#!/usr/bin/env python3
"""#300: add h3_res4/h3_res6 to an existing samples_map_lite without the wide.

The published 202608 lite already carries pid/label/source/lat/lng/place_name/
result_time/h3_res8/h3_res8_hex. h3_res4 and h3_res6 are pure functions of the
SAME rounded lat/lng the build used (build_frontend_derived.py samp_geo computes
them off ROUND(ST_Y,6)/ROUND(ST_X,6), which is exactly what lite stores) via
h3_latlng_to_cell at each resolution — so we derive them the IDENTICAL way and
avoid rebuilding from the (now-gone) /tmp wide.

NOTE: H3 cells do NOT strictly nest, so h3_latlng_to_cell(...,4) is NOT in general
the parent of h3_latlng_to_cell(...,8) — the build uses per-resolution
latlng_to_cell, never cell_to_parent, and so do we.

Validation cross-checks the derived res4/res6 against the SHIPPED
h3_summary_res{4,6} parquets (built off the same samp_geo): GROUP BY the new h3
column must reproduce each summary's (h3_cell, sample_count) exactly. Plus res8
preserved, row count preserved, no NULLs. Refuse to write otherwise.

Usage: regen_lite_res46.py SRC OUT SUMMARY_DIR TAG
"""
import os
import sys
import duckdb

SRC = sys.argv[1]
OUT = sys.argv[2]
SUMMARY_DIR = sys.argv[3]
TAG = sys.argv[4]

con = duckdb.connect()
con.execute("INSTALL h3 FROM community; LOAD h3;")

con.execute(f"""
    CREATE TEMP TABLE newlite AS
    SELECT pid, label, source, latitude, longitude, place_name, result_time,
           h3_latlng_to_cell(latitude, longitude, 4)::UBIGINT AS h3_res4,
           h3_latlng_to_cell(latitude, longitude, 6)::UBIGINT AS h3_res6,
           h3_res8::UBIGINT AS h3_res8,
           h3_res8_hex
    FROM read_parquet('{SRC}')
""")

# --- Validation 1: derived res4/res6 reproduce the SHIPPED h3 summaries exactly ---
# (the authoritative cross-check — both come from the same samp_geo latlng_to_cell)
for res in (4, 6, 8):
    summ = os.path.join(SUMMARY_DIR, f"{TAG}_h3_summary_res{res}.parquet")
    mism = con.execute(f"""
        WITH mine AS (
            SELECT h3_res{res} AS cell, COUNT(*) AS c FROM newlite
            WHERE h3_res{res} IS NOT NULL GROUP BY h3_res{res}
        ),
        summ AS (
            SELECT h3_cell AS cell, sample_count AS c FROM read_parquet('{summ}')
        )
        SELECT
          (SELECT COUNT(*) FROM mine FULL OUTER JOIN summ USING (cell)
           WHERE mine.c IS DISTINCT FROM summ.c) AS bad
    """).fetchone()[0]
    if mism:
        raise SystemExit(f"FATAL: res{res} GROUP BY disagrees with shipped summary in {mism} cells")

# --- Validation 2: row count + res8 preserved exactly ---
n_src = con.execute(f"SELECT COUNT(*) FROM read_parquet('{SRC}')").fetchone()[0]
n_new = con.execute("SELECT COUNT(*) FROM newlite").fetchone()[0]
res8_mismatch = con.execute(f"""
    SELECT COUNT(*) FROM newlite n
    JOIN read_parquet('{SRC}') s ON s.pid = n.pid
    WHERE n.h3_res8 IS DISTINCT FROM s.h3_res8::UBIGINT
""").fetchone()[0]
if n_src != n_new or res8_mismatch:
    raise SystemExit(f"FATAL: rows src={n_src} new={n_new}, res8_mismatch={res8_mismatch}")

# --- Validation 3: no NULL res4/res6 where coords present ---
nulls = con.execute("""
    SELECT COUNT(*) FROM newlite
    WHERE latitude IS NOT NULL AND longitude IS NOT NULL
      AND (h3_res4 IS NULL OR h3_res6 IS NULL)
""").fetchone()[0]
if nulls:
    raise SystemExit(f"FATAL: {nulls} located rows with NULL res4/res6")

con.execute(f"""
    COPY (SELECT * FROM newlite ORDER BY pid)
    TO '{OUT}' (FORMAT PARQUET, COMPRESSION ZSTD)
""")

cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet('{OUT}')").fetchall()]
print(f"OK rows={n_new:,}  res8_preserved  res4/res6 GROUP BY == shipped h3 summaries")
print(f"columns: {cols}")
