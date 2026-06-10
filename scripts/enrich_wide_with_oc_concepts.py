#!/usr/bin/env python3
"""Overlay OpenContext material/object-type concepts onto the unified wide parquet.

Issue #272 (fixes #260): the unified wide derives from the FROZEN iSamples
Central export, whose vocab mappings for OpenContext samples are stale or wrong
(e.g. a ceramic carrying [anthropogenicmetal, biogenicnonorganicmaterial, rock]).
Eric Kansa's independently-maintained OC PQG carries the corrected mappings.

POLICY (RY decision, 2026-06-10, #272): **OC wins unconditionally for OC pids.**
For every MaterialSampleRecord pid present in the OC wide, this script REPLACES
`p__has_material_category` and `p__has_sample_object_type` with the OC values —
including when OC is less specific (root-only). The frozen export's "specific"
values for OC samples are exactly the class proven untrustworthy in #260.

WHAT IT DOES (single DuckDB pass, deterministic):
  1. Extract per-pid ORDERED concept-URI lists for both dimensions from the OC
     wide (array order is preserved — the frontend builder picks the first
     non-root concept by array order).
  2. Map URIs -> target row_ids via the src wide's IdentifiedConcept rows
     (duplicate-URI concepts resolve to MIN(row_id), deterministically).
  3. Mint NEW IdentifiedConcept rows for URIs the src wide lacks (e.g.
     `otheranthropogenicmaterial` — absent from the frozen export entirely).
     New row_ids = max(src row_id) + dense rank by URI (deterministic).
     Labels/scheme metadata are carried from the OC concept rows.
  4. Write src rows with the two p__ columns replaced for overlay pids
     (all other rows and columns byte-identical), UNION the new concept rows.
  5. Emit a {out}.manifest.json (inputs' sha256, counts, argv, git SHA).

WHAT IT DOES *NOT* DO (scope, documented in #272):
  - OC samples absent from the src wide (~75K new records) are NOT ingested —
    overlay only. New-record ingestion is a follow-up.
  - `p__has_context_category` is untouched (unverified against OC; follow-up).

NORMALIZATION: an EMPTY OC array (`[]`) becomes NULL in the output — this is
deliberate and matches the wide-format convention that p__* columns are NULL
when no relationship exists (pqg issue #8). In practice all 1.11M OC
MaterialSampleRecords carry non-empty arrays for both dims.

HARD FAILURES (refuses to write):
  - duplicate pids among OC MaterialSampleRecords (overlay grain would be wrong)
  - any OC concept reference that does not resolve to an OC IdentifiedConcept row
  - duplicate row_ids among src entity rows (entity grain would be wrong)

Usage:
  python scripts/enrich_wide_with_oc_concepts.py \
      --src  isamples_202604_wide.parquet \
      --oc-wide oc_isamples_pqg_wide_2026-06-09.parquet \
      --out  isamples_202606_wide.parquet

Validate with scripts/validate_oc_concept_enrichment.py (independent re-derivation).
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

import duckdb

# the two overlay dimensions: (src/our wide column, human name)
DIMS = ["p__has_material_category", "p__has_sample_object_type"]


def sha256_file(path, _bufsize=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_bufsize), b""):
            h.update(chunk)
    return h.hexdigest()


def git_sha():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return None


def log(msg, t0):
    print(f"[{time.time()-t0:6.1f}s] {msg}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="unified wide parquet (frozen-export lineage)")
    ap.add_argument("--oc-wide", required=True, help="Eric's OC PQG wide parquet (source of truth for OC concepts)")
    ap.add_argument("--out", required=True, help="output enriched wide parquet")
    ap.add_argument("--no-manifest", action="store_true")
    args = ap.parse_args()

    for fp in (args.src, args.oc_wide):
        if not os.path.exists(fp):
            sys.exit(f"FATAL: missing input {fp}")
    if os.path.abspath(args.out) in (os.path.abspath(args.src), os.path.abspath(args.oc_wide)):
        sys.exit("FATAL: --out must not overwrite an input")

    t0 = time.time()
    con = duckdb.connect()
    SRC = f"read_parquet('{args.src}')"
    OC = f"read_parquet('{args.oc_wide}')"

    # ---- schema contract: src must carry both p__ columns; capture full column list
    src_cols = [(r[0], r[1]) for r in con.sql(f"DESCRIBE SELECT * FROM {SRC}").fetchall()]
    src_colnames = [c for c, _ in src_cols]
    for d in DIMS:
        if d not in src_colnames:
            sys.exit(f"FATAL: src wide lacks required column {d}")
    p_types = {c: t for c, t in src_cols if c in DIMS}

    # ---- grain checks (hard-fail before any writing) ----------------------
    n_dup_src_rowid = con.sql(
        f"SELECT COUNT(*) FROM (SELECT row_id FROM {SRC} GROUP BY row_id HAVING COUNT(*)>1)").fetchone()[0]
    n_dup_oc_pid = con.sql(
        f"SELECT COUNT(*) FROM (SELECT pid FROM {OC} WHERE otype='MaterialSampleRecord' "
        f"GROUP BY pid HAVING COUNT(*)>1)").fetchone()[0]
    if n_dup_src_rowid or n_dup_oc_pid:
        sys.exit(f"FATAL: non-unique keys — src duplicate row_ids={n_dup_src_rowid}, "
                 f"OC duplicate MSR pids={n_dup_oc_pid}. Refusing to write.")

    # ---- 1. OC per-pid ORDERED URI lists, both dims ------------------------
    # WITH ORDINALITY preserves OC's array order; every rid MUST resolve to an
    # OC IdentifiedConcept row (unresolved refs are a hard error, not a drop).
    con.execute(f"""
    CREATE TEMP TABLE oc_ref AS
      SELECT s.pid, 'p__has_material_category' AS dim, u.rid, u.ord
      FROM {OC} s, UNNEST(s.p__has_material_category) WITH ORDINALITY AS u(rid, ord)
      WHERE s.otype='MaterialSampleRecord'
      UNION ALL
      SELECT s.pid, 'p__has_sample_object_type' AS dim, u.rid, u.ord
      FROM {OC} s, UNNEST(s.p__has_sample_object_type) WITH ORDINALITY AS u(rid, ord)
      WHERE s.otype='MaterialSampleRecord';

    CREATE TEMP TABLE oc_concepts AS
      SELECT row_id, pid AS uri, label, scheme_name, scheme_uri
      FROM {OC} WHERE otype='IdentifiedConcept';
    """)
    n_unresolved = con.sql("""
        SELECT COUNT(*) FROM oc_ref r LEFT JOIN oc_concepts c ON c.row_id = r.rid
        WHERE c.row_id IS NULL""").fetchone()[0]
    if n_unresolved:
        sys.exit(f"FATAL: {n_unresolved} OC concept references do not resolve to an "
                 f"OC IdentifiedConcept row. OC file is internally inconsistent; refusing to write.")

    con.execute("""
    CREATE TEMP TABLE oc_uri_lists AS
      SELECT r.pid, r.dim, list(c.uri ORDER BY r.ord, c.uri) AS uris
      FROM oc_ref r JOIN oc_concepts c ON c.row_id = r.rid
      GROUP BY r.pid, r.dim;
    """)
    log("OC ordered URI lists extracted", t0)

    # ---- 2. URI -> target row_id (existing concepts; MIN(row_id) on dup URIs)
    con.execute(f"""
    CREATE TEMP TABLE src_concept_map AS
      SELECT pid AS uri, MIN(row_id) AS row_id
      FROM {SRC} WHERE otype='IdentifiedConcept' GROUP BY pid;
    """)

    # ---- 3. mint rows for missing URIs (deterministic ids: max + rank by URI)
    max_row_id = con.sql(f"SELECT COALESCE(MAX(row_id), 0) FROM {SRC}").fetchone()[0]
    con.execute(f"""
    CREATE TEMP TABLE new_concepts AS
      WITH missing AS (
        SELECT DISTINCT u.uri
        FROM (SELECT DISTINCT unnest(uris) AS uri FROM oc_uri_lists) u
        LEFT JOIN src_concept_map m ON m.uri = u.uri
        WHERE m.uri IS NULL
      ),
      meta AS (
        -- deterministic metadata per URI (OC may carry duplicate concept rows)
        SELECT uri, MIN(label) AS label, MIN(scheme_name) AS scheme_name, MIN(scheme_uri) AS scheme_uri
        FROM oc_concepts GROUP BY uri
      )
      SELECT {max_row_id} + ROW_NUMBER() OVER (ORDER BY missing.uri) AS row_id,
             missing.uri, meta.label, meta.scheme_name, meta.scheme_uri
      FROM missing JOIN meta ON meta.uri = missing.uri;

    CREATE TEMP TABLE uri_map AS
      SELECT uri, row_id FROM src_concept_map
      UNION ALL
      SELECT uri, row_id FROM new_concepts;
    """)
    n_new = con.sql("SELECT COUNT(*) FROM new_concepts").fetchone()[0]
    log(f"new IdentifiedConcept rows to mint: {n_new}", t0)

    # ---- 4. per-pid mapped row_id lists ------------------------------------
    con.execute("""
    CREATE TEMP TABLE overlay AS
      SELECT l.pid,
             MAX(CASE WHEN l.dim='p__has_material_category' THEN ids END)  AS mat_ids,
             MAX(CASE WHEN l.dim='p__has_sample_object_type' THEN ids END) AS obj_ids
      FROM (
        SELECT ol.pid, ol.dim, list(m.row_id ORDER BY u.ord, m.row_id) AS ids
        FROM oc_uri_lists ol,
             UNNEST(ol.uris) WITH ORDINALITY AS u(uri, ord)
        JOIN uri_map m ON m.uri = u.uri
        GROUP BY ol.pid, ol.dim
      ) l
      GROUP BY l.pid;
    """)
    n_overlay = con.sql("SELECT COUNT(*) FROM overlay").fetchone()[0]
    n_match = con.sql(f"""
        SELECT COUNT(*) FROM overlay o
        JOIN {SRC} s ON s.pid = o.pid AND s.otype='MaterialSampleRecord'""").fetchone()[0]
    log(f"overlay pids={n_overlay:,}  matched in src={n_match:,}  "
        f"unmatched (new OC records, NOT ingested)={n_overlay-n_match:,}", t0)

    # ---- 5. write: replaced src rows + minted concept rows ------------------
    # OC WINS UNCONDITIONALLY for matched MaterialSampleRecord pids — the two
    # p__ columns become the OC-derived lists (NOT COALESCE).
    new_concept_select = ", ".join(
        {
            "row_id": f"n.row_id::{dict(src_cols)['row_id']} AS row_id",
            "pid": "n.uri AS pid",
            "otype": "'IdentifiedConcept' AS otype",
            "label": "n.label AS label",
            "scheme_name": "n.scheme_name AS scheme_name",
            "scheme_uri": "n.scheme_uri AS scheme_uri",
        }.get(c, f"NULL::{t} AS {c}")
        for c, t in src_cols
    )
    replace_exprs = ", ".join(
        f"(CASE WHEN ov.pid IS NOT NULL AND s.otype='MaterialSampleRecord' "
        f"THEN ov.{alias}::{p_types[col]} ELSE s.{col} END) AS {col}"
        for col, alias in [("p__has_material_category", "mat_ids"),
                           ("p__has_sample_object_type", "obj_ids")])
    con.execute(f"""
    COPY (
      SELECT s.* REPLACE ({replace_exprs})
      FROM {SRC} s LEFT JOIN overlay ov ON ov.pid = s.pid
      UNION ALL BY NAME
      SELECT {new_concept_select} FROM new_concepts n
      ORDER BY row_id
    ) TO '{args.out}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    log(f"wrote {args.out}", t0)

    # ---- post-write accounting ----------------------------------------------
    OUT = f"read_parquet('{args.out}')"
    n_src, n_out = (con.sql(f"SELECT COUNT(*) FROM {SRC}").fetchone()[0],
                    con.sql(f"SELECT COUNT(*) FROM {OUT}").fetchone()[0])
    if n_out != n_src + n_new:
        sys.exit(f"FATAL: row count {n_out} != src {n_src} + new concepts {n_new}")
    changed = con.sql(f"""
        SELECT
          COUNT(*) FILTER (WHERE s.p__has_material_category IS DISTINCT FROM o.p__has_material_category),
          COUNT(*) FILTER (WHERE s.p__has_sample_object_type IS DISTINCT FROM o.p__has_sample_object_type)
        FROM {SRC} s JOIN {OUT} o ON o.row_id = s.row_id
        WHERE s.otype='MaterialSampleRecord'""").fetchone()
    log(f"rows={n_out:,} (src {n_src:,} + {n_new} minted concepts)  "
        f"material changed={changed[0]:,}  object_type changed={changed[1]:,}", t0)

    if not args.no_manifest:
        manifest = {
            "script": os.path.basename(__file__),
            "argv": sys.argv,
            "git_sha": git_sha(),
            "duckdb_version": duckdb.__version__,
            "policy": "OC wins unconditionally for OC pids (#272, RY 2026-06-10)",
            "dims": DIMS,
            "inputs": {
                "src": {"path": args.src, "bytes": os.path.getsize(args.src),
                        "sha256": sha256_file(args.src)},
                "oc_wide": {"path": args.oc_wide, "bytes": os.path.getsize(args.oc_wide),
                            "sha256": sha256_file(args.oc_wide)},
            },
            "counts": {
                "src_rows": n_src, "out_rows": n_out,
                "overlay_pids": n_overlay, "overlay_matched": n_match,
                "overlay_unmatched_new_oc_records": n_overlay - n_match,
                "minted_concepts": n_new,
                "material_changed": changed[0], "object_type_changed": changed[1],
            },
            "output": {"path": args.out, "bytes": os.path.getsize(args.out),
                       "sha256": sha256_file(args.out)},
        }
        mpath = args.out + ".manifest.json"
        with open(mpath, "w") as fh:
            json.dump(manifest, fh, indent=2)
        log(f"manifest → {mpath}", t0)

    log("done", t0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
