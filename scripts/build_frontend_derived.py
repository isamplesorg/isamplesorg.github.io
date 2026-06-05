#!/usr/bin/env python3
"""Build the explorer's frontend-derived parquet files from a wide PQG parquet.

Closes the biggest provenance gap (see DATA_PROVENANCE.md): 6 of the 7 derived
files previously had no checked-in build script — only ad-hoc notebook SQL. This
reproduces them deterministically from one `wide` input.

Inputs:  a wide PQG parquet (e.g. isamples_YYYYMM_wide.parquet) — entity rows incl.
         MaterialSampleRecord + IdentifiedConcept, with `geometry` (WKB) and the
         `p__has_{material,context,sample_object}_category` row-id arrays.
Outputs (into --outdir, prefixed --tag, default `isamples_YYYYMM`):
  - {tag}_sample_facets_v2.parquet      pid, source, material, context, object_type, label, description, place_name
  - {tag}_samples_map_lite.parquet      pid, label, source, latitude, longitude, place_name[], result_time, h3_res8, h3_res8_hex
  - {tag}_wide_h3.parquet               wide + h3_res4/h3_res6/h3_res8  (large; use --skip wide_h3 to omit)
  - {tag}_h3_summary_res{4,6,8}.parquet h3_cell, sample_count, center_lat, center_lng, dominant_source, source_count, resolution
  - {tag}_facet_summaries.parquet       facet_type, facet_value, scheme, count
  - {tag}_facet_cross_filter.parquet    filter_source/material/context/object_type, facet_type, facet_value, count

Usage:
  python scripts/build_frontend_derived.py --wide WIDE.parquet --outdir OUT --tag isamples_202601
  python scripts/build_frontend_derived.py --wide WIDE.parquet --outdir OUT --validate-against docs/data
  python scripts/build_frontend_derived.py --wide WIDE.parquet --outdir OUT --only sample_facets_v2,facet_summaries
"""
import argparse, os, sys, time
import duckdb

FACET_DIMS = ["source", "material", "context", "object_type"]

# #265: the broad SKOS root concept for material. Source arrays (esp. SESAR)
# carry the full ancestry, and this root ("Material") can sit at ANY array
# position — so the old p__has_material_category[1] often surfaced it as a
# bogus facet value. We drop it during material selection. (context/object_type
# have analogous roots — `anysampledfeature`, `materialsample` — but those are
# meaningful "any/generic" values and far higher-volume, so we leave them on the
# [1] selection pending confirmation; tracked as a #265 follow-up.)
MATERIAL_ROOT = "https://w3id.org/isample/vocabulary/material/1.0/material"


def log(msg, t0):
    print(f"[{time.time()-t0:.1f}s] {msg}", flush=True)


def base_samples_sql(wide: str) -> str:
    """One row per MaterialSampleRecord with resolved source/facet URIs, lat/lng, h3."""
    return f"""
    CREATE OR REPLACE TEMP TABLE ic AS
      SELECT row_id, pid AS uri FROM read_parquet('{wide}') WHERE otype='IdentifiedConcept';
    -- row_id -> uri map, so we can resolve a whole concept array without a
    -- per-element correlated subquery (needed for the #265 most-specific pick).
    CREATE OR REPLACE TEMP TABLE icmap AS
      SELECT MAP(list(row_id), list(uri)) AS m FROM ic;
    CREATE OR REPLACE TEMP TABLE samp AS
      SELECT
        s.pid,
        s.n                                            AS source,
        s.label,
        s.description,
        s.place_name,                                  -- VARCHAR[]
        s.result_time,
        ST_Y(ST_GeomFromWKB(s.geometry))               AS latitude,
        ST_X(ST_GeomFromWKB(s.geometry))               AS longitude,
        -- #265: drop the broad root concept, then keep the original [1] order.
        -- The root ("Material") can sit at ANY array position; when it landed at
        -- position 1 the old p__has_material_category[1] surfaced it as a bogus
        -- facet value (346k samples). We resolve the whole array, filter out the
        -- root, and take the FIRST remaining concept. This is deliberately
        -- conservative: it changes ONLY samples whose [1] was the root (they now
        -- get their first real concept, or NULL if root-only -> excluded from the
        -- facet). Samples already labelled with a real concept are untouched —
        -- e.g. the ceramic ark:/28722/k2p55x96j keeps anthropogenicmetal rather
        -- than flipping to a deeper-but-wrong array entry. NOTE: this does not
        -- pick the most-SPECIFIC concept (the arrays are not clean SKOS paths,
        -- and some OC arrays end in an unrelated 'rock'); true leaf selection
        -- needs the SKOS hierarchy and is tracked as a #265 follow-up.
        (list_filter(
          list_transform(s.p__has_material_category, rid -> icmap.m[rid]),
          u -> u IS NOT NULL AND u <> '{MATERIAL_ROOT}'
        ))[1]                                          AS material,
        (SELECT uri FROM ic WHERE ic.row_id = s.p__has_context_category[1])    AS context,
        (SELECT uri FROM ic WHERE ic.row_id = s.p__has_sample_object_type[1])  AS object_type
      FROM read_parquet('{wide}') s, icmap
      WHERE s.otype='MaterialSampleRecord';
    -- coordinate-bearing subset + h3 cells (used by map_lite + h3 summaries)
    CREATE OR REPLACE TEMP TABLE samp_geo AS
      SELECT *,
             h3_latlng_to_cell(latitude, longitude, 4) AS h3_res4,
             h3_latlng_to_cell(latitude, longitude, 6) AS h3_res6,
             h3_latlng_to_cell(latitude, longitude, 8) AS h3_res8
      FROM samp WHERE latitude IS NOT NULL AND longitude IS NOT NULL;
    """


def build_sample_facets_v2(con, out):
    # located (coordinate-bearing) samples only — matches the published file,
    # which is map-scoped (5.98M = GeospatialCoordLocation count).
    con.execute(f"""COPY (
        SELECT pid, source, material, context, object_type, label, description,
               place_name::VARCHAR AS place_name
        FROM samp_geo
    ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)""")


def build_samples_map_lite(con, out):
    con.execute(f"""COPY (
        SELECT pid, label, source, latitude, longitude, place_name, result_time,
               h3_res8::UBIGINT AS h3_res8,
               h3_h3_to_string(h3_res8) AS h3_res8_hex
        FROM samp_geo
    ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)""")


def build_h3_summary(con, out, res):
    col = f"h3_res{res}"
    con.execute(f"""COPY (
        SELECT {col}::UBIGINT AS h3_cell,
               COUNT(*) AS sample_count,
               AVG(latitude) AS center_lat,
               AVG(longitude) AS center_lng,
               MODE(source) AS dominant_source,
               COUNT(DISTINCT source) AS source_count,
               {res} AS resolution
        FROM samp_geo WHERE {col} IS NOT NULL
        GROUP BY {col}
    ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)""")


def build_facet_summaries(con, out):
    # one row per (facet_type, facet_value); scheme kept NULL to match published shape
    union = " UNION ALL ".join(
        f"SELECT '{d}' AS facet_type, {d} AS facet_value FROM samp_geo WHERE {d} IS NOT NULL"
        for d in FACET_DIMS)
    con.execute(f"""COPY (
        SELECT facet_type, facet_value, NULL::INTEGER AS scheme, COUNT(*) AS count
        FROM ({union})
        GROUP BY facet_type, facet_value
    ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)""")


def build_facet_cross_filter(con, out):
    # baseline (no filter) + every single-dimension filter value, with counts for
    # all facet dims. Mirrors the cube fast-path the explorer reads (one filter_* set).
    selects = []
    # baseline: all filter_* NULL
    for fd in FACET_DIMS:
        selects.append(
            f"SELECT NULL::VARCHAR AS filter_source, NULL::VARCHAR AS filter_material, "
            f"NULL::VARCHAR AS filter_context, NULL::VARCHAR AS filter_object_type, "
            f"'{fd}' AS facet_type, {fd} AS facet_value, COUNT(*) AS count "
            f"FROM samp_geo WHERE {fd} IS NOT NULL GROUP BY {fd}")
    # single-dimension filters
    for filt in FACET_DIMS:
        for fd in FACET_DIMS:
            cols = ", ".join(
                (f"{filt} AS filter_{c}" if c == filt else f"NULL::VARCHAR AS filter_{c}")
                for c in FACET_DIMS)
            selects.append(
                f"SELECT {cols}, '{fd}' AS facet_type, {fd} AS facet_value, COUNT(*) AS count "
                f"FROM samp_geo WHERE {filt} IS NOT NULL AND {fd} IS NOT NULL GROUP BY {filt}, {fd}")
    con.execute(f"""COPY (
        SELECT filter_source, filter_material, filter_context, filter_object_type,
               facet_type, facet_value, count
        FROM ({' UNION ALL '.join(selects)})
    ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)""")


def build_wide_h3(con, wide, out):
    con.execute(f"""COPY (
        SELECT *,
          CASE WHEN geometry IS NOT NULL
               THEN h3_latlng_to_cell(ST_Y(ST_GeomFromWKB(geometry)), ST_X(ST_GeomFromWKB(geometry)), 4) END AS h3_res4,
          CASE WHEN geometry IS NOT NULL
               THEN h3_latlng_to_cell(ST_Y(ST_GeomFromWKB(geometry)), ST_X(ST_GeomFromWKB(geometry)), 6) END AS h3_res6,
          CASE WHEN geometry IS NOT NULL
               THEN h3_latlng_to_cell(ST_Y(ST_GeomFromWKB(geometry)), ST_X(ST_GeomFromWKB(geometry)), 8) END AS h3_res8
        FROM read_parquet('{wide}')
    ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)""")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wide", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--tag", default="isamples_202601")
    ap.add_argument("--only", default="", help="comma list: sample_facets_v2,samples_map_lite,wide_h3,h3_summaries,facet_summaries,facet_cross_filter")
    ap.add_argument("--skip", default="", help="comma list of the same names to skip")
    ap.add_argument("--validate-against", default="", help="dir of published files to compare schema+rowcount")
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    only = set(filter(None, args.only.split(",")))
    skip = set(filter(None, args.skip.split(",")))
    want = lambda name: (not only or name in only) and name not in skip

    t0 = time.time()
    con = duckdb.connect()
    con.execute("INSTALL h3 FROM community; LOAD h3; INSTALL spatial; LOAD spatial;")
    log("building base sample tables…", t0)
    con.execute(base_samples_sql(args.wide))
    log(f"samp={con.sql('SELECT COUNT(*) FROM samp').fetchone()[0]:,}  samp_geo={con.sql('SELECT COUNT(*) FROM samp_geo').fetchone()[0]:,}", t0)

    p = lambda name: os.path.join(args.outdir, f"{args.tag}_{name}.parquet")
    if want("sample_facets_v2"):  build_sample_facets_v2(con, p("sample_facets_v2")); log("sample_facets_v2 ✓", t0)
    if want("facet_summaries"):   build_facet_summaries(con, p("facet_summaries")); log("facet_summaries ✓", t0)
    if want("facet_cross_filter"):build_facet_cross_filter(con, p("facet_cross_filter")); log("facet_cross_filter ✓", t0)
    if want("samples_map_lite"):  build_samples_map_lite(con, p("samples_map_lite")); log("samples_map_lite ✓", t0)
    if want("h3_summaries"):
        for res in (4, 6, 8): build_h3_summary(con, p(f"h3_summary_res{res}"), res)
        log("h3_summary_res{4,6,8} ✓", t0)
    if want("wide_h3"):           build_wide_h3(con, args.wide, p("wide_h3")); log("wide_h3 ✓", t0)

    if args.validate_against:
        print("\n=== validation vs published ===")
        for name in ["sample_facets_v2","samples_map_lite","facet_summaries","facet_cross_filter",
                     "h3_summary_res4","h3_summary_res6","h3_summary_res8"]:
            built = p(name)
            pub = os.path.join(args.validate_against, f"{args.tag}_{name}.parquet")
            if not (os.path.exists(built) and os.path.exists(pub)):
                continue
            bn = con.sql(f"SELECT COUNT(*) FROM read_parquet('{built}')").fetchone()[0]
            pn = con.sql(f"SELECT COUNT(*) FROM read_parquet('{pub}')").fetchone()[0]
            bcols = [r[0] for r in con.sql(f"DESCRIBE SELECT * FROM read_parquet('{built}')").fetchall()]
            pcols = [r[0] for r in con.sql(f"DESCRIBE SELECT * FROM read_parquet('{pub}')").fetchall()]
            ok = "✓" if bcols == pcols else "✗ COLS DIFFER"
            print(f"  {name:22} built={bn:>10,}  pub={pn:>10,}  cols {ok}")
    log("done", t0)


if __name__ == "__main__":
    main()
