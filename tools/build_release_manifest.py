#!/usr/bin/env python3
"""build_release_manifest.py — emit the canonical release manifest (#334 v0-detect).

The manifest is the machine-readable twin of CANONICAL.md: it enumerates exactly
the data files the Explorer is entitled to load for a release, with per-file
size/etag/last-modified gathered from HTTP HEAD against the live origin (no
downloads). The Explorer fetches this at boot and cross-checks its pinned URLs
(v0 = DETECT divergence loudly; deriving URLs from the manifest is v1, post-grant
— see #334).

Usage:
    python3 tools/build_release_manifest.py                       # print JSON
    python3 tools/build_release_manifest.py --out isamples_202608_release_manifest.json
    python3 tools/build_release_manifest.py --base https://data.isamples.org

Fail-closed: any missing file or non-200 HEAD aborts with exit 1 — a manifest
must never be generated from a broken origin. (Policy learned 2026-07-18.)
<!-- cc:2026.07.23 -->
"""
import argparse
import datetime
import json
import sys
import urllib.request

RELEASE_ID = "isamples_202608"

# The canonical set. Keep in lockstep with CANONICAL.md §1 — a suffix bump edits
# BOTH in the same change (policy in CANONICAL.md §2).
CANONICAL_FILES = [
    "isamples_202608_wide.parquet",
    "isamples_202608_samples_map_lite_v3.parquet",
    "isamples_202608_sample_facets_v4.parquet",
    "isamples_202608_h3_summary_res4.parquet",
    "isamples_202608_h3_summary_res6.parquet",
    "isamples_202608_h3_summary_res8.parquet",
    "isamples_202608_facet_summaries.parquet",
    "isamples_202608_facet_cross_filter.parquet",
    "isamples_202608_facet_tree_summaries.parquet",
    "isamples_202608_facet_tree_cross_filter.parquet",
    "isamples_202608_sample_facet_membership.parquet",
    "isamples_202608_sample_facet_masks.parquet",
    "isamples_202608_facet_node_bits.parquet",
    "isamples_202608_sample_facet_index.parquet",
    "isamples_202608_sample_facet_index_meta.parquet",
    "vocab_labels_202608.parquet",
]

# The search index is a directory of ~852 objects; the manifest pins its
# self-describing sidecars (the index validates itself via build_stats).
SEARCH_INDEX_SIDECARS = [
    "isamples_202608_search_index_v1/build_stats.json",
    "isamples_202608_search_index_v1/hot_tokens.json",
    "isamples_202608_search_index_v1/shard_sizes.json",
    "isamples_202608_search_index_v1/hot_topk.parquet",   # loaded by the topk query path
    # df.parquet is OFFLINE-ONLY per SEARCH_INDEX_V1.md — archived, not runtime;
    # it is probed for existence but excluded from the Explorer's runtime check.
    "isamples_202608_search_index_v1/df.parquet",
]


UA = "isamples-release-manifest-builder/1.0 (+https://github.com/isamplesorg/isamplesorg.github.io)"


def head(base, name, permissive=False):
    """Probe a file without downloading it (1-byte ranged GET).

    The data.isamples.org Worker 403s HEAD and the default Python UA, so we use
    a ranged GET with an honest UA — the same primitive DuckDB-WASM relies on.
    STRICT by default (Codex P1): require 206 + exact Content-Range + one byte
    + an ETag. Anything else (200-with-HTML proxy page, broken Range support —
    the very capability the Explorer needs, missing integrity metadata) refuses.
    --permissive relaxes for dev mirrors.
    """
    req = urllib.request.Request(f"{base}/{name}", headers={
        "Range": "bytes=0-0", "User-Agent": UA,
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
        h = r.headers
        etag = (h.get("ETag") or "").strip('"') or None
        cr = h.get("Content-Range", "")
        size = None
        m = cr.split("/")[-1] if "/" in cr else ""
        if m.isdigit():
            size = int(m)
        if not permissive:
            if r.status != 206:
                raise RuntimeError(f"{name}: expected 206, got {r.status} (Range support broken?)")
            if not cr.startswith("bytes 0-0/") or size is None:
                raise RuntimeError(f"{name}: bad Content-Range {cr!r}")
            if len(body) != 1:
                raise RuntimeError(f"{name}: expected 1 byte, got {len(body)}")
            if not etag:
                raise RuntimeError(f"{name}: missing ETag (no integrity metadata)")
        elif size is None:
            cl = h.get("Content-Length")
            size = int(cl) if cl and cl.isdigit() and r.status == 200 else None
        return {"size_bytes": size, "etag": etag, "last_modified": h.get("Last-Modified")}


def fetch_json(base, name):
    req = urllib.request.Request(f"{base}/{name}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        if r.status != 200:
            raise RuntimeError(f"HTTP {r.status} for {name}")
        return json.loads(r.read().decode())


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="https://data.isamples.org")
    ap.add_argument("--out", metavar="FILE")
    ap.add_argument("--permissive", action="store_true",
                    help="relax probe strictness for dev mirrors")
    args = ap.parse_args()

    files, errors = {}, []
    for name in CANONICAL_FILES + SEARCH_INDEX_SIDECARS:
        try:
            meta = head(args.base, name, permissive=args.permissive)
            if meta["size_bytes"] in (None, 0):
                errors.append(f"{name}: missing/zero size")
            files[name] = meta
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")

    # Shard inventory from the index's own shard_sizes.json (Codex P1: the
    # object count must come from data, not a hard-coded 852).
    shard_count, shard_bytes = None, None
    try:
        sizes = fetch_json(args.base, "isamples_202608_search_index_v1/shard_sizes.json")
        entries = sizes if isinstance(sizes, dict) else {}
        if not entries:
            errors.append("shard_sizes.json: empty/unexpected shape")
        else:
            shard_count = len(entries)
            vals = list(entries.values())
            shard_bytes = sum(v for v in vals if isinstance(v, int)) or None
    except Exception as e:  # noqa: BLE001
        errors.append(f"shard_sizes.json inventory: {e}")

    if errors:
        print("REFUSING to emit manifest — origin problems:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    manifest = {
        "schema_version": 1,
        "release_id": RELEASE_ID,
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc)
            .isoformat(timespec="seconds"),
        "base": args.base,
        "files": files,
        "search_index": {
            "path": "isamples_202608_search_index_v1/",
            "shard_count": shard_count,
            "shard_bytes_total": shard_bytes,
            "runtime_sidecars": ["build_stats.json", "hot_tokens.json",
                                  "shard_sizes.json", "hot_topk.parquet"],
            "offline_only": ["df.parquet"],
            "note": "shard inventory derived from shard_sizes.json at generation time",
        },
        "docs": "CANONICAL.md (human twin); #334 v0-detect",
    }
    text = json.dumps(manifest, indent=1)
    print(text)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text + "\n")
        print(f"wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
