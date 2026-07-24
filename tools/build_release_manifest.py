#!/usr/bin/env python3
"""build_release_manifest.py — emit the canonical release manifest (#334 v0-detect).

The manifest is the machine-readable twin of CANONICAL.md: it enumerates exactly
the data files the Explorer is entitled to load for a release, with per-file
size/etag/last-modified gathered via strict ranged GETs against the live origin (no
downloads). The Explorer fetches this at boot and cross-checks its pinned URLs
(v0 = DETECT divergence loudly; deriving URLs from the manifest is v1, post-grant
— see #334).

Usage:
    python3 tools/build_release_manifest.py                       # print JSON
    python3 tools/build_release_manifest.py --out isamples_202608_release_manifest.json
    python3 tools/build_release_manifest.py --base https://data.isamples.org

Fail-closed: any missing file or non-strict probe result aborts with exit 1 — a
manifest must never be generated from a broken origin. (Policy learned 2026-07-18.)
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
    import re as _re
    req = urllib.request.Request(f"{base}/{name}", headers={
        "Range": "bytes=0-0", "User-Agent": UA,
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        h = r.headers
        etag = (h.get("ETag") or "").strip('"') or None
        cr = h.get("Content-Range", "")
        m = _re.fullmatch(r"bytes 0-0/(\d+)", cr)
        size = int(m.group(1)) if m else None
        if not permissive:
            # Validate status + headers BEFORE touching the body, so a
            # Range-ignoring origin can't make us download a 300 MB object.
            if r.status != 206:
                raise RuntimeError(f"{name}: expected 206, got {r.status} (Range support broken?)")
            if size is None or size <= 0:
                raise RuntimeError(f"{name}: bad Content-Range {cr!r}")
            if not etag:
                raise RuntimeError(f"{name}: missing ETag (no integrity metadata)")
            body = r.read(2)   # bounded: expect exactly the 1 requested byte
            if len(body) != 1:
                raise RuntimeError(f"{name}: expected 1 byte, got {len(body)}")
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

    # Shard inventory, cross-validated between the index's own artifacts
    # (Codex rounds 1-2: counts come from data; shard_sizes.json covers only
    # the BASE shards — hot-token sub-files are counted in build_stats.json).
    inv = {"base_shard_count": None, "base_shard_bytes": None,
           "total_shard_files": None, "hot_shard_files": None}
    try:
        sizes = fetch_json(args.base, "isamples_202608_search_index_v1/shard_sizes.json")
        entries = sizes if isinstance(sizes, dict) else {}
        if not entries:
            errors.append("shard_sizes.json: empty/unexpected shape")
        else:
            inv["base_shard_count"] = len(entries)
            inv["base_shard_bytes"] = sum(v for v in entries.values() if isinstance(v, int)) or None
    except Exception as e:  # noqa: BLE001
        errors.append(f"shard_sizes.json inventory: {e}")
    try:
        stats = fetch_json(args.base, "isamples_202608_search_index_v1/build_stats.json")
        # build_stats: shard_count = LOGICAL shards (256, matches shard_sizes);
        # shard_files = PHYSICAL files (base + hot-token sub-files).
        tot = stats.get("shard_files")
        logical = stats.get("shard_count")
        if not (isinstance(tot, int) and tot > 0):
            errors.append("build_stats.json: missing/invalid shard_files")
            tot = None
        if not (isinstance(logical, int) and logical > 0):
            # Hard requirement (Codex round 3): absence must fail, not slide by.
            errors.append("build_stats.json: missing/invalid shard_count (logical)")
        elif inv["base_shard_count"] and logical != inv["base_shard_count"]:
            errors.append(f"inventory contradiction: build_stats logical shards {logical} "
                          f"!= shard_sizes entries {inv['base_shard_count']}")
        inv["total_shard_files"] = tot
    except Exception as e:  # noqa: BLE001
        errors.append(f"build_stats.json inventory: {e}")
    try:
        # Hot sub-files enumerated from their authoritative source: each
        # hot_tokens.json entry declares its physical sub_files count.
        ht = fetch_json(args.base, "isamples_202608_search_index_v1/hot_tokens.json")
        toks = ht.get("tokens")
        if not isinstance(toks, dict) or not toks:
            errors.append("hot_tokens.json: missing/empty tokens map")
        else:
            bad = [t for t, v in toks.items()
                   if not isinstance(v, dict) or not isinstance(v.get("sub_files"), int)
                   or v["sub_files"] < 1]
            if bad:
                errors.append(f"hot_tokens.json: malformed entries: {bad[:5]}")
            else:
                inv["hot_shard_files"] = sum(v["sub_files"] for v in toks.values())
                inv["hot_token_count"] = len(toks)
        # Three-way cross-check: base (shard_sizes) + hot (hot_tokens) must
        # equal physical shard_files (build_stats). Any disagreement refuses.
        if (inv["base_shard_count"] and inv.get("hot_shard_files") is not None
                and inv["total_shard_files"] is not None
                and inv["base_shard_count"] + inv["hot_shard_files"] != inv["total_shard_files"]):
            errors.append(f"inventory contradiction: base {inv['base_shard_count']} + "
                          f"hot {inv['hot_shard_files']} != shard_files {inv['total_shard_files']}")
    except Exception as e:  # noqa: BLE001
        errors.append(f"hot_tokens.json inventory: {e}")

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
            **inv,
            "runtime_sidecars": ["build_stats.json", "hot_tokens.json",
                                  "shard_sizes.json", "hot_topk.parquet"],
            "offline_only": ["df.parquet"],
            "note": "base shards from shard_sizes.json; hot sub-files enumerated "
                     "from hot_tokens.json; totals cross-checked vs build_stats shard_files",
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
