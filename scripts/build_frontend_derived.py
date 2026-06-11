#!/usr/bin/env python3
"""Build the explorer's frontend-derived parquet files from a wide PQG parquet.

Deterministic, reproducible builder for the 6 ad-hoc Stage-4 derived files
(see DATA_PROVENANCE.md). Every run also writes a manifest (input + output
checksums, argv, git SHA, DuckDB + extension versions) so a build is
machine-identifiable and re-verifiable.

INPUT CONTRACT (enforced/handled):
  A wide PQG parquet with entity rows incl. MaterialSampleRecord +
  IdentifiedConcept. The `geometry` column may be **WKB BLOB** or DuckDB
  **GEOMETRY** — both are handled (detected at runtime). Concept references
  live in `p__has_{material,context,sample_object}_category` row-id arrays.

OUTPUTS (into --outdir, prefixed --tag):
  - {tag}_sample_facets_v2.parquet   pid, source, material, context, object_type, label, description, place_name(VARCHAR)
  - {tag}_samples_map_lite.parquet   pid, label, source, latitude, longitude, place_name(VARCHAR[]), result_time, h3_res8(UBIGINT), h3_res8_hex
  - {tag}_h3_summary_res{4,6,8}.parquet  h3_cell(UBIGINT), sample_count(INT), center_lat, center_lng, dominant_source, source_count(INT), resolution(INT)
  - {tag}_facet_summaries.parquet    facet_type, facet_value, scheme, count
  - {tag}_facet_cross_filter.parquet filter_source/material/context/object_type, facet_type, facet_value, count
  - {tag}_wide_h3.parquet            wide + h3_res4/6/8  (large; built only on --only wide_h3)
  - {tag}_manifest.json              provenance + per-output rowcount/schema/sha256

MATERIAL SELECTION (issue #265/#271): the broad SKOS root
`.../material/1.0/material` ("Material") can appear at ANY position in the
concept array; the old `[1]` pick surfaced it as a bogus facet value. We pick
the FIRST NON-ROOT concept (by array order); samples tagged ONLY at the root
get NULL material (excluded from the facet). This is NOT leaf/most-specific
selection — see DATA_PROVENANCE.md. context/object_type use the first array
element ([1]); their root-dropping is deferred (tracked in the pipeline epic).

Determinism: row order and all DISCRETE values are deterministic (ORDER BY on
every COPY; dominant_source ties broken by source name ASC; non-unique keys are
a hard error). Floating centroids (center_lat/lng) are rounded to 6 dp and are
display-only — not part of the reproducibility guarantee; pass --threads 1 for
bit-stable centroids across machines.

Usage:
  python scripts/build_frontend_derived.py --wide WIDE.parquet --outdir OUT --tag isamples_202606
  python scripts/build_frontend_derived.py --wide WIDE.parquet --outdir OUT --tag T --only sample_facets_v2,facet_summaries
"""
import argparse, hashlib, json, os, subprocess, sys, time
import duckdb

MATERIAL_ROOT = "https://w3id.org/isample/vocabulary/material/1.0/material"
FACET_DIMS = ["source", "material", "context", "object_type"]
# the artifacts this script knows how to build (for --only/--skip validation)
ARTIFACTS = ["sample_facets_v2", "samples_map_lite", "h3_summaries",
             "facet_summaries", "facet_cross_filter", "wide_h3"]


def log(msg, t0):
    print(f"[{time.time()-t0:6.1f}s] {msg}", flush=True)


def sha256_file(path, _bufsize=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_bufsize), b""):
            h.update(chunk)
    return h.hexdigest()


def geometry_expr(con, wide):
    """Return a SQL expression yielding a GEOMETRY from `s.geometry`, whether the
    column is stored as WKB BLOB or as DuckDB GEOMETRY. Fixes the silent
    BLOB-only contract (202604 wide = BLOB; 202601/Zenodo wides = GEOMETRY)."""
    rows = con.sql(f"DESCRIBE SELECT geometry FROM read_parquet('{wide}') LIMIT 0").fetchall()
    coltype = rows[0][1].upper() if rows else "BLOB"
    if coltype == "GEOMETRY":
        return "s.geometry"
    if coltype in ("BLOB", "WKB_BLOB", "VARBINARY"):
        return "ST_GeomFromWKB(s.geometry)"
    raise SystemExit(f"FATAL: unexpected geometry column type {coltype!r} in {wide}")


def build_base_tables(con, wide, t0):
    geom = geometry_expr(con, wide)
    con.execute(f"""
    CREATE OR REPLACE TEMP TABLE ic AS
      SELECT row_id, pid AS uri FROM read_parquet('{wide}') WHERE otype='IdentifiedConcept';

    -- material: FIRST NON-ROOT concept per sample. Decorrelated (unnest+join+
    -- arg_min by array ordinality) — NOT a correlated subquery and NOT a MAP
    -- cross-join (both of which blow up the planner on 20M rows).
    CREATE OR REPLACE TEMP TABLE mat AS
      WITH ex AS (
        SELECT s.pid AS pid, u.rid AS rid, u.ord AS ord
        FROM read_parquet('{wide}') s,
             UNNEST(s.p__has_material_category) WITH ORDINALITY AS u(rid, ord)
        WHERE s.otype='MaterialSampleRecord'
      )
      SELECT ex.pid, arg_min(ic.uri, ex.ord) AS material
      FROM ex JOIN ic ON ic.row_id = ex.rid
      WHERE ic.uri <> '{MATERIAL_ROOT}'
      GROUP BY ex.pid;

    -- one row per MaterialSampleRecord; all concept resolution via JOINs (decorrelated).
    CREATE OR REPLACE TEMP TABLE samp AS
      SELECT
        s.pid,
        s.n                              AS source,
        s.label,
        s.description,
        s.place_name,                    -- VARCHAR[]
        s.result_time,
        ROUND(ST_Y({geom}), 6)           AS latitude,
        ROUND(ST_X({geom}), 6)           AS longitude,
        mat.material                     AS material,
        ctx.uri                          AS context,
        obj.uri                          AS object_type
      FROM read_parquet('{wide}') s
      LEFT JOIN mat ON mat.pid = s.pid
      LEFT JOIN ic AS ctx ON ctx.row_id = s.p__has_context_category[1]
      LEFT JOIN ic AS obj ON obj.row_id = s.p__has_sample_object_type[1]
      WHERE s.otype='MaterialSampleRecord';

    CREATE OR REPLACE TEMP TABLE samp_geo AS
      SELECT *,
             h3_latlng_to_cell(latitude, longitude, 4) AS h3_res4,
             h3_latlng_to_cell(latitude, longitude, 6) AS h3_res6,
             h3_latlng_to_cell(latitude, longitude, 8) AS h3_res8
      FROM samp WHERE latitude IS NOT NULL AND longitude IS NOT NULL;
    """)
    n_samp = con.sql("SELECT COUNT(*) FROM samp").fetchone()[0]
    n_geo = con.sql("SELECT COUNT(*) FROM samp_geo").fetchone()[0]
    n_dup = con.sql("SELECT COUNT(*) FROM (SELECT pid FROM samp_geo GROUP BY pid HAVING COUNT(*)>1)").fetchone()[0]
    n_icdup = con.sql("SELECT COUNT(*) FROM (SELECT row_id FROM ic GROUP BY row_id HAVING COUNT(*)>1)").fetchone()[0]
    log(f"samp={n_samp:,}  samp_geo={n_geo:,}  duplicate_pids={n_dup:,}  duplicate_concept_row_ids={n_icdup:,}", t0)
    if n_dup or n_icdup:
        # HARD fail (Codex): non-unique keys make the output grain wrong (inflated
        # facet counts, ambiguous joins, non-total ORDER BY pid). Abort before writing.
        raise SystemExit(
            f"FATAL: non-unique keys — duplicate_pids={n_dup}, duplicate_concept_row_ids={n_icdup}. "
            f"Output grain/joins would be wrong; refusing to write.")


def build_sample_facets_v2(con, out):
    con.execute(f"""COPY (
        SELECT pid, source, material, context, object_type, label, description,
               place_name::VARCHAR AS place_name
        FROM samp_geo ORDER BY pid
    ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)""")


def build_samples_map_lite(con, out):
    con.execute(f"""COPY (
        SELECT pid, label, source, latitude, longitude, place_name, result_time,
               h3_res8::UBIGINT AS h3_res8,
               h3_h3_to_string(h3_res8) AS h3_res8_hex
        FROM samp_geo ORDER BY pid
    ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)""")


def build_h3_summary(con, out, res):
    col = f"h3_res{res}"
    # deterministic dominant_source: max sample count, ties broken by source name ASC.
    con.execute(f"""COPY (
        WITH sc AS (
            SELECT {col} AS cell, source, COUNT(*) AS c
            FROM samp_geo WHERE {col} IS NOT NULL GROUP BY {col}, source
        ),
        dom AS (
            SELECT cell, source AS dominant_source,
                   ROW_NUMBER() OVER (PARTITION BY cell ORDER BY c DESC, source ASC) AS rn
            FROM sc
        ),
        agg AS (
            SELECT {col} AS cell, COUNT(*) AS sample_count,
                   ROUND(AVG(latitude), 6) AS center_lat,
                   ROUND(AVG(longitude), 6) AS center_lng,
                   COUNT(DISTINCT source) AS source_count
            FROM samp_geo WHERE {col} IS NOT NULL GROUP BY {col}
        )
        SELECT agg.cell::UBIGINT          AS h3_cell,
               agg.sample_count::INTEGER  AS sample_count,
               agg.center_lat, agg.center_lng,
               dom.dominant_source,
               agg.source_count::INTEGER  AS source_count,
               {res}::INTEGER             AS resolution
        FROM agg JOIN dom ON dom.cell = agg.cell AND dom.rn = 1
        ORDER BY h3_cell
    ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)""")


def build_facet_summaries(con, out):
    union = " UNION ALL ".join(
        f"SELECT '{d}' AS facet_type, {d} AS facet_value FROM samp_geo WHERE {d} IS NOT NULL"
        for d in FACET_DIMS)
    con.execute(f"""COPY (
        SELECT facet_type, facet_value, NULL::INTEGER AS scheme, COUNT(*) AS count
        FROM ({union})
        GROUP BY facet_type, facet_value
        ORDER BY facet_type, facet_value
    ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)""")


def build_facet_cross_filter(con, out):
    # baseline (all filter_* NULL) + single-dimension filters. NOTE: the shape
    # (incl. baseline rows + self-dimension rows) matches what the deployed
    # explorer reads; see SERIALIZATIONS.md for the exact contract. Determinism
    # via ORDER BY.
    selects = []
    for fd in FACET_DIMS:
        selects.append(
            f"SELECT NULL::VARCHAR AS filter_source, NULL::VARCHAR AS filter_material, "
            f"NULL::VARCHAR AS filter_context, NULL::VARCHAR AS filter_object_type, "
            f"'{fd}' AS facet_type, {fd} AS facet_value, COUNT(*) AS count "
            f"FROM samp_geo WHERE {fd} IS NOT NULL GROUP BY {fd}")
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
        ORDER BY filter_source, filter_material, filter_context, filter_object_type, facet_type, facet_value
    ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)""")


def build_wide_h3(con, wide, out):
    geom = geometry_expr(con, wide).replace("s.geometry", "geometry")
    con.execute(f"""COPY (
        SELECT *,
          CASE WHEN geometry IS NOT NULL THEN h3_latlng_to_cell(ST_Y({geom}), ST_X({geom}), 4) END AS h3_res4,
          CASE WHEN geometry IS NOT NULL THEN h3_latlng_to_cell(ST_Y({geom}), ST_X({geom}), 6) END AS h3_res6,
          CASE WHEN geometry IS NOT NULL THEN h3_latlng_to_cell(ST_Y({geom}), ST_X({geom}), 8) END AS h3_res8
        FROM read_parquet('{wide}') ORDER BY pid
    ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD)""")


def file_meta(con, path):
    n = con.sql(f"SELECT COUNT(*) FROM read_parquet('{path}')").fetchone()[0]
    schema = [(r[0], r[1]) for r in con.sql(f"DESCRIBE SELECT * FROM read_parquet('{path}')").fetchall()]
    return {"rows": n, "schema": schema, "bytes": os.path.getsize(path), "sha256": sha256_file(path)}


def git_sha():
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"],
                                       cwd=os.path.dirname(os.path.abspath(__file__)),
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wide", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--tag", required=True, help="output prefix, e.g. isamples_202606 (no stale default)")
    ap.add_argument("--only", default="", help=f"comma list of: {','.join(ARTIFACTS)}")
    ap.add_argument("--skip", default="", help="comma list of the same names to skip")
    ap.add_argument("--no-manifest", action="store_true", help="skip writing {tag}_manifest.json")
    ap.add_argument("--threads", type=int, default=0,
                    help="DuckDB thread count; set 1 for bit-stable floating centroids (slower)")
    args = ap.parse_args()

    only = set(filter(None, args.only.split(",")))
    skip = set(filter(None, args.skip.split(",")))
    bad = (only | skip) - set(ARTIFACTS)
    if bad:  # Codex #3: fail loudly on typos instead of silently building nothing
        sys.exit(f"FATAL: unknown --only/--skip name(s): {sorted(bad)}. Known: {ARTIFACTS}")
    want = lambda name: (not only or name in only) and name not in skip
    os.makedirs(args.outdir, exist_ok=True)

    t0 = time.time()
    con = duckdb.connect()
    if args.threads:
        con.execute(f"PRAGMA threads={args.threads}")
    con.execute("INSTALL h3 FROM community; LOAD h3; INSTALL spatial; LOAD spatial;")
    log("building base sample tables…", t0)
    build_base_tables(con, args.wide, t0)

    p = lambda name: os.path.join(args.outdir, f"{args.tag}_{name}.parquet")
    produced = []
    def emit(name, fn):
        if want(name):
            fn(p(name)); produced.append(p(name)); log(f"{name} ✓", t0)

    emit("sample_facets_v2", lambda o: build_sample_facets_v2(con, o))
    emit("facet_summaries", lambda o: build_facet_summaries(con, o))
    emit("facet_cross_filter", lambda o: build_facet_cross_filter(con, o))
    emit("samples_map_lite", lambda o: build_samples_map_lite(con, o))
    if want("h3_summaries"):
        for res in (4, 6, 8):
            build_h3_summary(con, p(f"h3_summary_res{res}"), res); produced.append(p(f"h3_summary_res{res}"))
        log("h3_summary_res{4,6,8} ✓", t0)
    emit("wide_h3", lambda o: build_wide_h3(con, args.wide, o))

    if not args.no_manifest:
        log("hashing inputs/outputs for manifest…", t0)
        exts = {r[0]: r[1] for r in con.sql(
            "SELECT extension_name, extension_version FROM duckdb_extensions() WHERE installed").fetchall()}
        manifest = {
            "tag": args.tag,
            "argv": sys.argv,
            "git_sha": git_sha(),
            "duckdb_version": duckdb.__version__,
            "extensions": exts,
            "input": {"path": args.wide,
                      "bytes": (os.path.getsize(args.wide) if os.path.exists(args.wide) else None),
                      "sha256": (sha256_file(args.wide) if os.path.exists(args.wide) else "remote/unhashed")},
            "outputs": {os.path.basename(f): file_meta(con, f) for f in produced},
        }
        mpath = p("manifest").replace(".parquet", ".json")
        with open(mpath, "w") as fh:
            json.dump(manifest, fh, indent=2)
        log(f"manifest → {mpath}", t0)

    log("done", t0)


if __name__ == "__main__":
    main()
