#!/usr/bin/env python3
"""
Build the supplementary parquet files that power the explorer's *collection*
facet (issue #243).

A "collection" is the human-readable **label** of a SamplingSite (e.g. the
OpenContext project "PKAP Survey Area"). That identity does NOT live on the
MaterialSampleRecord rows the explorer renders; it is reached by traversal
through the wide parquet's relationship arrays:

    MaterialSampleRecord.p__produced_by[1]  -> SamplingEvent.row_id
    SamplingEvent.p__sampling_site[1]        -> SamplingSite.row_id
    SamplingSite.label                       -> the collection name

Many SamplingSite rows share one label (e.g. ~1,336 rows are "PKAP Survey
Area"), so a collection aggregates over all of them. We therefore key a
collection on a stable hash of (source, label), NOT on a site pid.

Doing this traversal live in DuckDB-WASM per facet interaction is the
documented in-browser bottleneck, so we precompute here. Two ADDITIVE outputs
(they touch none of the existing facet files):

  1. collections.parquet      -- dimension, one row per collection:
       collection_id, label, source, n_samples,
       centroid_lat, centroid_lng, min_lat, max_lat, min_lng, max_lng
     Powers the top-N checkbox list, the long-tail search box, and the
     Featured-Collections preset camera targets.

  2. sample_collections.parquet -- membership, one row per sample that has a
     collection: pid, collection_id
     The explorer filters with:
       AND pid IN (SELECT pid FROM read_parquet('<sample_collections>')
                   WHERE collection_id IN (...))
     exactly parallel to the existing facet predicate at explorer.qmd:942.

Usage:
    python build_collections.py \
        --wide https://data.isamples.org/current/wide.parquet \
        --out-dir /tmp/collections_build \
        --snapshot 202604

Verify against the live data without writing files:
    python build_collections.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import duckdb

DEFAULT_WIDE = "https://data.isamples.org/current/wide.parquet"


def build(wide_url: str, out_dir: str, snapshot: str, dry_run: bool) -> dict:
    con = duckdb.connect()
    con.sql("INSTALL httpfs; LOAD httpfs;")

    t0 = time.time()
    # Pull only the columns the traversal needs, for the three entity types.
    con.sql(
        f"""
        CREATE TEMP TABLE w AS
        SELECT row_id, pid, otype, n AS source, label, latitude, longitude,
               p__produced_by, p__sampling_site
        FROM read_parquet('{wide_url}')
        WHERE otype IN ('MaterialSampleRecord','SamplingEvent','SamplingSite')
        """
    )
    print(f"[1/4] loaded traversal columns in {time.time() - t0:.1f}s")

    # Lookup tables for the two hops.
    con.sql(
        "CREATE TEMP TABLE site AS "
        "SELECT row_id AS site_rid, label AS site_label "
        "FROM w WHERE otype='SamplingSite' AND label IS NOT NULL"
    )
    # Unnest the sampling_site array so an event with multiple sites maps to
    # all of them (not just the first).
    con.sql(
        "CREATE TEMP TABLE evt AS "
        "SELECT row_id AS evt_rid, UNNEST(p__sampling_site) AS site_rid "
        "FROM w WHERE otype='SamplingEvent' AND p__sampling_site IS NOT NULL"
    )

    # Per-sample collection membership. Unnest BOTH relationship arrays
    # (produced_by → events, sampling_site → sites) so a sample with multiple
    # events / a site list joins through all of them — otherwise a member could
    # be silently dropped from a non-first collection. DISTINCT collapses the
    # fan-out to one row per (pid, collection). collection_id is a stable 16-hex
    # digest of (source, label) so it survives rebuilds and is URL-safe.
    con.sql(
        """
        CREATE TEMP TABLE memb AS
        SELECT DISTINCT
            s.pid AS pid,
            substr(md5(coalesce(s.source,'') || '\x1f' || st.site_label), 1, 16) AS collection_id,
            st.site_label AS label,
            s.source AS source,
            s.latitude AS lat,
            s.longitude AS lng
        FROM (
            SELECT pid, source, latitude, longitude, UNNEST(p__produced_by) AS evt_rid
            FROM w
            WHERE otype='MaterialSampleRecord' AND pid IS NOT NULL
              AND p__produced_by IS NOT NULL
        ) s
        JOIN evt e ON e.evt_rid = s.evt_rid
        JOIN site st ON st.site_rid = e.site_rid
        """
    )
    print(f"[2/4] built membership in {time.time() - t0:.1f}s")

    # Collections dimension (one row per collection).
    con.sql(
        """
        CREATE TEMP TABLE collections AS
        SELECT
            collection_id,
            any_value(label) AS label,
            any_value(source) AS source,
            COUNT(DISTINCT pid) AS n_samples,
            round(median(lat), 5) AS centroid_lat,
            round(median(lng), 5) AS centroid_lng,
            round(min(lat), 5) AS min_lat,
            round(max(lat), 5) AS max_lat,
            round(min(lng), 5) AS min_lng,
            round(max(lng), 5) AS max_lng
        FROM memb
        GROUP BY collection_id
        """
    )

    stats = {
        "samples_with_collection": con.sql("SELECT COUNT(DISTINCT pid) FROM memb").fetchone()[0],
        "n_collections": con.sql("SELECT COUNT(*) FROM collections").fetchone()[0],
        "pkap_samples": con.sql(
            "SELECT n_samples FROM collections WHERE label='PKAP Survey Area'"
        ).fetchone(),
    }
    print(f"[3/4] aggregated {stats['n_collections']:,} collections; "
          f"{stats['samples_with_collection']:,} samples carry one")
    pkap = stats["pkap_samples"][0] if stats["pkap_samples"] else None
    print(f"      PKAP Survey Area -> {pkap} samples "
          f"(expected ~15,446)")

    print("\n      Top 10 collections by sample count:")
    print(con.sql(
        "SELECT label, source, n_samples, centroid_lat, centroid_lng "
        "FROM collections ORDER BY n_samples DESC LIMIT 10"
    ).df().to_string(index=False))

    if dry_run:
        print("\n[4/4] --dry-run: no files written")
        return stats

    os.makedirs(out_dir, exist_ok=True)
    dim_path = os.path.join(out_dir, f"isamples_{snapshot}_collections.parquet")
    memb_path = os.path.join(out_dir, f"isamples_{snapshot}_sample_collections.parquet")

    con.sql(
        f"COPY (SELECT * FROM collections ORDER BY n_samples DESC) "
        f"TO '{dim_path}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    con.sql(
        # Order by collection_id so the explorer's `WHERE collection_id IN (...)`
        # filter can prune row groups (and it compresses better).
        f"COPY (SELECT DISTINCT pid, collection_id FROM memb ORDER BY collection_id, pid) "
        f"TO '{memb_path}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    print(f"\n[4/4] wrote:\n  {dim_path} ({os.path.getsize(dim_path)/1e6:.1f} MB)"
          f"\n  {memb_path} ({os.path.getsize(memb_path)/1e6:.1f} MB)")
    stats["dim_path"] = dim_path
    stats["memb_path"] = memb_path
    return stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build collection facet parquet files (#243)")
    ap.add_argument("--wide", default=DEFAULT_WIDE,
                    help="wide parquet URL (default: %(default)s)")
    ap.add_argument("--out-dir", default="/tmp/collections_build",
                    help="output directory (default: %(default)s)")
    ap.add_argument("--snapshot", default="202604",
                    help="snapshot tag for filenames (default: %(default)s)")
    ap.add_argument("--dry-run", action="store_true",
                    help="compute and report, but write no files")
    args = ap.parse_args(argv)

    try:
        build(args.wide, args.out_dir, args.snapshot, args.dry_run)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
