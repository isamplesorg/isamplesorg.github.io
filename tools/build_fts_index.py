#!/usr/bin/env python3
"""
STATUS: spike artifact — NOT in production pipeline.

Build a DuckDB full-text search index for the iSamples Explorer.

This script was used to evaluate whether DuckDB FTS could replace the
ILIKE-based search in the Explorer. Findings (PR #95):
  - Full index (label + description + place_name): 358 MB
  - Lite index (label + place_name only):          211 MB
  - ATTACH-over-HTTP works in DuckDB-WASM, but the download is too
    large for an interactive page.
The Explorer continues to use ILIKE; this script is preserved so we
can revisit FTS once we have a smaller index strategy (e.g.
pre-tokenized inverted index as parquet, or on-demand loading behind
an "Enhanced Search" toggle).

Usage:
    python tools/build_fts_index.py

Output:
    tools/isamples_fts_index.duckdb  (NOT currently uploaded anywhere)

Requirements:
    pip install duckdb
"""

import duckdb
import os
import sys
from pathlib import Path

PARQUET_URL = "https://data.isamples.org/isamples_202601_wide.parquet"
OUTPUT_DB = Path(__file__).parent / "isamples_fts_index.duckdb"

# Local fallback for faster builds
LOCAL_PARQUET = Path.home() / "Data/iSample/pqg_refining/zenodo_wide_2026-01-09.parquet"


def build_fts_index():
    # Use local file if available, otherwise remote
    source = str(LOCAL_PARQUET) if LOCAL_PARQUET.exists() else PARQUET_URL
    print(f"Source: {source}")

    # Remove existing index file
    if OUTPUT_DB.exists():
        OUTPUT_DB.unlink()

    con = duckdb.connect(str(OUTPUT_DB))

    print("Creating samples table from parquet...")
    con.execute(f"""
        CREATE TABLE samples AS
        SELECT
            pid,
            label,
            COALESCE(description, '') AS description,
            COALESCE(CAST(place_name AS VARCHAR), '') AS place_name
        FROM read_parquet('{source}')
        WHERE otype = 'MaterialSampleRecord'
    """)

    row_count = con.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
    print(f"Loaded {row_count:,} rows")

    print("Installing and loading FTS extension...")
    con.execute("INSTALL fts")
    con.execute("LOAD fts")

    print("Building FTS index (this may take a few minutes)...")
    con.execute("""
        PRAGMA create_fts_index(
            'samples', 'pid',
            'label', 'description', 'place_name',
            stemmer = 'porter',
            stopwords = 'english',
            overwrite = 1
        )
    """)

    # Verify the index works
    test_result = con.execute("""
        SELECT pid, fts_main_samples.match_bm25(pid, 'pottery') AS score
        FROM samples
        WHERE score IS NOT NULL
        ORDER BY score DESC
        LIMIT 5
    """).fetchall()
    print(f"Test query 'pottery': {len(test_result)} results")
    for pid, score in test_result:
        print(f"  {pid[:60]}  score={score:.4f}")

    # Keep samples table — FTS macros reference it internally.
    # The table has only pid + text columns (not the full schema),
    # so it's much smaller than the full parquet.

    con.close()

    size_mb = OUTPUT_DB.stat().st_size / (1024 * 1024)
    print(f"\nIndex file: {OUTPUT_DB}")
    print(f"Size: {size_mb:.1f} MB")
    print(f"\nNOTE: Index is too large to ship to the browser as-is.")
    print(f"      See module docstring for the spike findings.")


if __name__ == "__main__":
    build_fts_index()
