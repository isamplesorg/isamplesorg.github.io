"""
HTTP contract tests for the data origin (`data.isamples.org`).

WHY THIS FILE EXISTS
--------------------
The Explorer's whole architecture rests on one assumption: DuckDB-WASM fetches
only the byte ranges a query touches. In August 2026 we discovered that had been
silently false — a cold load transferred **~74 MB before anything was usable, instead
of ~3.5 MB** because
DuckDB's range-support probe was answered in a way it did not accept, so it fell
back to downloading whole files (#345).

That regression was invisible to every existing test. It was also *mis-cleared*
in June (`ISSUE_313_FINDINGS_2026-06-26.md`) by a `curl` probe that used **GET**
where DuckDB uses **HEAD** — the check looked right and proved nothing.

These tests are deliberately cheap: no browser, no DuckDB, a handful of bytes on
the wire. They run before the Playwright smoke gate so this class of failure is
caught before anything downloads 74 MB to discover it.

MAINTENANCE NOTE
----------------
`tools/build_release_manifest.py` performs the ranged-GET probe but NOT the HEAD
probe — which is exactly why it could report a healthy origin while DuckDB was
broken. If you touch either, keep them in sync.
"""
import json
import os
import pathlib

import pytest
import requests

ORIGIN = os.environ.get("ISAMPLES_DATA_ORIGIN", "https://data.isamples.org")
PAGE_ORIGIN = "https://isamples.org"
MANIFEST = pathlib.Path(__file__).resolve().parent.parent / "isamples_202608_release_manifest.json"

# The Worker 403s some default user agents; identify honestly.
UA = {"User-Agent": "isamples-ci-contract/1.0 (+https://isamples.org)"}
TIMEOUT = 30


def _manifest_files():
    if not MANIFEST.exists():
        pytest.skip(f"release manifest not found at {MANIFEST}")
    return json.loads(MANIFEST.read_text())["files"]


def _boot_critical_large_file():
    """The biggest boot-critical parquet — the one a full read actually hurts.

    Skips (rather than fails) if the origin does not serve it. Without this a
    404 from, say, a partially-seeded local test origin gets reported as
    "the shim has widened", which is a confidently wrong diagnosis — the exact
    failure mode this whole file exists to prevent.
    """
    files = _manifest_files()
    name = None
    for candidate in ("isamples_202608_samples_map_lite_v3.parquet",
                      "isamples_202608_sample_facet_masks.parquet"):
        if candidate in files:
            name = candidate
            break
    if name is None:
        name = max(files.items(), key=lambda kv: kv[1].get("size_bytes", 0))[0]

    probe = requests.head(f"{ORIGIN}/{name}", headers=UA, timeout=TIMEOUT)
    if probe.status_code == 404:
        pytest.skip(f"{ORIGIN} does not serve {name} (404) — not a contract failure")
    return name, files[name]["size_bytes"]


def test_ranged_get_returns_206_with_exact_content_range():
    """The load-bearing property: partial GETs work and report the full size.

    This one passes today and has always passed — which is precisely why it was
    not enough on its own. Keep it: if it ever breaks, range reads are dead.
    """
    name, size = _boot_critical_large_file()
    r = requests.get(f"{ORIGIN}/{name}",
                     headers={**UA, "Range": "bytes=0-0", "Origin": PAGE_ORIGIN},
                     timeout=TIMEOUT)
    assert r.status_code == 206, f"ranged GET returned {r.status_code}, not 206"
    assert r.headers.get("Content-Range") == f"bytes 0-0/{size}", (
        f"Content-Range {r.headers.get('Content-Range')!r} disagrees with the "
        f"manifest size {size}")
    assert len(r.content) == 1, f"ranged GET returned {len(r.content)} bytes, expected 1"


def test_cors_exposes_headers_the_explorer_must_read():
    """Cross-origin JS cannot see Content-Range/Accept-Ranges unless exposed."""
    name, _ = _boot_critical_large_file()
    r = requests.get(f"{ORIGIN}/{name}",
                     headers={**UA, "Range": "bytes=0-0", "Origin": PAGE_ORIGIN},
                     timeout=TIMEOUT)
    exposed = (r.headers.get("Access-Control-Expose-Headers") or "").lower()
    for h in ("content-range", "accept-ranges", "content-length"):
        assert h in exposed, f"{h} not in Access-Control-Expose-Headers ({exposed!r})"
    assert r.headers.get("Access-Control-Allow-Origin") in ("*", PAGE_ORIGIN)


def test_duckdb_124_head_range_compatibility():
    # The #345 shim went live on data.isamples.org on 2026-08-27 (Worker version
    # 6f8170a7…); this test is now a hard gate. If it fails, DuckDB-WASM is back to
    # downloading whole files (~74 MB before the facets are usable) — see #345/#351.
    """DuckDB-WASM 1.24.0's range-support probe must be answered with 206.

    *** THIS ASSERTS A DELIBERATE STANDARDS DIVERGENCE. ***

    RFC 9110 section 14.2: Range is defined only for GET, and a server MUST
    IGNORE it on other methods including HEAD. A plain 200 here is the CORRECT
    HTTP answer. But DuckDB-WASM 1.24.0 — the version Quarto's OJS runtime pins
    — probes with exactly `HEAD` + `Range: bytes=0-` and treats anything other
    than 206 as "this server cannot do partial reads", then downloads whole
    files.

    So this test encodes a compatibility shim, not correct HTTP. It should be
    DELETED, along with the Worker shim, once the Explorer no longer depends on
    that probe (i.e. when it stops using the pinned duckdb-wasm and does its own
    init on a conformant version). See #345.
    """
    name, size = _boot_critical_large_file()
    r = requests.head(f"{ORIGIN}/{name}",
                      headers={**UA, "Range": "bytes=0-", "Origin": PAGE_ORIGIN},
                      timeout=TIMEOUT)
    assert r.status_code == 206, (
        f"HEAD+Range returned {r.status_code}. DuckDB-WASM will fall back to full "
        f"HTTP reads and the Explorer will transfer tens of MB on cold load.")
    assert r.headers.get("Content-Range") == f"bytes 0-{size - 1}/{size}"
    assert r.headers.get("Content-Length") == str(size)
    assert not r.content, "HEAD must not return a body"


def test_shim_does_not_widen_to_other_ranged_heads():
    """The #345 shim must stay scoped to the exact probe shape.

    Any OTHER ranged HEAD must remain standards-correct (200, no Content-Range),
    so the divergence cannot leak to other clients or harden into a contract we
    did not intend to offer.
    """
    name, _ = _boot_critical_large_file()
    for rng in ("bytes=0-99", "bytes=100-199", "bytes=-100"):
        r = requests.head(f"{ORIGIN}/{name}",
                          headers={**UA, "Range": rng, "Origin": PAGE_ORIGIN},
                          timeout=TIMEOUT)
        assert r.status_code == 200, (
            f"HEAD with {rng!r} returned {r.status_code}; the #345 shim has widened "
            f"beyond the single DuckDB probe shape and is now diverging from RFC 9110 "
            f"more than intended")
        assert "Content-Range" not in r.headers, (
            f"HEAD with {rng!r} carried a Content-Range; see above")


def test_manifest_sizes_match_the_origin():
    """Catches the data/doc drift class: manifest says one size, origin serves another."""
    files = _manifest_files()
    checked = 0
    for name, meta in files.items():
        if not name.endswith(".parquet") or "/" in name:
            continue
        size = meta.get("size_bytes")
        if not size:
            continue
        r = requests.head(f"{ORIGIN}/{name}", headers=UA, timeout=TIMEOUT)
        assert r.status_code == 200, f"{name}: HEAD returned {r.status_code}"
        assert r.headers.get("Content-Length") == str(size), (
            f"{name}: manifest says {size} bytes, origin serves "
            f"{r.headers.get('Content-Length')}")
        checked += 1
    assert checked > 0, "no parquet entries checked — manifest shape may have changed"
