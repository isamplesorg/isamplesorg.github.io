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
    "isamples_202608_search_index_v1/df.parquet",
]


def head(base, name):
    """Probe a file without downloading it.

    The data.isamples.org Worker 403s HEAD, so use a 1-byte ranged GET (the
    same primitive DuckDB-WASM relies on) and read the total from
    Content-Range: "bytes 0-0/TOTAL".
    """
    # data.isamples.org 403s the default Python-urllib User-Agent (UA-based bot
    # filtering); identify honestly instead.
    req = urllib.request.Request(f"{base}/{name}", headers={
        "Range": "bytes=0-0",
        "User-Agent": "isamples-release-manifest-builder/1.0 (+https://github.com/isamplesorg/isamplesorg.github.io)",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        if r.status not in (200, 206):
            raise RuntimeError(f"HTTP {r.status} for {name}")
        h = r.headers
        size = None
        cr = h.get("Content-Range", "")
        if "/" in cr:
            tail = cr.rsplit("/", 1)[-1]
            if tail.isdigit():
                size = int(tail)
        if size is None:  # origin ignored Range and returned the whole body header
            cl = h.get("Content-Length")
            if cl and cl.isdigit() and r.status == 200:
                size = int(cl)
        return {
            "size_bytes": size,
            "etag": (h.get("ETag") or "").strip('"') or None,
            "last_modified": h.get("Last-Modified"),
        }


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="https://data.isamples.org")
    ap.add_argument("--out", metavar="FILE")
    args = ap.parse_args()

    files, errors = {}, []
    for name in CANONICAL_FILES + SEARCH_INDEX_SIDECARS:
        try:
            meta = head(args.base, name)
            if meta["size_bytes"] in (None, 0):
                errors.append(f"{name}: missing/zero Content-Length")
            files[name] = meta
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")

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
            "object_count_expected": 852,
            "note": "sidecars pinned above; shards validate via build_stats.json",
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
