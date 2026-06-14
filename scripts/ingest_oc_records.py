#!/usr/bin/env python3
"""TRUE SYNC: ingest new OpenContext records + remove stale OC records.

Issue #272 Phase 2 (follow-up to PR #275 overlay phase):
  The overlay phase (Phase 1) fixed concept mappings for ~1.04M existing OC pids.
  This script performs a TRUE SYNC against Eric's 2026-06-09 OC PQG wide:
    ADD  67,187 new pids (in Eric's wide but not in src)
    REMOVE 21,227 stale pids (in src but not in Eric's wide — Murlo project
           mass-updated PIDs; old PIDs would duplicate the same physical samples)
  + remove orphaned subgraph entities for the removed pids.

Decision D3 (2026-06-12, RY): REMOVE the stale pids. Rationale: OpenContext
mass-updated Murlo project PIDs; keeping old pids would duplicate the same
physical samples under two identifiers. This is a TRUE SYNC.

WHAT IT DOES (single DuckDB session, deterministic):
  1. Identify stale pids (src has, Eric doesn't) → rows to remove
  2. Identify orphan subgraph entities (SE / Geo / Site) only referenced by
     removed MSRs — safe to remove; agents are shared so NOT removed.
  3. Identify new pids (Eric has, src doesn't) → rows to add
  4. Extract full entity subgraph for new pids:
       MaterialSampleRecord + SamplingEvent + GeospatialCoordLocation +
       SamplingSite + Agent + (linked IdentifiedConcepts already in src)
  5. Assign new row_ids: dense rank starting at max(src.row_id)+1,
     ordered deterministically by (otype, pid).
  6. Build a mapping table: Eric's row_id → our new row_id.
  7. Remap all p__ arrays on new rows from Eric's id space to our id space.
     Concept refs in p__has_* arrays resolved via URI lookup against src's
     IdentifiedConcept rows (same pattern as enrich_wide_with_oc_concepts.py).
  8. Denormalize geometry/lat/lon from GeoCoordLoc onto new MSR rows
     (builder reads geometry from MSR rows, not from GeoCoordLoc).
  9. Set n='OPENCONTEXT' on new MSR rows (Eric's wide has NULL).
 10. Mint new IdentifiedConcept rows for any concept URIs in new MSRs but
     absent from src wide (expected: sampledfeature/1.0/earthsurface).
 11. Hard-fail checks before writing (see HARD FAILURES below).
 12. Write: (src - removed - orphans) UNION ALL new_entities → output wide.
 13. Emit a {out}.manifest.json.

WHAT IT DOES NOT DO (scope):
  - Does not re-run the Phase 1 concept overlay (already in src wide).
  - Does not populate p__curation / p__related_resource (OC doesn't have them).

HARD FAILURES (refuses to write):
  - duplicate pids among new MSRs (new pid set must be truly new)
  - any new pid already exists in src wide (ingestion grain wrong)
  - duplicate row_ids in proposed new id set vs src wide
  - any p__ reference in a new row that cannot be resolved to a row_id in output
  - any new MSR with n != 'OPENCONTEXT' in the written output
  - row count mismatch: output != (src - removed) + new_entities + minted_concepts
  - duplicate pids anywhere in output (union would create them if logic is wrong)
  - any removed pid still present in output

Usage:
  python scripts/ingest_oc_records.py \\
      --src  isamples_202606_wide.parquet \\
      --oc-wide oc_isamples_pqg_wide_2026-06-09.parquet \\
      --out  isamples_202608_wide.parquet

  # Dry-run (skips writing, just runs analysis + trust checks):
  python scripts/ingest_oc_records.py --src ... --oc-wide ... --out ... --dry-run

Notes:
  - DuckDB pinned to 1.4.4 (scripts/requirements.txt). h3 + spatial extensions
    installed at runtime (needed for geometry handling).
  - Use the 202606 wide as --src (not 202604). Phase 1 (PR #275) minted the
    otheranthropogenicmaterial concept in 202606; using 202604 would require
    minting it again and risks id collision with Phase 1.
  - The --src wide's row_id column must be BIGINT (our convention). Eric's wide
    uses INTEGER — new rows cast to BIGINT automatically.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time

import duckdb

# Dimensions where concept references live on MSR rows
CONCEPT_DIMS = [
    "p__has_material_category",
    "p__has_sample_object_type",
    "p__has_context_category",
]

# Columns present in our wide but absent from Eric's wide (will be NULL in new rows)
OUR_ONLY_COLS = ["p__curation", "p__related_resource"]

# The source attribution for all OC records in the unified wide
OC_SOURCE = "OPENCONTEXT"


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
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return None


def log(msg, t0):
    print(f"[{time.time()-t0:6.1f}s] {msg}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True,
                    help="Source unified wide parquet (should be isamples_202606_wide.parquet "
                         "so Phase-1 concept minting is already present)")
    ap.add_argument("--oc-wide", required=True,
                    help="Eric's OC PQG wide parquet (oc_isamples_pqg_wide_2026-06-09.parquet)")
    ap.add_argument("--out", required=True,
                    help="Output wide parquet (e.g. isamples_202608_wide.parquet)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Run analysis and trust checks, do not write output")
    ap.add_argument("--no-manifest", action="store_true")
    args = ap.parse_args()

    for fp in (args.src, args.oc_wide):
        if not os.path.exists(fp):
            sys.exit(f"FATAL: missing input {fp}")
    if not args.dry_run:
        if os.path.abspath(args.out) in (os.path.abspath(args.src),
                                          os.path.abspath(args.oc_wide)):
            sys.exit("FATAL: --out must not overwrite an input")
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    t0 = time.time()
    con = duckdb.connect()
    con.execute("INSTALL h3 FROM community; LOAD h3; INSTALL spatial; LOAD spatial;")

    SRC = f"read_parquet('{args.src}')"
    OC = f"read_parquet('{args.oc_wide}')"

    # ---- schema contract checks -------------------------------------------
    src_cols_raw = con.sql(f"DESCRIBE SELECT * FROM {SRC}").fetchall()
    src_cols = [(r[0], r[1]) for r in src_cols_raw]
    src_colnames = [c for c, _ in src_cols]

    oc_cols_raw = con.sql(f"DESCRIBE SELECT * FROM {OC}").fetchall()
    oc_colnames = [r[0] for r in oc_cols_raw]

    # Verify concept dim columns exist in both
    for d in CONCEPT_DIMS:
        if d not in src_colnames:
            sys.exit(f"FATAL: src wide lacks required column {d}")
        if d not in oc_colnames:
            sys.exit(f"FATAL: oc-wide lacks required column {d}")

    # Verify p__produced_by exists (coord path)
    for col in ("p__produced_by",):
        if col not in oc_colnames:
            sys.exit(f"FATAL: oc-wide lacks required column {col}")

    log("schema checks passed", t0)

    # ---- grain checks (hard-fail before any writing) -----------------------
    n_dup_src_rowid = con.sql(
        f"SELECT COUNT(*) FROM (SELECT row_id FROM {SRC} GROUP BY row_id HAVING COUNT(*)>1)"
    ).fetchone()[0]
    n_dup_oc_pid_msr = con.sql(
        f"SELECT COUNT(*) FROM (SELECT pid FROM {OC} WHERE otype='MaterialSampleRecord' "
        f"GROUP BY pid HAVING COUNT(*)>1)"
    ).fetchone()[0]
    if n_dup_src_rowid or n_dup_oc_pid_msr:
        sys.exit(
            f"FATAL: non-unique keys — src duplicate row_ids={n_dup_src_rowid}, "
            f"OC duplicate MSR pids={n_dup_oc_pid_msr}. Refusing to proceed."
        )

    # ---- Phase D3: identify stale pids to remove ---------------------------
    con.execute(f"""
    CREATE TEMP TABLE removed_pids AS
      SELECT pid
      FROM {SRC} WHERE otype='MaterialSampleRecord' AND n='{OC_SOURCE}'
      EXCEPT
      SELECT pid
      FROM {OC} WHERE otype='MaterialSampleRecord';
    """)
    n_removed_pids = con.sql("SELECT COUNT(*) FROM removed_pids").fetchone()[0]
    log(f"stale pids to remove: {n_removed_pids:,}", t0)

    # ---- Phase D3 orphan analysis: FIXPOINT general orphan removal ----------
    # TRUE GENERAL FORMULATION (no path enumeration):
    #
    # A candidate row (any non-MSR entity reachable from the 21K removed MSRs'
    # subgraph) is removed iff its row_id is NOT referenced by ANY surviving row
    # through ANY p__* array column.  We iterate to fixpoint because an orphan
    # candidate may itself be the sole reference-holder of another candidate
    # (e.g. an orphan SamplingSite → orphan Geo).
    #
    # Algorithm:
    #   remove_set := row_ids of the stale MSRs
    #   repeat until remove_set stops growing:
    #     survivor_refs := DISTINCT union of every p__* array column, UNNESTed,
    #                      over all rows WHERE row_id NOT IN remove_set
    #     candidates    := rows in the removed-MSR subgraph not already in remove_set
    #     new_orphans   := candidates WHERE row_id NOT IN survivor_refs
    #     remove_set    := remove_set UNION new_orphans
    #
    # The graph is shallow (~3 hops: MSR→SE→Geo/Site→Geo) so fixpoint is reached
    # in ≤4 passes.  We enumerate the p__* columns from the schema — no guesswork.

    # Collect all p__* columns that carry BIGINT[] or INTEGER[] row_id references.
    p_ref_cols = [
        col for col, typ in src_cols
        if col.startswith("p__")
        and any(t in typ.upper() for t in ("BIGINT", "INTEGER"))
    ]
    log(f"fixpoint orphan: p__* ref cols = {p_ref_cols}", t0)

    # Build the subgraph of candidates: all non-MSR rows reachable (transitively)
    # from the removed MSRs through their p__* arrays.
    # We do this in one pass: any row whose row_id appears in ANY p__* array of
    # the removed MSRs (or their descendants) is a candidate.
    # We use a wide-first BFS: first pass collects direct refs from removed MSRs,
    # subsequent passes follow refs from newly discovered candidates.
    # For the iSamples graph (depth ≤3) three passes always reach fixpoint.
    con.execute(f"""
    -- Seed remove_set with the stale MSR row_ids
    CREATE TEMP TABLE remove_set AS
      SELECT s.row_id
      FROM {SRC} s
      WHERE s.otype='MaterialSampleRecord' AND s.n='{OC_SOURCE}'
        AND s.pid IN (SELECT pid FROM removed_pids);
    """)

    pass_num = 0
    while True:
        pass_num += 1

        # -- Step 1: compute survivor_refs: all row_ids referenced by surviving rows
        # (rows NOT in remove_set) through ANY p__* reference column.
        # Build a UNION ALL of unnest() over each p__* col, filter to surviving rows.
        survivor_union = "\n    UNION ALL\n    ".join(
            f"SELECT unnest(w.{col}) AS ref_id"
            f" FROM {SRC} w"
            f" WHERE w.{col} IS NOT NULL AND len(w.{col}) > 0"
            f"   AND w.row_id NOT IN (SELECT row_id FROM remove_set)"
            for col in p_ref_cols
        )
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE survivor_refs_cur AS
            SELECT DISTINCT ref_id
            FROM ({survivor_union}) t
            WHERE ref_id IS NOT NULL
        """)

        # -- Step 2: compute the candidate subgraph reachable from remove_set rows.
        # Any non-MSR row whose row_id appears in any p__* array of any row in
        # remove_set is a candidate for orphan-deletion.
        candidate_union = "\n    UNION ALL\n    ".join(
            f"SELECT unnest(r2.{col}) AS row_id"
            f" FROM {SRC} r2"
            f" WHERE r2.row_id IN (SELECT row_id FROM remove_set)"
            f"   AND r2.{col} IS NOT NULL"
            for col in p_ref_cols
        )
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE candidates_cur AS
            SELECT DISTINCT row_id
            FROM ({candidate_union}) t
            WHERE row_id IS NOT NULL
        """)

        # -- Step 3: new orphans = candidates NOT in survivor_refs AND NOT already removed
        # AND NOT an MSR (we only auto-remove non-MSR entities; MSRs handled explicitly above)
        # AND NOT an IdentifiedConcept (vocabulary concept rows are shared across all sources
        # and must never be deleted just because one MSR is removed).
        new_orphan_ids = con.execute(f"""
            SELECT s.row_id
            FROM {SRC} s
            JOIN candidates_cur c ON c.row_id = s.row_id
            WHERE s.otype != 'MaterialSampleRecord'
              AND s.otype != 'IdentifiedConcept'
              AND s.row_id NOT IN (SELECT row_id FROM remove_set)
              AND s.row_id NOT IN (SELECT ref_id FROM survivor_refs_cur)
        """).fetchall()

        n_new = len(new_orphan_ids)
        log(f"fixpoint pass {pass_num}: {n_new} new orphans", t0)
        if n_new == 0:
            con.execute("DROP TABLE IF EXISTS survivor_refs_cur")
            con.execute("DROP TABLE IF EXISTS candidates_cur")
            break

        # Insert the new orphans into remove_set
        new_ids_csv = ",".join(str(r[0]) for r in new_orphan_ids)
        con.execute(f"""
            INSERT INTO remove_set
            SELECT DISTINCT row_id FROM {SRC}
            WHERE row_id IN ({new_ids_csv})
              AND row_id NOT IN (SELECT row_id FROM remove_set)
        """)

    n_rows_to_remove = con.sql("SELECT COUNT(*) FROM remove_set").fetchone()[0]
    log(f"fixpoint done in {pass_num} passes: rows_to_remove={n_rows_to_remove:,}", t0)

    # Sanity: verify no non-OC MSR rows crept into remove_set
    n_non_oc_in_remove = con.sql(f"""
        SELECT COUNT(*) FROM remove_set rs
        JOIN {SRC} s ON s.row_id = rs.row_id
        WHERE s.otype='MaterialSampleRecord' AND s.n != '{OC_SOURCE}'
    """).fetchone()[0]
    if n_non_oc_in_remove:
        sys.exit(f"FATAL: fixpoint orphan put {n_non_oc_in_remove} non-OC MSR rows in remove_set")

    # For logging: count by otype
    otype_counts = con.sql(f"""
        SELECT s.otype, COUNT(*) AS n
        FROM remove_set rs JOIN {SRC} s ON s.row_id=rs.row_id
        GROUP BY s.otype ORDER BY s.otype
    """).fetchall()
    orphan_counts = {ot: n for ot, n in otype_counts}
    n_removed_msrs_actual = orphan_counts.get("MaterialSampleRecord", 0)
    if n_removed_msrs_actual != n_removed_pids:
        sys.exit(f"FATAL: remove_set has {n_removed_msrs_actual} MSR rows but expected {n_removed_pids}")
    log(f"orphan subgraph by otype: {orphan_counts}", t0)

    # Alias rows_to_remove for compatibility with downstream SQL
    con.execute("CREATE TEMP TABLE rows_to_remove AS SELECT row_id FROM remove_set")
    total_orphan_rows = n_rows_to_remove

    # ---- Phase A: identify new pids ----------------------------------------
    con.execute(f"""
    CREATE TEMP TABLE new_pids AS
      SELECT pid
      FROM {OC} WHERE otype='MaterialSampleRecord'
      EXCEPT
      SELECT pid
      FROM {SRC} WHERE otype='MaterialSampleRecord' AND n='{OC_SOURCE}';
    """)
    n_new_pids = con.sql("SELECT COUNT(*) FROM new_pids").fetchone()[0]
    log(f"new pids: {n_new_pids:,}", t0)
    if n_new_pids == 0:
        sys.exit("INFO: no new pids to ingest. Output would be identical to src minus removals. Exiting.")

    # Check none of the new pids sneak in as non-OPENCONTEXT records in src
    n_pid_collision = con.sql(f"""
        SELECT COUNT(*) FROM new_pids np
        JOIN {SRC} s ON s.pid = np.pid AND s.otype='MaterialSampleRecord'
    """).fetchone()[0]
    if n_pid_collision:
        sys.exit(f"FATAL: {n_pid_collision} 'new' pids already exist in src wide (with different n). "
                 f"This would create duplicate pids in output.")

    # ---- Phase B: extract new MSR rows + full entity subgraph ---------------
    log("extracting entity subgraph for new pids...", t0)
    con.execute(f"""
    -- New MSR rows from Eric's wide
    CREATE TEMP TABLE new_msr_eric AS
      SELECT e.*
      FROM {OC} e
      WHERE e.otype='MaterialSampleRecord' AND e.pid IN (SELECT pid FROM new_pids);

    -- Linked SamplingEvent row_ids
    CREATE TEMP TABLE se_ids AS
      SELECT DISTINCT u.se_id AS eric_row_id
      FROM new_msr_eric, UNNEST(p__produced_by) AS u(se_id);

    -- SamplingEvent rows
    CREATE TEMP TABLE new_se_eric AS
      SELECT e.* FROM {OC} e
      WHERE e.otype='SamplingEvent' AND e.row_id IN (SELECT eric_row_id FROM se_ids);

    -- GeospatialCoordLocation ids from SE (p__sample_location)
    CREATE TEMP TABLE geo_from_se AS
      SELECT DISTINCT u.geo_id AS eric_row_id
      FROM new_se_eric, UNNEST(p__sample_location) AS u(geo_id);

    -- SamplingSite ids from SE (p__sampling_site)
    CREATE TEMP TABLE site_ids AS
      SELECT DISTINCT u.site_id AS eric_row_id
      FROM new_se_eric, UNNEST(p__sampling_site) AS u(site_id);

    -- SamplingSite rows
    CREATE TEMP TABLE new_site_eric AS
      SELECT e.* FROM {OC} e
      WHERE e.otype='SamplingSite' AND e.row_id IN (SELECT eric_row_id FROM site_ids);

    -- GeospatialCoordLocation ids from SamplingSite (p__site_location)
    CREATE TEMP TABLE geo_from_site AS
      SELECT DISTINCT u.loc_id AS eric_row_id
      FROM new_site_eric, UNNEST(p__site_location) AS u(loc_id);

    -- All unique GeoCoordLoc ids (union of SE-linked and site-linked)
    CREATE TEMP TABLE all_geo_ids AS
      SELECT eric_row_id FROM geo_from_se
      UNION
      SELECT eric_row_id FROM geo_from_site;

    -- GeoCoordLoc rows
    CREATE TEMP TABLE new_geo_eric AS
      SELECT e.* FROM {OC} e
      WHERE e.otype='GeospatialCoordLocation' AND e.row_id IN (SELECT eric_row_id FROM all_geo_ids);

    -- Agent ids from MSR (p__registrant AND p__responsibility — both columns ref Agents)
    CREATE TEMP TABLE agent_ids AS
      SELECT DISTINCT u.agent_id AS eric_row_id
      FROM new_msr_eric, UNNEST(p__registrant) AS u(agent_id)
      UNION
      SELECT DISTINCT u.agent_id AS eric_row_id
      FROM new_msr_eric, UNNEST(p__responsibility) AS u(agent_id);

    -- Agent rows
    CREATE TEMP TABLE new_agent_eric AS
      SELECT e.* FROM {OC} e
      WHERE e.otype='Agent' AND e.row_id IN (SELECT eric_row_id FROM agent_ids);
    """)

    counts = {
        "new_msr": con.sql("SELECT COUNT(*) FROM new_msr_eric").fetchone()[0],
        "new_se": con.sql("SELECT COUNT(*) FROM new_se_eric").fetchone()[0],
        "new_geo": con.sql("SELECT COUNT(*) FROM new_geo_eric").fetchone()[0],
        "new_site": con.sql("SELECT COUNT(*) FROM new_site_eric").fetchone()[0],
        "new_agent": con.sql("SELECT COUNT(*) FROM new_agent_eric").fetchone()[0],
    }
    log(f"subgraph: msr={counts['new_msr']:,} se={counts['new_se']:,} geo={counts['new_geo']:,} "
        f"site={counts['new_site']:,} agent={counts['new_agent']:,}", t0)

    # ---- Phase C: assign new row_ids ----------------------------------------
    max_src_row_id = con.sql(f"SELECT COALESCE(MAX(row_id), 0) FROM {SRC}").fetchone()[0]
    log(f"src max_row_id={max_src_row_id:,}", t0)

    # All new entities in one table, ordered deterministically by (otype, pid)
    # for stable dense-rank assignment
    con.execute(f"""
    CREATE TEMP TABLE all_new_entities AS
      SELECT row_id AS eric_row_id, pid, otype FROM new_msr_eric
      UNION ALL
      SELECT row_id, pid, otype FROM new_se_eric
      UNION ALL
      SELECT row_id, pid, otype FROM new_geo_eric
      UNION ALL
      SELECT row_id, pid, otype FROM new_site_eric
      UNION ALL
      SELECT row_id, pid, otype FROM new_agent_eric;

    CREATE TEMP TABLE eric_id_map AS
      SELECT eric_row_id,
             {max_src_row_id} + DENSE_RANK() OVER (ORDER BY otype, pid) AS our_row_id
      FROM all_new_entities;
    """)

    n_id_map = con.sql("SELECT COUNT(*) FROM eric_id_map").fetchone()[0]
    new_max = con.sql("SELECT MAX(our_row_id) FROM eric_id_map").fetchone()[0]
    # Verify no collision with src
    n_collision = con.sql(f"""
        SELECT COUNT(*) FROM eric_id_map m
        WHERE m.our_row_id IN (SELECT row_id FROM {SRC})
    """).fetchone()[0]
    if n_collision:
        sys.exit(f"FATAL: {n_collision} proposed new row_ids collide with existing src row_ids")
    # FIX 2: verify our_row_id uniqueness within eric_id_map.
    # DENSE_RANK() over (otype, pid) is unique when all (otype, pid) pairs are distinct.
    # If a duplicate (otype, pid) pair sneaked through, two eric_row_ids would share
    # the same our_row_id — silently producing colliding row_ids in the output.
    n_dup_our_row_id = con.sql("""
        SELECT COUNT(*) FROM (
            SELECT our_row_id FROM eric_id_map
            GROUP BY our_row_id HAVING COUNT(*) > 1
        )
    """).fetchone()[0]
    if n_dup_our_row_id:
        dup_examples = con.sql("""
            SELECT our_row_id, COUNT(*) AS cnt FROM eric_id_map
            GROUP BY our_row_id HAVING COUNT(*) > 1 ORDER BY cnt DESC LIMIT 5
        """).fetchall()
        sys.exit(
            f"FATAL: {n_dup_our_row_id} duplicate our_row_id values in id_map "
            f"(duplicate (otype,pid) pairs in new entity set). Examples: {dup_examples}"
        )
    log(f"id_map: {n_id_map:,} entries, new row_id range {max_src_row_id+1} to {new_max:,}, "
        f"collisions={n_collision}, dup_our_row_ids={n_dup_our_row_id}", t0)

    # ---- Phase D: concept resolution for p__has_* dims ---------------------
    # OC concept row_ids (Eric's space) -> URI -> our row_id
    # Uses same approach as enrich_wide_with_oc_concepts.py
    con.execute(f"""
    CREATE TEMP TABLE oc_concept_rows AS
      SELECT row_id AS eric_row_id, pid AS uri
      FROM {OC} WHERE otype='IdentifiedConcept';

    CREATE TEMP TABLE src_concept_map AS
      SELECT pid AS uri, MIN(row_id) AS our_row_id
      FROM {SRC} WHERE otype='IdentifiedConcept' GROUP BY pid;
    """)

    # Find concepts referenced by new MSRs that are missing from src.
    # Includes p__keywords so keyword IdentifiedConcept rows are minted if absent.
    con.execute(f"""
    CREATE TEMP TABLE new_concept_refs AS
      SELECT DISTINCT u.cid AS eric_cid
      FROM new_msr_eric, UNNEST(p__has_material_category) AS u(cid)
      UNION
      SELECT DISTINCT u.cid FROM new_msr_eric, UNNEST(p__has_sample_object_type) AS u(cid)
      UNION
      SELECT DISTINCT u.cid FROM new_msr_eric, UNNEST(p__has_context_category) AS u(cid)
      UNION
      SELECT DISTINCT u.cid FROM new_msr_eric, UNNEST(p__keywords) AS u(cid);

    CREATE TEMP TABLE new_concept_uris AS
      SELECT DISTINCT c.uri
      FROM new_concept_refs r
      JOIN oc_concept_rows c ON c.eric_row_id = r.eric_cid;
    """)

    n_unresolved_uris = con.sql("""
        SELECT COUNT(*) FROM new_concept_uris u
        LEFT JOIN src_concept_map m ON m.uri = u.uri
        WHERE m.our_row_id IS NULL
    """).fetchone()[0]

    if n_unresolved_uris:
        # These need to be minted — expected: only earthsurface when base is 202606.
        missing = con.sql("""
            SELECT u.uri FROM new_concept_uris u
            LEFT JOIN src_concept_map m ON m.uri = u.uri
            WHERE m.our_row_id IS NULL
            ORDER BY u.uri
        """).fetchall()
        log(f"minting {n_unresolved_uris} new IdentifiedConcept rows: {[r[0] for r in missing]}", t0)
    else:
        log("all concept URIs already in src", t0)

    # Mint new concept rows
    max_src_row_id_with_map = con.sql("SELECT MAX(our_row_id) FROM eric_id_map").fetchone()[0]
    con.execute(f"""
    CREATE TEMP TABLE new_concepts_to_mint AS
      WITH missing_uris AS (
        SELECT u.uri FROM new_concept_uris u
        LEFT JOIN src_concept_map m ON m.uri = u.uri
        WHERE m.our_row_id IS NULL
      ),
      meta AS (
        SELECT c.uri, MIN(c2.label) AS label, MIN(c2.scheme_name) AS scheme_name,
               MIN(c2.scheme_uri) AS scheme_uri
        FROM missing_uris c
        JOIN (SELECT pid AS uri, label, scheme_name, scheme_uri FROM {OC}
              WHERE otype='IdentifiedConcept') c2 ON c2.uri = c.uri
        GROUP BY c.uri
      )
      SELECT {max_src_row_id_with_map} + DENSE_RANK() OVER (ORDER BY m.uri) AS our_row_id,
             m.uri, m.label, m.scheme_name, m.scheme_uri
      FROM meta m;

    -- Complete concept lookup: src existing + newly minted
    CREATE TEMP TABLE concept_id_lookup AS
      SELECT uri, our_row_id FROM src_concept_map
      UNION ALL
      SELECT uri, our_row_id FROM new_concepts_to_mint;
    """)

    n_minted = con.sql("SELECT COUNT(*) FROM new_concepts_to_mint").fetchone()[0]
    log(f"minted_concepts={n_minted}", t0)

    # ---- Phase E: build coord table for new MSRs ----------------------------
    # Eric's wide stores geometry as DuckDB GEOMETRY type (spatial extension auto-decodes).
    # Our wide stores geometry as BLOB (WKB bytes). Convert with ST_AsWKB() so the
    # UNION ALL with src rows (BLOB) does not fail with BLOB->GEOMETRY cast error.
    con.execute("""
    CREATE TEMP TABLE new_msr_coords AS
      WITH msr_se AS (
        SELECT m.pid,
               se.row_id AS se_eric_row_id,
               se.p__sample_location
        FROM new_msr_eric m,
             UNNEST(m.p__produced_by) AS u(se_rid)
        JOIN new_se_eric se ON se.row_id = u.se_rid
      )
      SELECT ms.pid,
             CASE WHEN geo.geometry IS NOT NULL
                  THEN ST_AsWKB(geo.geometry)::BLOB
                  ELSE NULL END AS geometry,
             geo.latitude,
             geo.longitude
      FROM msr_se ms,
           UNNEST(ms.p__sample_location) AS u(geo_rid)
      JOIN new_geo_eric geo ON geo.row_id = u.geo_rid
      WHERE geo.latitude IS NOT NULL;
    """)
    n_coords = con.sql("SELECT COUNT(*) FROM new_msr_coords").fetchone()[0]
    n_dup_coords = con.sql(
        "SELECT COUNT(*) FROM (SELECT pid FROM new_msr_coords GROUP BY pid HAVING COUNT(*)>1)"
    ).fetchone()[0]
    log(f"coords: {n_coords:,} pids with coords, {n_dup_coords} duplicate-coord pids", t0)
    if n_dup_coords:
        sys.exit(f"FATAL: {n_dup_coords} MSR pids have multiple coord rows in the graph path")

    # ---- Phase F: remap p__ arrays for new entities -------------------------
    # Build remapped MSR rows (concept p__ via URI lookup; structural p__ via eric_id_map)
    # Using UNNEST WITH ORDINALITY + JOIN + list() aggregation (decorrelated — no correlated subqueries)
    log("remapping p__ arrays for new MSR rows...", t0)

    con.execute("""
    -- Pre-aggregate remapped structural arrays for new MSRs
    -- p__produced_by (SamplingEvent references)
    CREATE TEMP TABLE remap_msr_pb AS
      SELECT m.pid,
             list(idm.our_row_id::BIGINT ORDER BY u.ord) AS remapped
      FROM new_msr_eric m,
           UNNEST(m.p__produced_by) WITH ORDINALITY AS u(eric_rid, ord)
      JOIN eric_id_map idm ON idm.eric_row_id = u.eric_rid
      GROUP BY m.pid;

    -- p__has_material_category (concept refs via URI lookup)
    CREATE TEMP TABLE remap_msr_mat AS
      SELECT m.pid,
             list(cl.our_row_id::BIGINT ORDER BY u.ord) AS remapped
      FROM new_msr_eric m,
           UNNEST(m.p__has_material_category) WITH ORDINALITY AS u(eric_rid, ord)
      JOIN oc_concept_rows ocr ON ocr.eric_row_id = u.eric_rid
      JOIN concept_id_lookup cl ON cl.uri = ocr.uri
      GROUP BY m.pid;

    -- p__has_sample_object_type (concept refs)
    CREATE TEMP TABLE remap_msr_obj AS
      SELECT m.pid,
             list(cl.our_row_id::BIGINT ORDER BY u.ord) AS remapped
      FROM new_msr_eric m,
           UNNEST(m.p__has_sample_object_type) WITH ORDINALITY AS u(eric_rid, ord)
      JOIN oc_concept_rows ocr ON ocr.eric_row_id = u.eric_rid
      JOIN concept_id_lookup cl ON cl.uri = ocr.uri
      GROUP BY m.pid;

    -- p__has_context_category (concept refs)
    CREATE TEMP TABLE remap_msr_ctx AS
      SELECT m.pid,
             list(cl.our_row_id::BIGINT ORDER BY u.ord) AS remapped
      FROM new_msr_eric m,
           UNNEST(m.p__has_context_category) WITH ORDINALITY AS u(eric_rid, ord)
      JOIN oc_concept_rows ocr ON ocr.eric_row_id = u.eric_rid
      JOIN concept_id_lookup cl ON cl.uri = ocr.uri
      GROUP BY m.pid;

    -- p__registrant (Agent refs)
    CREATE TEMP TABLE remap_msr_reg AS
      SELECT m.pid,
             list(idm.our_row_id::BIGINT ORDER BY u.ord) AS remapped
      FROM new_msr_eric m,
           UNNEST(m.p__registrant) WITH ORDINALITY AS u(eric_rid, ord)
      JOIN eric_id_map idm ON idm.eric_row_id = u.eric_rid
      GROUP BY m.pid;

    -- p__keywords (concept refs via URI lookup; same pattern as p__has_material_category)
    CREATE TEMP TABLE remap_msr_kw AS
      SELECT m.pid,
             list(cl.our_row_id::BIGINT ORDER BY u.ord) AS remapped
      FROM new_msr_eric m,
           UNNEST(m.p__keywords) WITH ORDINALITY AS u(eric_rid, ord)
      JOIN oc_concept_rows ocr ON ocr.eric_row_id = u.eric_rid
      JOIN concept_id_lookup cl ON cl.uri = ocr.uri
      GROUP BY m.pid;

    -- p__responsibility (Agent or other entity refs)
    CREATE TEMP TABLE remap_msr_resp AS
      SELECT m.pid,
             list(idm.our_row_id::BIGINT ORDER BY u.ord) AS remapped
      FROM new_msr_eric m,
           UNNEST(m.p__responsibility) WITH ORDINALITY AS u(eric_rid, ord)
      JOIN eric_id_map idm ON idm.eric_row_id = u.eric_rid
      GROUP BY m.pid;
    """)

    # Similarly remap SamplingEvent p__ arrays
    con.execute("""
    -- SE p__sample_location (GeoCoordLoc refs)
    CREATE TEMP TABLE remap_se_sl AS
      SELECT s.pid,
             list(idm.our_row_id::BIGINT ORDER BY u.ord) AS remapped
      FROM new_se_eric s,
           UNNEST(s.p__sample_location) WITH ORDINALITY AS u(eric_rid, ord)
      JOIN eric_id_map idm ON idm.eric_row_id = u.eric_rid
      GROUP BY s.pid;

    -- SE p__sampling_site (SamplingSite refs)
    CREATE TEMP TABLE remap_se_ss AS
      SELECT s.pid,
             list(idm.our_row_id::BIGINT ORDER BY u.ord) AS remapped
      FROM new_se_eric s,
           UNNEST(s.p__sampling_site) WITH ORDINALITY AS u(eric_rid, ord)
      JOIN eric_id_map idm ON idm.eric_row_id = u.eric_rid
      GROUP BY s.pid;

    -- SamplingSite p__site_location (GeoCoordLoc refs)
    CREATE TEMP TABLE remap_site_sl AS
      SELECT s.pid,
             list(idm.our_row_id::BIGINT ORDER BY u.ord) AS remapped
      FROM new_site_eric s,
           UNNEST(s.p__site_location) WITH ORDINALITY AS u(eric_rid, ord)
      JOIN eric_id_map idm ON idm.eric_row_id = u.eric_rid
      GROUP BY s.pid;
    """)
    log("p__ remapping tables built", t0)

    # ---- trust checks before writing ----------------------------------------
    log("running pre-write trust checks...", t0)

    # Check all new MSR p__produced_by refs resolve
    n_unresolved_se = con.sql("""
        SELECT COUNT(*) FROM new_msr_eric m, UNNEST(m.p__produced_by) AS u(rid)
        LEFT JOIN eric_id_map idm ON idm.eric_row_id = u.rid
        WHERE idm.our_row_id IS NULL
    """).fetchone()[0]
    if n_unresolved_se:
        sys.exit(f"FATAL: {n_unresolved_se} p__produced_by references in new MSRs do not resolve")

    # Check all concept references resolve (via URI) — includes p__keywords
    n_unresolved_concepts = con.sql("""
        WITH all_refs AS (
            SELECT m.pid, u.eric_rid FROM new_msr_eric m, UNNEST(m.p__has_material_category) AS u(eric_rid)
            UNION ALL
            SELECT m.pid, u.eric_rid FROM new_msr_eric m, UNNEST(m.p__has_sample_object_type) AS u(eric_rid)
            UNION ALL
            SELECT m.pid, u.eric_rid FROM new_msr_eric m, UNNEST(m.p__has_context_category) AS u(eric_rid)
            UNION ALL
            SELECT m.pid, u.eric_rid FROM new_msr_eric m, UNNEST(m.p__keywords) AS u(eric_rid)
        )
        SELECT COUNT(*) FROM all_refs r
        LEFT JOIN oc_concept_rows ocr ON ocr.eric_row_id = r.eric_rid
        LEFT JOIN concept_id_lookup cl ON cl.uri = ocr.uri
        WHERE cl.our_row_id IS NULL
    """).fetchone()[0]
    if n_unresolved_concepts:
        sys.exit(f"FATAL: {n_unresolved_concepts} concept references (including keywords) in new MSRs do not resolve")

    # Check that rows_to_remove doesn't contain any non-OC rows
    n_non_oc_removal = con.sql(f"""
        SELECT COUNT(*) FROM rows_to_remove rr
        JOIN {SRC} s ON s.row_id = rr.row_id AND s.otype='MaterialSampleRecord'
        WHERE s.n != '{OC_SOURCE}'
    """).fetchone()[0]
    if n_non_oc_removal:
        sys.exit(f"FATAL: {n_non_oc_removal} removal targets are non-OC MSR rows (would corrupt other sources)")

    # FIX B — SILENT-DROP GUARD: verify that every p__* source array on new rows
    # has a 1:1 remapped array (no silently-dropped refs due to inner-join misses).
    #
    # The remapping tables (remap_msr_pb, remap_se_sl, remap_se_ss, remap_site_sl)
    # use INNER JOINs to eric_id_map.  If a source row has a ref not in eric_id_map,
    # that row simply DISAPPEARS from the remap table, and the LEFT JOIN in the
    # write SQL gives NULL for the column — silently dropping the reference.
    #
    # For each (source_table, p__col, remap_table) pair, we assert:
    #   every row with a non-null source array has a matching remap row AND
    #   the remapped array has the same length as the source array.
    # Any mismatch → RuntimeError, build aborted.
    def _check_remap_length(source_table, pid_col, src_col, remap_table, remap_col, label):
        bad = con.sql(f"""
            SELECT s.{pid_col}, len(s.{src_col}) AS src_len, COALESCE(len(r.{remap_col}), 0) AS remap_len
            FROM {source_table} s
            LEFT JOIN {remap_table} r ON r.{pid_col} = s.{pid_col}
            WHERE s.{src_col} IS NOT NULL AND len(s.{src_col}) > 0
              AND COALESCE(len(r.{remap_col}), 0) != len(s.{src_col})
        """).fetchall()
        if bad:
            details = "; ".join(f"{pid_col}={row[0]} src_len={row[1]} remap_len={row[2]}" for row in bad[:5])
            raise RuntimeError(
                f"SILENT-DROP GUARD FAIL [{label}]: {len(bad)} rows have mismatched "
                f"source vs remapped array lengths. First offenders: {details}. "
                f"Check that all referenced entities were extracted before remapping."
            )

    # MSR structural refs
    _check_remap_length("new_msr_eric", "pid", "p__produced_by",      "remap_msr_pb",   "remapped", "MSR.p__produced_by")
    _check_remap_length("new_msr_eric", "pid", "p__registrant",        "remap_msr_reg",  "remapped", "MSR.p__registrant")
    _check_remap_length("new_msr_eric", "pid", "p__responsibility",    "remap_msr_resp", "remapped", "MSR.p__responsibility")
    # MSR concept refs (via URI lookup — p__has_* dims + p__keywords)
    _check_remap_length("new_msr_eric", "pid", "p__has_material_category",    "remap_msr_mat", "remapped", "MSR.p__has_material_category")
    _check_remap_length("new_msr_eric", "pid", "p__has_sample_object_type",   "remap_msr_obj", "remapped", "MSR.p__has_sample_object_type")
    _check_remap_length("new_msr_eric", "pid", "p__has_context_category",     "remap_msr_ctx", "remapped", "MSR.p__has_context_category")
    _check_remap_length("new_msr_eric", "pid", "p__keywords",                 "remap_msr_kw",  "remapped", "MSR.p__keywords")
    # SE structural refs
    _check_remap_length("new_se_eric",   "pid", "p__sample_location",  "remap_se_sl",    "remapped", "SE.p__sample_location")
    _check_remap_length("new_se_eric",   "pid", "p__sampling_site",    "remap_se_ss",    "remapped", "SE.p__sampling_site")
    # SamplingSite structural refs
    _check_remap_length("new_site_eric", "pid", "p__site_location",    "remap_site_sl",  "remapped", "Site.p__site_location")
    log("silent-drop guard: all structural + concept remapped arrays length-verified (PASS)", t0)

    log("trust checks passed", t0)

    # ---- compute expected output row count -----------------------------------
    n_src = con.sql(f"SELECT COUNT(*) FROM {SRC}").fetchone()[0]
    n_new_entities = n_id_map  # entities in eric_id_map
    n_out_expected = n_src - n_rows_to_remove + n_new_entities + n_minted
    log(f"expected output rows: {n_src:,} src - {n_rows_to_remove:,} removed + "
        f"{n_new_entities:,} new entities + {n_minted} concepts = {n_out_expected:,}", t0)

    if args.dry_run:
        log("DRY RUN: skipping write step", t0)
        print("\n=== DRY RUN SUMMARY ===")
        print(f"  removed_pids:         {n_removed_pids:,}")
        print(f"  orphan_rows:          {total_orphan_rows - n_removed_pids:,}")
        print(f"  total_rows_removed:   {n_rows_to_remove:,}")
        print(f"  new_pids:             {n_new_pids:,}")
        print(f"  new_entities:         {n_new_entities:,}")
        print(f"  minted_concepts:      {n_minted}")
        print(f"  expected_out:         {n_out_expected:,}")
        print(f"  trust_checks:         PASS")
        return 0

    # ---- Phase I: write output -----------------------------------------------
    log("writing output...", t0)

    # Build the column list for new MSR rows
    # For each column in src_cols, produce an expression that maps Eric's data to our schema
    # The key transformations:
    #   row_id -> from eric_id_map
    #   n -> 'OPENCONTEXT'
    #   geometry/latitude/longitude -> from new_msr_coords
    #   p__produced_by -> from remap_msr_pb
    #   p__has_material_category -> from remap_msr_mat
    #   p__has_sample_object_type -> from remap_msr_obj
    #   p__has_context_category -> from remap_msr_ctx
    #   p__registrant -> from remap_msr_reg
    #   p__keywords -> from remap_msr_kw
    #   p__responsibility -> from remap_msr_resp
    #   p__curation -> NULL
    #   p__related_resource -> NULL
    #   all others -> direct from new_msr_eric

    # New MSR rows SELECT
    msr_select_cols = []
    for col, typ in src_cols:
        if col == "row_id":
            msr_select_cols.append(f"idm.our_row_id::BIGINT AS row_id")
        elif col == "n":
            msr_select_cols.append(f"'{OC_SOURCE}'::VARCHAR AS n")
        elif col == "geometry":
            msr_select_cols.append(f"coords.geometry AS geometry")
        elif col == "latitude":
            msr_select_cols.append(f"coords.latitude AS latitude")
        elif col == "longitude":
            msr_select_cols.append(f"coords.longitude AS longitude")
        elif col == "p__produced_by":
            msr_select_cols.append(f"rmap_pb.remapped::{typ} AS p__produced_by")
        elif col == "p__has_material_category":
            msr_select_cols.append(f"rmap_mat.remapped::{typ} AS p__has_material_category")
        elif col == "p__has_sample_object_type":
            msr_select_cols.append(f"rmap_obj.remapped::{typ} AS p__has_sample_object_type")
        elif col == "p__has_context_category":
            msr_select_cols.append(f"rmap_ctx.remapped::{typ} AS p__has_context_category")
        elif col == "p__registrant":
            msr_select_cols.append(f"rmap_reg.remapped::{typ} AS p__registrant")
        elif col == "p__keywords":
            msr_select_cols.append(f"rmap_kw.remapped::{typ} AS p__keywords")
        elif col == "p__responsibility":
            msr_select_cols.append(f"rmap_resp.remapped::{typ} AS p__responsibility")
        elif col in OUR_ONLY_COLS:
            msr_select_cols.append(f"NULL::{typ} AS {col}")
        elif col in oc_colnames:
            msr_select_cols.append(f"m.{col}::{typ} AS {col}")
        else:
            msr_select_cols.append(f"NULL::{typ} AS {col}")

    msr_select = ",\n       ".join(msr_select_cols)

    # New SE rows SELECT (remapped p__sample_location and p__sampling_site)
    se_select_cols = []
    for col, typ in src_cols:
        if col == "row_id":
            se_select_cols.append(f"idm.our_row_id::BIGINT AS row_id")
        elif col == "p__sample_location":
            se_select_cols.append(f"rmap_sl.remapped::{typ} AS p__sample_location")
        elif col == "p__sampling_site":
            se_select_cols.append(f"rmap_ss.remapped::{typ} AS p__sampling_site")
        elif col in OUR_ONLY_COLS:
            se_select_cols.append(f"NULL::{typ} AS {col}")
        elif col in oc_colnames:
            se_select_cols.append(f"s.{col}::{typ} AS {col}")
        else:
            se_select_cols.append(f"NULL::{typ} AS {col}")
    se_select = ",\n       ".join(se_select_cols)

    # New SamplingSite rows SELECT (remapped p__site_location)
    site_select_cols = []
    for col, typ in src_cols:
        if col == "row_id":
            site_select_cols.append(f"idm.our_row_id::BIGINT AS row_id")
        elif col == "p__site_location":
            site_select_cols.append(f"rmap_site_sl.remapped::{typ} AS p__site_location")
        elif col in OUR_ONLY_COLS:
            site_select_cols.append(f"NULL::{typ} AS {col}")
        elif col in oc_colnames:
            site_select_cols.append(f"st.{col}::{typ} AS {col}")
        else:
            site_select_cols.append(f"NULL::{typ} AS {col}")
    site_select = ",\n       ".join(site_select_cols)

    # Generic entity SELECT (Geo, Agent: just row_id remapped, all other cols direct)
    # geometry: Eric's wide has GEOMETRY type (spatial extension), our wide has BLOB (WKB).
    # Convert with ST_AsWKB() for GEOMETRY-typed columns; BLOB columns pass through directly.
    def generic_entity_select(alias, table_alias, eric_geo_is_geometry=False):
        parts = []
        for col, typ in src_cols:
            if col == "row_id":
                parts.append(f"idm.our_row_id::BIGINT AS row_id")
            elif col == "geometry" and eric_geo_is_geometry:
                # GeoCoordLoc in Eric's wide stores geometry as GEOMETRY type
                parts.append(
                    f"CASE WHEN {table_alias}.geometry IS NOT NULL "
                    f"THEN ST_AsWKB({table_alias}.geometry)::BLOB "
                    f"ELSE NULL END AS geometry"
                )
            elif col in OUR_ONLY_COLS:
                parts.append(f"NULL::{typ} AS {col}")
            elif col in oc_colnames:
                parts.append(f"{table_alias}.{col}::{typ} AS {col}")
            else:
                parts.append(f"NULL::{typ} AS {col}")
        return ",\n       ".join(parts)

    # GeoCoordLoc in Eric's wide has geometry as GEOMETRY type (auto-decoded by spatial extension)
    geo_select = generic_entity_select("g", "g", eric_geo_is_geometry=True)
    agent_select = generic_entity_select("a", "a")

    # Minted concept rows SELECT
    concept_select_cols = []
    for col, typ in src_cols:
        mapping = {
            "row_id": f"nc.our_row_id::BIGINT",
            "pid": "nc.uri::VARCHAR",
            "otype": "'IdentifiedConcept'::VARCHAR",
            "label": "nc.label::VARCHAR",
            "scheme_name": "nc.scheme_name::VARCHAR",
            "scheme_uri": "nc.scheme_uri::VARCHAR",
        }
        if col in mapping:
            concept_select_cols.append(f"{mapping[col]} AS {col}")
        else:
            concept_select_cols.append(f"NULL::{typ} AS {col}")
    concept_select = ",\n       ".join(concept_select_cols)

    write_sql = f"""
    COPY (
      -- 1. Surviving src rows (all rows NOT in the removal set)
      SELECT * FROM {SRC}
      WHERE row_id NOT IN (SELECT row_id FROM rows_to_remove)

      UNION ALL BY NAME

      -- 2. New MaterialSampleRecord rows (remapped + denormalized coords)
      SELECT {msr_select}
      FROM new_msr_eric m
      JOIN eric_id_map idm ON idm.eric_row_id = m.row_id
      LEFT JOIN new_msr_coords coords ON coords.pid = m.pid
      LEFT JOIN remap_msr_pb rmap_pb ON rmap_pb.pid = m.pid
      LEFT JOIN remap_msr_mat rmap_mat ON rmap_mat.pid = m.pid
      LEFT JOIN remap_msr_obj rmap_obj ON rmap_obj.pid = m.pid
      LEFT JOIN remap_msr_ctx rmap_ctx ON rmap_ctx.pid = m.pid
      LEFT JOIN remap_msr_reg rmap_reg ON rmap_reg.pid = m.pid
      LEFT JOIN remap_msr_kw rmap_kw ON rmap_kw.pid = m.pid
      LEFT JOIN remap_msr_resp rmap_resp ON rmap_resp.pid = m.pid

      UNION ALL BY NAME

      -- 3. New SamplingEvent rows (remapped structural arrays)
      SELECT {se_select}
      FROM new_se_eric s
      JOIN eric_id_map idm ON idm.eric_row_id = s.row_id
      LEFT JOIN remap_se_sl rmap_sl ON rmap_sl.pid = s.pid
      LEFT JOIN remap_se_ss rmap_ss ON rmap_ss.pid = s.pid

      UNION ALL BY NAME

      -- 4. New GeospatialCoordLocation rows (just row_id remapped)
      SELECT {geo_select}
      FROM new_geo_eric g
      JOIN eric_id_map idm ON idm.eric_row_id = g.row_id

      UNION ALL BY NAME

      -- 5. New SamplingSite rows (remapped p__site_location)
      SELECT {site_select}
      FROM new_site_eric st
      JOIN eric_id_map idm ON idm.eric_row_id = st.row_id
      LEFT JOIN remap_site_sl rmap_site_sl ON rmap_site_sl.pid = st.pid

      UNION ALL BY NAME

      -- 6. New Agent rows
      SELECT {agent_select}
      FROM new_agent_eric a
      JOIN eric_id_map idm ON idm.eric_row_id = a.row_id

      UNION ALL BY NAME

      -- 7. Minted IdentifiedConcept rows
      SELECT {concept_select}
      FROM new_concepts_to_mint nc

      ORDER BY row_id
    ) TO '{args.out}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """

    con.execute(write_sql)
    log(f"wrote {args.out}", t0)

    # ---- post-write verification --------------------------------------------
    OUT = f"read_parquet('{args.out}')"
    n_out = con.sql(f"SELECT COUNT(*) FROM {OUT}").fetchone()[0]
    if n_out != n_out_expected:
        sys.exit(f"FATAL: row count {n_out:,} != expected {n_out_expected:,}. "
                 f"(src={n_src:,} - removed={n_rows_to_remove:,} + "
                 f"new={n_new_entities:,} + minted={n_minted})")

    n_dup_out_rowid = con.sql(
        f"SELECT COUNT(*) FROM (SELECT row_id FROM {OUT} GROUP BY row_id HAVING COUNT(*)>1)"
    ).fetchone()[0]
    if n_dup_out_rowid:
        sys.exit(f"FATAL: {n_dup_out_rowid} duplicate row_ids in output")

    n_dup_out_pid = con.sql(
        f"SELECT COUNT(*) FROM (SELECT pid FROM {OUT} WHERE otype='MaterialSampleRecord' "
        f"GROUP BY pid HAVING COUNT(*)>1)"
    ).fetchone()[0]
    if n_dup_out_pid:
        sys.exit(f"FATAL: {n_dup_out_pid} duplicate MaterialSampleRecord pids in output")

    # Verify n='OPENCONTEXT' on ALL new MSR rows in output
    n_wrong_n = con.sql(f"""
        SELECT COUNT(*) FROM {OUT}
        WHERE otype='MaterialSampleRecord' AND n!='{OC_SOURCE}'
        AND pid IN (SELECT pid FROM new_pids)
    """).fetchone()[0]
    if n_wrong_n:
        sys.exit(f"FATAL: {n_wrong_n} new MSR rows have n != '{OC_SOURCE}'")

    # Verify NONE of the removed pids remain in output
    n_stale_pids_remain = con.sql(f"""
        SELECT COUNT(*) FROM {OUT}
        WHERE otype='MaterialSampleRecord' AND n='{OC_SOURCE}'
          AND pid IN (SELECT pid FROM removed_pids)
    """).fetchone()[0]
    if n_stale_pids_remain:
        sys.exit(f"FATAL: {n_stale_pids_remain} stale (removed) pids remain in output")

    out_oc_count = con.sql(
        f"SELECT COUNT(*) FROM {OUT} WHERE otype='MaterialSampleRecord' AND n='{OC_SOURCE}'"
    ).fetchone()[0]
    log(f"post-write: rows={n_out:,}  dup_rowids={n_dup_out_rowid}  "
        f"dup_pids={n_dup_out_pid}  oc_msrs={out_oc_count:,}  "
        f"stale_remain={n_stale_pids_remain}  n_check=PASS", t0)

    # ---- Mandatory in-script dangling-ref gate: ALL rows, ALL p__* columns ----
    # Scan EVERY p__* array column across the ENTIRE output (not just new rows).
    # Surviving src rows must also be checked because orphan deletion can create
    # dangling refs in old rows (e.g. surviving SamplingSites whose p__site_location
    # pointed at geos that were incorrectly deleted as orphans).
    # This is a HARD FAIL if any dangling ref is found — build aborted.
    log("running mandatory dangling-ref gate on ALL rows, ALL p__* columns...", t0)
    p_ref_cols = [
        col for col, typ in src_cols
        if col.startswith("p__")
        and any(t in typ.upper() for t in ("BIGINT", "INTEGER"))
    ]
    n_total_dangling = 0
    dangling_details = {}
    out_row_ids_subq = f"SELECT row_id FROM {OUT}"
    for p_col in p_ref_cols:
        # Check ALL rows in output (both surviving src rows and new rows)
        n_dangle = con.sql(f"""
            WITH all_row_ids AS ({out_row_ids_subq}),
                 refs AS (
                     SELECT unnest(w.{p_col}) AS ref_id
                     FROM {OUT} w
                     WHERE w.{p_col} IS NOT NULL AND len(w.{p_col}) > 0
                 )
            SELECT COUNT(*)
            FROM refs
            LEFT JOIN all_row_ids ON refs.ref_id = all_row_ids.row_id
            WHERE all_row_ids.row_id IS NULL
        """).fetchone()[0]
        dangling_details[p_col] = n_dangle
        n_total_dangling += n_dangle
    for col, cnt in sorted(dangling_details.items()):
        print(f"  {col}: {cnt} dangling refs", flush=True)
    if n_total_dangling:
        raise RuntimeError(
            f"INTEGRITY FAIL: {n_total_dangling} dangling references in output. "
            f"Per-column: {dangling_details}. Build aborted — do NOT emit manifest."
        )
    log(f"Dangling ref check: PASS (0 dangling across {len(p_ref_cols)} columns)", t0)

    # ---- Phase J: description enrichment (#277) ---------------------------------
    # OC sample descriptions in the combined wide are terse LD metadata strings
    # ('updated': 2023-10-05...) instead of the human-readable site-path strings
    # ('Open Context published "Sample" from: Europe/Cyprus/PKAP Survey Area/...')
    # present in Eric's OC wide. Overwrite `description` for ALL OC MSR pids in
    # the output from Eric's wide. This covers both existing ~1.04M pids that
    # survived the sync and the 67,187 newly added pids.
    #
    # Implementation: single DuckDB COPY rewriting only the description column
    # for OC MSR rows; all other columns and all non-OC rows pass through as-is.
    # Row counts are invariant (JOIN on pid, not a filter).
    log("description enrichment (#277): copying OC descriptions from Eric's wide…", t0)

    tmp_enriched = args.out + ".enriching.tmp"
    # Use a UNION ALL approach for efficiency: join only OC MSR rows (1.1M) with
    # Eric's wide for descriptions, then pass all non-OC rows through unchanged.
    # This avoids a full-scan LEFT JOIN on 20M rows (which materializes the full
    # wide in memory and is very slow). Both branches use SELECT * REPLACE for
    # schema-agnostic column handling.
    con.execute(f"""
    COPY (
      -- OC MSR rows: overwrite description from Eric's wide where available
      SELECT w.* REPLACE (
        CASE WHEN oc.description IS NOT NULL THEN oc.description ELSE w.description END AS description
      )
      FROM read_parquet('{args.out}') w
      LEFT JOIN (
        SELECT pid, description FROM {OC} WHERE otype='MaterialSampleRecord'
      ) oc ON oc.pid = w.pid
      WHERE w.otype='MaterialSampleRecord' AND w.n='{OC_SOURCE}'

      UNION ALL BY NAME

      -- All non-OC rows: pass through unchanged (no description modification)
      SELECT * FROM read_parquet('{args.out}')
      WHERE NOT (otype='MaterialSampleRecord' AND n='{OC_SOURCE}')

      ORDER BY row_id
    ) TO '{tmp_enriched}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)

    # Trust gate: verify row count is unchanged, then check Cyprus count
    n_enriched = con.sql(f"SELECT COUNT(*) FROM read_parquet('{tmp_enriched}')").fetchone()[0]
    if n_enriched != n_out:
        os.unlink(tmp_enriched)
        sys.exit(f"FATAL: description enrichment changed row count {n_out:,} → {n_enriched:,}")

    n_cyprus = con.sql(
        f"SELECT COUNT(*) FROM read_parquet('{tmp_enriched}') "
        f"WHERE otype='MaterialSampleRecord' AND n='{OC_SOURCE}' "
        f"AND description ILIKE '%Cyprus%'"
    ).fetchone()[0]
    log(f"description enrichment trust gate: Cyprus OC MSR count = {n_cyprus:,} (expect ≈ 69,230)", t0)
    # Hard trust gate: only applies at production scale (out_oc_count > 1M) to avoid
    # false-positive failures on small synthetic fixtures that lack Cyprus descriptions.
    # Threshold 69,000 is conservative relative to the observed production count of 69,230.
    CYPRUS_THRESHOLD = 69000
    if out_oc_count > 1_000_000 and n_cyprus < CYPRUS_THRESHOLD:
        os.unlink(tmp_enriched)
        raise RuntimeError(
            f"Trust gate FAIL: Cyprus description count {n_cyprus:,} < {CYPRUS_THRESHOLD:,} threshold. "
            f"Description enrichment may have failed or OC wide is missing Cyprus data."
        )

    # Atomically replace the output with the enriched version
    os.replace(tmp_enriched, args.out)
    log(f"description enrichment complete: replaced {args.out}", t0)

    # ---- manifest -----------------------------------------------------------
    if not args.no_manifest:
        manifest = {
            "script": os.path.basename(__file__),
            "argv": sys.argv,
            "git_sha": git_sha(),
            "duckdb_version": duckdb.__version__,
            "policy": ("TRUE SYNC: add new OC pids + remove stale OC pids from Eric's fresh OC PQG wide "
                       "(#272 phase 2, D3 decision 2026-06-12)"),
            "inputs": {
                "src": {"path": args.src, "bytes": os.path.getsize(args.src),
                        "sha256": sha256_file(args.src)},
                "oc_wide": {"path": args.oc_wide, "bytes": os.path.getsize(args.oc_wide),
                            "sha256": sha256_file(args.oc_wide)},
            },
            "counts": {
                "src_rows": n_src,
                "removed_pids": n_removed_pids,
                "orphan_rows": total_orphan_rows - n_removed_pids,
                "total_rows_removed": n_rows_to_remove,
                "orphan_breakdown": orphan_counts,
                "new_pids": n_new_pids,
                "new_entity_rows": n_new_entities,
                "minted_concepts": n_minted,
                "out_rows": n_out,
                "new_oc_msr_total": out_oc_count,
                "entity_breakdown": counts,
            },
            "output": {"path": args.out, "bytes": os.path.getsize(args.out),
                       "sha256": sha256_file(args.out)},
        }
        mpath = args.out + ".manifest.json"
        with open(mpath, "w") as fh:
            json.dump(manifest, fh, indent=2)
        log(f"manifest -> {mpath}", t0)

    log("done", t0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
