#!/usr/bin/env python3
"""Build an enriched unified-wide parquet by left-joining OC thumbnails.

Takes the unified Zenodo wide parquet (which has thumbnail_url = NULL for all
6.7M samples because the upstream iSamples export doesn't carry thumbnails —
see issue #131) and fills in thumbnail_url for the ~47K OpenContext samples
that appear in Eric Kansa's oc_isamples_pqg.parquet.

Input:
    --src          local path to source unified wide parquet
                   (e.g. ~/Data/iSample/pqg_refining/zenodo_wide_*.parquet)
    --oc           local path to Eric's oc_isamples_pqg.parquet (the narrow
                   one — thumbnails live on MaterialSampleRecord rows)
    --out          path to write the enriched output

Usage:
    python scripts/enrich_wide_with_oc_thumbnails.py \\
        --src ~/Data/iSample/pqg_refining/zenodo_wide_2026-01-09.parquet \\
        --oc  /tmp/oc_isamples_pqg_20251107.parquet \\
        --out /tmp/isamples_202604_wide.parquet

Then upload to R2 under a date-stamped filename (e.g. isamples_202604_wide.parquet)
and update current/manifest.json to point at it.
"""
import argparse
import os
import sys
import time
import duckdb


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--src', required=True, help='source unified wide parquet')
    p.add_argument('--oc',  required=True, help="Eric's OC narrow parquet (for thumbnails)")
    p.add_argument('--out', required=True, help='output path for enriched parquet')
    args = p.parse_args()

    for f in (args.src, args.oc):
        if not os.path.exists(f):
            print(f'ERROR: missing {f}', file=sys.stderr)
            return 2

    con = duckdb.connect()

    print(f'source: {args.src}')
    print(f'oc:     {args.oc}')
    print(f'out:    {args.out}')

    t0 = time.time()
    con.execute(f"""
        CREATE TEMP TABLE oc_thumbs AS
        SELECT DISTINCT pid, thumbnail_url
        FROM read_parquet('{args.oc}')
        WHERE thumbnail_url IS NOT NULL AND thumbnail_url <> ''
    """)
    n = con.sql('SELECT COUNT(*) FROM oc_thumbs').fetchone()[0]
    print(f'[{time.time()-t0:.1f}s] oc_thumbs lookup: {n:,} (pid, thumbnail) pairs')

    t0 = time.time()
    con.execute(f"""
        COPY (
          SELECT p.* REPLACE (COALESCE(oc.thumbnail_url, p.thumbnail_url) AS thumbnail_url)
          FROM read_parquet('{args.src}') p
          LEFT JOIN oc_thumbs oc ON p.pid = oc.pid
        )
        TO '{args.out}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    print(f'[{time.time()-t0:.1f}s] wrote enriched parquet')

    # Verify
    r = con.sql(f"""
        SELECT COUNT(*) AS rows,
               COUNT(*) FILTER (WHERE thumbnail_url IS NOT NULL AND thumbnail_url <> '') AS with_thumb
        FROM read_parquet('{args.out}')
    """).df()
    print(r.to_string(index=False))
    print(f'output size: {os.path.getsize(args.out)/1024/1024:.1f} MB')
    return 0


if __name__ == '__main__':
    sys.exit(main())
