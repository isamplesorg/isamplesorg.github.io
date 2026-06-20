#!/usr/bin/env python3
"""Algebraic, AI-free trust gate for the explorer's derived parquet.

This is NOT a code review and NOT a spot check. It recomputes the derived-file
*algebra* from `sample_facets_v2` / `samples_map_lite` and asserts the other
files agree. A rebuild that is wrong (collapsed materials, stale summaries,
drifted cross-filter, duplicate pids, broken H3) FAILS here. Exits non-zero on
any failure so it can gate CI / a publish.

Usage:
  python scripts/validate_frontend_derived.py --dir /tmp/rebuild-202606 --tag isamples_202606
  # or point at live/remote files:
  python scripts/validate_frontend_derived.py \
      --facets URL --map-lite URL --summaries URL --cross-filter URL \
      --h3 URL4 URL6 URL8
  # hierarchy + #305/#306 complete index (auto-discovered with --dir/--tag, or):
  python scripts/validate_frontend_derived.py --dir DIR --tag TAG --index INDEX.parquet
"""
import argparse, hashlib, json, os, sys
import duckdb


def sha256_file(path, _b=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_b), b""):
            h.update(chunk)
    return h.hexdigest()

MATERIAL_ROOT = "https://w3id.org/isample/vocabulary/material/1.0/material"
PID_K = "ark:/28722/k2p55x96j"  # #260 sentinel (a ceramic)
# Expected sentinel material BY DATA VINTAGE:
#   pre-#272 wides (frozen-export lineage, e.g. 202601/202604): the export's
#     (wrong) value — anthropogenicmetal — because #271 only fixed SELECTION,
#     not the data. The check then asserts selection didn't regress.
#   post-#272 wides (OC-concept-enriched, 202606+): the corrected value from
#     Eric's OC PQG — otheranthropogenicmaterial (see #260/#272).
# Default = the enriched expectation; validate a legacy build with
#   --sentinel-material https://w3id.org/isample/vocabulary/material/1.0/anthropogenicmetal
PID_K_EXPECTED = "https://w3id.org/isample/vocabulary/material/1.0/otheranthropogenicmaterial"

EXPECTED_SCHEMA = {
    "facets": [("pid", "VARCHAR"), ("source", "VARCHAR"), ("material", "VARCHAR"),
               ("context", "VARCHAR"), ("object_type", "VARCHAR"), ("label", "VARCHAR"),
               ("description", "VARCHAR"), ("place_name", "VARCHAR")],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir"); ap.add_argument("--tag")
    ap.add_argument("--facets"); ap.add_argument("--map-lite")
    ap.add_argument("--summaries"); ap.add_argument("--cross-filter")
    ap.add_argument("--h3", nargs=3, metavar=("R4", "R6", "R8"))
    ap.add_argument("--tree-summaries", help="facet_tree_summaries parquet (#281/#282); optional")
    ap.add_argument("--membership", help="sample_facet_membership parquet (#281/#282); optional")
    ap.add_argument("--tree-cross-filter", help="facet_tree_cross_filter parquet (#290/#293); optional")
    ap.add_argument("--node-bits", help="facet_node_bits parquet (#293); optional")
    ap.add_argument("--masks", help="sample_facet_masks parquet (#293); optional")
    ap.add_argument("--index", help="sample_facet_index parquet (#305/#306); optional")
    ap.add_argument("--wide", help="source wide parquet — enables the SEMANTIC gate "
                    "(re-derive and diff the written files against a fresh build)")
    ap.add_argument("--min-rows", type=int, default=1_000_000,
                    help="floor for the non-empty sanity check (use 1 for fixtures)")
    ap.add_argument("--sentinel-material", default=PID_K_EXPECTED,
                    help="expected material URI for the #260 sentinel pid; default is the "
                         "post-#272 (OC-enriched) value — override for pre-enrichment builds")
    a = ap.parse_args()

    def f(name, attr):
        v = getattr(a, attr)
        if v:
            return v
        if a.dir and a.tag:
            return os.path.join(a.dir, f"{a.tag}_{name}.parquet")
        sys.exit(f"FATAL: provide --{attr} or both --dir and --tag")

    facets = f("sample_facets_v2", "facets")
    maplite = f("samples_map_lite", "map_lite")
    summaries = f("facet_summaries", "summaries")
    crossf = f("facet_cross_filter", "cross_filter")
    h3 = a.h3 or ([os.path.join(a.dir, f"{a.tag}_h3_summary_res{r}.parquet") for r in (4, 6, 8)]
                  if a.dir and a.tag else None)

    con = duckdb.connect()
    R = []  # (name, passed, detail)
    info = []
    def check(name, passed, detail=""):
        R.append((name, bool(passed), detail))
    def scalar(sql):
        return con.sql(sql).fetchone()[0]

    F = f"read_parquet('{facets}')"
    ML = f"read_parquet('{maplite}')"
    S = f"read_parquet('{summaries}')"
    CF = f"read_parquet('{crossf}')"

    # --- 1. material root absent (the #265/#271 contract) ---
    check("material root absent", scalar(f"SELECT COUNT(*) FROM {F} WHERE material='{MATERIAL_ROOT}'") == 0,
          "facets rows with bare root material (want 0)")

    # --- 2. #260 sentinel (skip when the pid isn't in this dataset, e.g. fixtures) ---
    row = con.sql(f"SELECT material FROM {F} WHERE pid='{PID_K}'").fetchone()
    if row is None:
        info.append(f"sentinel {PID_K} not present (N/A for this dataset)")
    else:
        check(f"sentinel {PID_K} == expected vintage value", row[0] == a.sentinel_material,
              f"got {row}, expected {a.sentinel_material} (wrong --sentinel-material for this data vintage?)")

    # --- 3. PID uniqueness (browser relies on one row per pid) ---
    check("facets pid unique", scalar(f"SELECT COUNT(*) FROM (SELECT pid FROM {F} GROUP BY pid HAVING COUNT(*)>1)") == 0,
          "duplicate pids in facets")
    check("map_lite pid unique", scalar(f"SELECT COUNT(*) FROM (SELECT pid FROM {ML} GROUP BY pid HAVING COUNT(*)>1)") == 0,
          "duplicate pids in map_lite")

    # --- 4. facets.pid SET == map_lite.pid SET ---
    diff = scalar(f"""SELECT
        (SELECT COUNT(*) FROM (SELECT pid FROM {F} EXCEPT SELECT pid FROM {ML})) +
        (SELECT COUNT(*) FROM (SELECT pid FROM {ML} EXCEPT SELECT pid FROM {F}))""")
    check("facets.pid == map_lite.pid", diff == 0, f"{diff} pids differ between facets and map_lite")

    # --- 5. ALGEBRA: facet_summaries == GROUP BY facets (per dim) ---
    # NOTE: build_frontend_derived.py filters both NULL and empty-string values (#283a fix).
    recompute = " UNION ALL ".join(
        f"SELECT '{d}' AS facet_type, {d} AS facet_value, COUNT(*) AS c FROM {F} WHERE {d} IS NOT NULL AND {d} <> '' GROUP BY {d}"
        for d in ("source", "material", "context", "object_type"))
    mismatch = scalar(f"""
      WITH recomputed AS ({recompute}),
           summ AS (SELECT facet_type, facet_value, count AS c FROM {S})
      SELECT COUNT(*) FROM (
        SELECT * FROM recomputed EXCEPT SELECT * FROM summ
        UNION ALL
        SELECT * FROM summ EXCEPT SELECT * FROM recomputed)""")
    check("facet_summaries == GROUP BY facets", mismatch == 0, f"{mismatch} (facet_type,value,count) rows disagree")
    check("facet_summaries.scheme all NULL", scalar(f"SELECT COUNT(*) FROM {S} WHERE scheme IS NOT NULL") == 0,
          "non-NULL scheme rows (contract: scheme is NULL)")
    # --- 5b. blank facet values absent (#283a) — also catches whitespace-only values ---
    check("facet_summaries no blank values (#283a)", scalar(f"SELECT COUNT(*) FROM {S} WHERE TRIM(facet_value) = ''") == 0,
          "blank/whitespace-only facet_value rows (want 0; caused by GEOME empty-string concept URI)")

    # --- 6. ALGEBRA: facet_cross_filter single-dim rows == conditional GROUP BY facets ---
    # NOTE: build_frontend_derived.py filters both NULL and empty-string values (#283a fix).
    dims = ("source", "material", "context", "object_type")
    parts = []
    for filt in dims:
        for fd in dims:
            parts.append(
                f"SELECT '{filt}' AS fcol, {filt} AS fval, '{fd}' AS facet_type, {fd} AS facet_value, COUNT(*) AS c "
                f"FROM {F} WHERE {filt} IS NOT NULL AND {filt} <> '' AND {fd} IS NOT NULL AND {fd} <> '' GROUP BY {filt}, {fd}")
    recompute_cf = " UNION ALL ".join(parts)
    # normalize cross_filter single-dim rows into (fcol, fval, facet_type, facet_value, count)
    cf_single = f"""
      SELECT 'source' AS fcol, filter_source AS fval, facet_type, facet_value, count FROM {CF} WHERE filter_source IS NOT NULL
      UNION ALL SELECT 'material', filter_material, facet_type, facet_value, count FROM {CF} WHERE filter_material IS NOT NULL
      UNION ALL SELECT 'context', filter_context, facet_type, facet_value, count FROM {CF} WHERE filter_context IS NOT NULL
      UNION ALL SELECT 'object_type', filter_object_type, facet_type, facet_value, count FROM {CF} WHERE filter_object_type IS NOT NULL
    """
    cf_mismatch = scalar(f"""
      WITH rc AS ({recompute_cf}), cf AS ({cf_single})
      SELECT COUNT(*) FROM (
        SELECT * FROM rc EXCEPT SELECT * FROM cf
        UNION ALL
        SELECT * FROM cf EXCEPT SELECT * FROM rc)""")
    check("cross_filter == conditional GROUP BY facets", cf_mismatch == 0, f"{cf_mismatch} single-dim rows disagree")

    # --- 7. cross_filter baseline (all filter_* NULL) == facet_summaries ---
    base_mismatch = scalar(f"""
      WITH base AS (SELECT facet_type, facet_value, count FROM {CF}
                    WHERE filter_source IS NULL AND filter_material IS NULL
                      AND filter_context IS NULL AND filter_object_type IS NULL),
           summ AS (SELECT facet_type, facet_value, count FROM {S})
      SELECT COUNT(*) FROM (
        SELECT * FROM base EXCEPT SELECT * FROM summ
        UNION ALL SELECT * FROM summ EXCEPT SELECT * FROM base)""")
    check("cross_filter baseline == summaries", base_mismatch == 0, f"{base_mismatch} baseline rows disagree")

    # --- 8. H3: per-resolution sample_count sums to located-sample total ---
    if h3:
        ml_n = scalar(f"SELECT COUNT(*) FROM {ML}")
        for res, hp in zip((4, 6, 8), h3):
            tot = scalar(f"SELECT SUM(sample_count) FROM read_parquet('{hp}')")
            check(f"h3 res{res} counts sum to map_lite", tot == ml_n, f"sum={tot} vs map_lite={ml_n}")

    # --- 9. schema/types ---
    sch = [(r[0], r[1]) for r in con.sql(f"DESCRIBE SELECT * FROM {F}").fetchall()]
    check("facets schema matches contract", sch == EXPECTED_SCHEMA["facets"], f"got {sch}")

    # --- 10. sanity floor ---
    total, mat = con.sql(f"SELECT COUNT(*), COUNT(material) FROM {F}").fetchone()
    check("facets non-empty", total >= a.min_rows, f"{total:,} rows (min {a.min_rows:,})")

    # --- 11. SEMANTIC gate vs the source wide (the REAL trust gate) ---
    # Internal-consistency checks (1-10) pass even on a wrecked-but-self-consistent
    # rebuild (proven). Re-derive from the wide with the SAME builder logic and
    # assert the WRITTEN files match it. Catches corrupted material/coords/H3,
    # stale files, and wrong-version artifacts.
    if a.wide:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import build_frontend_derived as B
        con.execute("INSTALL h3 FROM community; LOAD h3; INSTALL spatial; LOAD spatial;")
        B.build_base_tables(con, a.wide, 0.0)  # builds samp_geo; hard-fails on dup keys

        def except_diff(asql, bsql):
            return scalar(f"SELECT (SELECT COUNT(*) FROM (({asql}) EXCEPT ({bsql}))) "
                          f"+ (SELECT COUNT(*) FROM (({bsql}) EXCEPT ({asql})))")

        # description in facets_v2 is SEARCH-ONLY: concept labels are appended by
        # the builder (#277 part 2). We import the SAME expression from the builder
        # so the validator and builder can never drift from each other.
        from build_frontend_derived import FACETS_DESCRIPTION_EXPR
        ref_facets = (f"SELECT pid, source, material, context, object_type, label, "
                      f"{FACETS_DESCRIPTION_EXPR} AS description, "
                      f"place_name::VARCHAR AS place_name FROM samp_geo")
        file_facets = f"SELECT pid, source, material, context, object_type, label, description, place_name FROM {F}"
        check("facets == fresh build from --wide", except_diff(ref_facets, file_facets) == 0,
              "facets rows differ from a re-derivation off the wide (corruption/stale/wrong-version)")

        ref_ml = ("SELECT pid, label, source, latitude, longitude, result_time, "
                  "h3_res4::UBIGINT AS h3_res4, h3_res6::UBIGINT AS h3_res6, "
                  "h3_res8::UBIGINT AS h3_res8, h3_h3_to_string(h3_res8) AS h3_res8_hex, "
                  "place_name::VARCHAR AS pn FROM samp_geo")
        file_ml = (f"SELECT pid, label, source, latitude, longitude, result_time, h3_res4, h3_res6, h3_res8, h3_res8_hex, "
                   f"place_name::VARCHAR AS pn FROM {ML}")
        check("map_lite == fresh build from --wide", except_diff(ref_ml, file_ml) == 0,
              "map_lite coords/h3/place_name differ from a re-derivation off the wide")

        if h3:
            for res, hp in zip((4, 6, 8), h3):
                ref_h3 = (f"WITH sc AS (SELECT h3_res{res} AS cell, source, COUNT(*) c FROM samp_geo "
                          f"WHERE h3_res{res} IS NOT NULL GROUP BY h3_res{res}, source), "
                          f"dom AS (SELECT cell, source AS ds, ROW_NUMBER() OVER (PARTITION BY cell ORDER BY c DESC, source ASC) rn FROM sc), "
                          f"agg AS (SELECT h3_res{res} AS cell, COUNT(*) sc2, COUNT(DISTINCT source) srcc, "
                          f"ROUND(AVG(latitude),6) clat, ROUND(AVG(longitude),6) clng FROM samp_geo "
                          f"WHERE h3_res{res} IS NOT NULL GROUP BY h3_res{res}) "
                          f"SELECT agg.cell::UBIGINT h3_cell, agg.sc2::INTEGER sample_count, agg.clat center_lat, "
                          f"agg.clng center_lng, dom.ds AS dominant_source, agg.srcc::INTEGER source_count, "
                          f"{res}::INTEGER resolution FROM agg JOIN dom ON dom.cell=agg.cell AND dom.rn=1")
                FH = f"read_parquet('{hp}')"
                # discrete cols exact (now incl. resolution)
                disc_ref = f"SELECT h3_cell, sample_count, dominant_source, source_count, resolution FROM ({ref_h3})"
                disc_file = f"SELECT h3_cell, sample_count, dominant_source, source_count, resolution FROM {FH}"
                check(f"h3 res{res} discrete == fresh build", except_diff(disc_ref, disc_file) == 0,
                      "h3 cells/counts/dominant_source/resolution differ from re-derivation off the wide")
                # centers: tolerant (float/thread last-ULP jitter ok; gross corruption like 0,0 caught)
                cdiff = scalar(f"SELECT COALESCE(MAX(GREATEST(ABS(f.center_lat-r.center_lat), "
                               f"ABS(f.center_lng-r.center_lng))), 0) FROM {FH} f JOIN ({ref_h3}) r ON f.h3_cell=r.h3_cell")
                # tolerance 1e-5 (~1 m): absorbs the ~1e-6 round/thread jitter, catches
                # any meaningful shift (an adversary's 8e-5/~9 m shift previously slipped
                # through the old 1e-4). Residual undetected error is bounded at ~1 m on
                # display-only cluster centroids.
                check(f"h3 res{res} centers within 1e-5 (~1m)", cdiff <= 1e-5, f"max center delta {cdiff}")

    # --- 12. manifest integrity (when a {tag}_manifest.json is present) ---
    # The build emits a provenance manifest (per-output + input sha256). Verify the
    # written files match it, so the manifest is a guarded attestation, not decoration.
    # NOTE: the manifest is self-attesting (not signed) — this catches accidental
    # corruption, stale files, and tampering that didn't also rewrite the manifest;
    # it does NOT defend against an attacker who rewrites file+manifest consistently.
    if a.dir and a.tag:
        man_path = os.path.join(a.dir, f"{a.tag}_manifest.json")
        if os.path.exists(man_path):
            try:
                man = json.load(open(man_path))
            except Exception as e:
                man = None
                check("manifest parses", False, f"unreadable: {e}")
            if man:
                outs = man.get("outputs", {})
                check("manifest has outputs", bool(outs), "empty manifest.outputs")
                bad = []
                for fname, m in outs.items():
                    fp = os.path.join(a.dir, fname)
                    if not os.path.exists(fp):
                        bad.append(f"{fname}:missing")
                    elif sha256_file(fp) != m.get("sha256"):
                        bad.append(f"{fname}:sha256")
                check("manifest sha256 matches output files", not bad, f"mismatches: {bad}")
                if a.wide:
                    msha = man.get("input", {}).get("sha256")
                    if msha and msha != "remote/unhashed":
                        check("manifest input sha256 matches --wide", sha256_file(a.wide) == msha,
                              "wide sha256 != manifest.input.sha256")
        else:
            info.append(f"no {a.tag}_manifest.json (manifest verification skipped)")

    # --- informational (not failing): context/object_type root presence ---
    for dim, root in [("context", "https://w3id.org/isample/vocabulary/sampledfeature/1.0/anysampledfeature"),
                      ("object_type", "https://w3id.org/isample/vocabulary/materialsampleobjecttype/1.0/materialsample")]:
        n = scalar(f"SELECT COUNT(*) FROM {F} WHERE {dim}='{root}'")
        info.append(f"{dim} root-concept rows: {n:,} (informational; root-dropping deferred)")

    # --- hierarchy artifacts (#281/#282) — checked only when present ---
    def _opt(name, attr):
        v = getattr(a, attr)
        if v:
            return v
        if a.dir and a.tag:
            p = os.path.join(a.dir, f"{a.tag}_{name}.parquet")
            return p if os.path.exists(p) else None
        return None
    tree = _opt("facet_tree_summaries", "tree_summaries")
    mem = _opt("sample_facet_membership", "membership")
    treexf = _opt("facet_tree_cross_filter", "tree_cross_filter")
    nodebits = _opt("facet_node_bits", "node_bits")
    masks = _opt("sample_facet_masks", "masks")
    index = _opt("sample_facet_index", "index")
    if tree:
        T = f"read_parquet('{tree}')"
        # parent ≥ child for every edge, every dim (distinct-pid UNION semantics —
        # NOT additive; see FACET_HIERARCHY_PLAN.md §2.2).
        viol = scalar(f"""SELECT COUNT(*) FROM {T} c JOIN {T} p
            ON p.concept_uri=c.parent_uri AND p.facet_type=c.facet_type
            WHERE c.count > p.count""")
        check("tree: parent count >= every child count", viol == 0, f"{viol} edges violate")
        # every non-null parent_uri resolves to a node (no dangling edges)
        orph = scalar(f"""SELECT COUNT(*) FROM {T} c WHERE c.parent_uri IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM {T} p WHERE p.concept_uri=c.parent_uri AND p.facet_type=c.facet_type)""")
        check("tree: every parent_uri resolves to a node", orph == 0, f"{orph} dangling parents")
        # exactly one root per hierarchical dim
        badroots = scalar(f"""SELECT COUNT(*) FROM (
            SELECT facet_type, COUNT(*) n FROM {T} WHERE parent_uri IS NULL GROUP BY facet_type HAVING n<>1)""")
        check("tree: exactly one root per dim", badroots == 0, f"{badroots} dims with !=1 root")
        # all three hierarchical dims present (catches a silently-missing dim)
        dims_present = scalar(f"SELECT COUNT(DISTINCT facet_type) FROM {T}")
        check("tree: all 3 hierarchical dims present", dims_present == 3,
              f"{dims_present} dims present (want material/context/object_type)")
        # CROSS-FILE ALGEBRA: material root membership == facets_v2 non-root material
        # (both = located samples carrying ≥1 non-root material concept).
        # NOTE (Codex r2): this equality holds under the current-data invariant
        # "0 material concepts excluded from the hierarchy" (every located
        # material concept resolves to the material tree). If a future vintage
        # introduces a material concept absent from the SKOS tree, facets_v2 would
        # still count it flat while the hierarchy excludes it, and this check would
        # (correctly) fail — revisit the equality then.
        mat_root = scalar(f"SELECT count FROM {T} WHERE facet_type='material' AND parent_uri IS NULL")
        fv2_mat = scalar(f"SELECT COUNT(*) FROM {F} WHERE material IS NOT NULL")
        check("tree: material root == facets_v2 non-root material count",
              mat_root == fv2_mat, f"tree={mat_root:,} vs facets_v2={fv2_mat:,}")
    if mem:
        M = f"read_parquet('{mem}')"
        dup = scalar(f"SELECT COUNT(*) FROM (SELECT pid,facet_type,concept_uri FROM {M} GROUP BY 1,2,3 HAVING COUNT(*)>1)")
        check("membership: (pid,facet_type,concept_uri) unique", dup == 0, f"{dup} dup grain rows")
        if tree:  # tree_summaries must EXACTLY equal a fresh GROUP BY of membership
            T2 = f"read_parquet('{tree}')"
            # symmetric: neither side has a (facet_type,concept,count) the other lacks
            mm = scalar(f"""
                WITH g AS (SELECT facet_type, concept_uri, COUNT(DISTINCT pid) AS count FROM {M} GROUP BY 1,2),
                     t AS (SELECT facet_type, concept_uri, count FROM {T2})
                SELECT (SELECT COUNT(*) FROM (SELECT * FROM g EXCEPT SELECT * FROM t))
                     + (SELECT COUNT(*) FROM (SELECT * FROM t EXCEPT SELECT * FROM g))""")
            check("tree counts == GROUP BY membership (symmetric)", mm == 0, f"{mm} rows disagree")

    # --- facet_tree_cross_filter cube (#290/#293) — checked only when present ---
    # CROSS-FILE ALGEBRA: the cube must EXACTLY equal a fresh re-derivation of the
    # single-active-filter cross-filter self-join over the WRITTEN membership (tree
    # dims, subtree semantics) ∪ source (from facets_v2), plus the baseline. This is
    # the same algebra the builder runs, recomputed independently here from the
    # written sibling files — a drifted/stale/corrupt cube FAILS. AI-free.
    if treexf:
        if not mem:
            check("tree_cross_filter present but membership missing", False,
                  "need --membership (or {tag}_sample_facet_membership.parquet) to validate the cube")
        else:
            X = f"read_parquet('{treexf}')"
            M = f"read_parquet('{mem}')"
            # re-derive xf = tree membership ∪ flat source (from facets_v2 = located universe)
            xf = (f"SELECT pid, facet_type AS dim, concept_uri AS value FROM {M} "
                  f"UNION ALL SELECT pid, 'source' AS dim, source AS value FROM {F} "
                  f"WHERE NULLIF(TRIM(source), '') IS NOT NULL")
            ref = (f"WITH xf AS ({xf}), "
                   f"single AS (SELECT f.dim fdim, f.value fval, t.dim facet_type, t.value facet_value, "
                   f"COUNT(DISTINCT t.pid) count FROM xf f JOIN xf t ON t.pid=f.pid AND t.dim<>f.dim GROUP BY 1,2,3,4), "
                   f"base AS (SELECT NULL::VARCHAR fdim, NULL::VARCHAR fval, dim facet_type, value facet_value, "
                   f"COUNT(DISTINCT pid) count FROM xf GROUP BY dim, value) "
                   f"SELECT CASE WHEN fdim='source' THEN fval END filter_source, "
                   f"CASE WHEN fdim='material' THEN fval END filter_material, "
                   f"CASE WHEN fdim='context' THEN fval END filter_context, "
                   f"CASE WHEN fdim='object_type' THEN fval END filter_object_type, "
                   f"facet_type, facet_value, count FROM (SELECT * FROM single UNION ALL SELECT * FROM base)")
            filecube = (f"SELECT filter_source, filter_material, filter_context, filter_object_type, "
                        f"facet_type, facet_value, count FROM {X}")
            # GRAIN first: EXCEPT below is SET semantics, so a duplicated cube would
            # pass the symmetric diff. One row per (all filter cols, facet_type,
            # facet_value) is the contract the explorer relies on. (Codex P3.)
            xdup = scalar(f"""SELECT COUNT(*) FROM (
                SELECT filter_source, filter_material, filter_context, filter_object_type,
                       facet_type, facet_value
                FROM {X} GROUP BY 1,2,3,4,5,6 HAVING COUNT(*) > 1)""")
            check("tree_cross_filter grain unique", xdup == 0, f"{xdup} duplicated cube keys")
            mm = scalar(f"SELECT (SELECT COUNT(*) FROM (({ref}) EXCEPT ({filecube}))) "
                        f"+ (SELECT COUNT(*) FROM (({filecube}) EXCEPT ({ref})))")
            check("tree_cross_filter == re-derived self-join (symmetric)", mm == 0,
                  f"{mm} rows disagree (drifted/stale/corrupt cube)")
            # baseline (all filter_* NULL) tree rows == facet_tree_summaries counts
            if tree:
                T3 = f"read_parquet('{tree}')"
                bmm = scalar(f"""
                  WITH cb AS (SELECT facet_type, facet_value, count FROM {X}
                              WHERE filter_source IS NULL AND filter_material IS NULL
                                AND filter_context IS NULL AND filter_object_type IS NULL
                                AND facet_type <> 'source'),
                       ts AS (SELECT facet_type, concept_uri AS facet_value, count FROM {T3})
                  SELECT (SELECT COUNT(*) FROM (SELECT * FROM cb EXCEPT SELECT * FROM ts))
                       + (SELECT COUNT(*) FROM (SELECT * FROM ts EXCEPT SELECT * FROM cb))""")
                check("tree_cross_filter baseline == tree_summaries", bmm == 0,
                      f"{bmm} baseline tree rows disagree with facet_tree_summaries")

    # --- #293 bitmask filter artifacts (facet_node_bits + sample_facet_masks) ---
    # The explorer filters broad multi-tree selections with a columnar bitwise
    # predicate over sample_facet_masks instead of a 39M-row membership GROUP BY.
    # These checks prove the masks are SET-IDENTICAL to membership (so the filter
    # results can't differ from the old path) and node_bits is a clean assignment.
    if nodebits:
        NB = f"read_parquet('{nodebits}')"
        if mem:
            M = f"read_parquet('{mem}')"
            # node_bits covers EXACTLY the distinct (facet_type, concept_uri) in membership
            cov = scalar(f"""SELECT
                (SELECT COUNT(*) FROM (SELECT DISTINCT facet_type, concept_uri FROM {M}
                                       EXCEPT SELECT facet_type, concept_uri FROM {NB}))
              + (SELECT COUNT(*) FROM (SELECT facet_type, concept_uri FROM {NB}
                                       EXCEPT SELECT DISTINCT facet_type, concept_uri FROM {M}))""")
            check("node_bits covers exactly membership nodes", cov == 0, f"{cov} node(s) differ from membership")
        # bit_index dense 0..N-1, unique, and within signed-BIGINT range per dim
        bad = scalar(f"""SELECT COUNT(*) FROM (
            SELECT facet_type, COUNT(*) AS n, MIN(bit_index) AS lo, MAX(bit_index) AS hi,
                   COUNT(DISTINCT bit_index) AS d
            FROM {NB} GROUP BY facet_type
            HAVING lo<>0 OR hi<>n-1 OR d<>n OR hi>62)""")
        check("node_bits: dense unique 0..N-1 per dim (<=62)", bad == 0, f"{bad} dim(s) with a bad bit range")
    if masks:
        X = f"read_parquet('{masks}')"
        mdup = scalar(f"SELECT COUNT(*) FROM (SELECT pid FROM {X} GROUP BY pid HAVING COUNT(*)>1)")
        check("masks: one row per pid", mdup == 0, f"{mdup} duplicate pids in masks")
        # build_id must be a single value AND match node_bits (Codex P1): the
        # explorer enables the mask path only when these agree, so a mismatch here
        # is a build error that would silently disable the fast path in prod.
        mbids = scalar(f"SELECT COUNT(DISTINCT build_id) FROM {X}")
        check("masks: single build_id", mbids == 1, f"{mbids} distinct build_ids in masks (want 1)")
        if nodebits:
            nb_bid = scalar(f"SELECT COUNT(DISTINCT build_id) FROM read_parquet('{nodebits}')")
            check("node_bits: single build_id", nb_bid == 1, f"{nb_bid} distinct build_ids in node_bits")
            # Only compare when both are single-valued, else the scalar subqueries
            # below return multiple rows and throw (Codex r2). Use MIN/MAX agg so a
            # multi-valued file degrades to a clean FAIL, not an exception.
            if nb_bid == 1 and mbids == 1:
                same = scalar(f"SELECT (SELECT MIN(build_id) FROM read_parquet('{nodebits}')) "
                              f"= (SELECT MIN(build_id) FROM {X})")
                check("node_bits/masks build_id match", bool(same),
                      "build_id differs between node_bits and masks (mixed generations)")
            else:
                check("node_bits/masks build_id match", False,
                      "cannot compare — an artifact has multiple build_ids")
        if mem and nodebits:
            M = f"read_parquet('{mem}')"
            NB = f"read_parquet('{nodebits}')"
            # SEMANTIC gate: re-derive masks from the WRITTEN membership + node_bits
            # (independent of the builder's internal ROW_NUMBER) and diff symmetric.
            ref = (f"WITH nb AS (SELECT facet_type, concept_uri, (1::BIGINT << bit_index) AS bitval FROM {NB}) "
                   f"SELECT m.pid, "
                   f"COALESCE(bit_or(CASE WHEN m.facet_type='material' THEN nb.bitval END),0)::BIGINT material_mask, "
                   f"COALESCE(bit_or(CASE WHEN m.facet_type='context' THEN nb.bitval END),0)::BIGINT context_mask, "
                   f"COALESCE(bit_or(CASE WHEN m.facet_type='object_type' THEN nb.bitval END),0)::BIGINT object_type_mask "
                   f"FROM {M} m JOIN nb ON nb.facet_type=m.facet_type AND nb.concept_uri=m.concept_uri GROUP BY m.pid")
            fil = f"SELECT pid, material_mask, context_mask, object_type_mask FROM {X}"
            mm = scalar(f"SELECT (SELECT COUNT(*) FROM (({ref}) EXCEPT ({fil}))) + (SELECT COUNT(*) FROM (({fil}) EXCEPT ({ref})))")
            check("masks == re-derived from membership+node_bits", mm == 0, f"{mm} mask rows disagree")
            # CROSS-CHECK the actual filter semantics on a real node per dim: the
            # bitwise predicate must return the SAME pid set as the membership
            # subquery. Proves the masks are usable as a drop-in, not just equal blobs.
            for dim in ("material", "context", "object_type"):
                node = scalar(f"SELECT concept_uri FROM {M} WHERE facet_type='{dim}' "
                              f"GROUP BY 1 ORDER BY COUNT(*) DESC, 1 LIMIT 1")
                if node is None:
                    continue
                bitval = scalar(f"SELECT (1::BIGINT << bit_index) FROM {NB} WHERE facet_type='{dim}' AND concept_uri='{node}'")
                col = f"{dim}_mask"
                d = scalar(f"""WITH a AS (SELECT pid FROM {M} WHERE facet_type='{dim}' AND concept_uri='{node}'),
                                    b AS (SELECT pid FROM {X} WHERE ({col} & {bitval})<>0)
                    SELECT (SELECT COUNT(*) FROM (SELECT * FROM a EXCEPT SELECT * FROM b))
                         + (SELECT COUNT(*) FROM (SELECT * FROM b EXCEPT SELECT * FROM a))""")
                check(f"masks filter == membership ({dim})", d == 0, f"{d} pids differ for a real {dim} node")

    # --- #305/#306 complete per-pid facet index (sample_facet_index) ---
    # The multi-filter global-view count path scans THIS file. It must cover the
    # ENTIRE located universe (facets_v2 = samp_geo), carry the correct source per
    # pid, zero-mask the no-membership pids (#306), and be bit-identical to
    # sample_facet_masks for pids that DO have membership — otherwise counts drift.
    if index:
        IX = f"read_parquet('{index}')"
        # schema/types contract (the explorer reads these columns positionally-ish)
        ix_sch = [(r[0], r[1]) for r in con.sql(f"DESCRIBE SELECT * FROM {IX}").fetchall()]
        EXP_IX = [("pid", "VARCHAR"), ("source", "VARCHAR"),
                  ("material_mask", "BIGINT"), ("context_mask", "BIGINT"),
                  ("object_type_mask", "BIGINT"), ("build_id", "VARCHAR"),
                  ("schema_version", "INTEGER")]
        check("index schema matches contract", ix_sch == EXP_IX, f"got {ix_sch}")
        # one row per pid
        ixdup = scalar(f"SELECT COUNT(*) FROM (SELECT pid FROM {IX} GROUP BY pid HAVING COUNT(*)>1)")
        check("index: one row per pid", ixdup == 0, f"{ixdup} duplicate pids in index")
        # COMPLETENESS (#306): index pid SET == facets_v2 pid SET (the located universe).
        # This is the whole point — masks omits no-membership located pids; the index
        # must not. A symmetric set-diff catches both missing and extra pids.
        ix_diff = scalar(f"""SELECT
            (SELECT COUNT(*) FROM (SELECT pid FROM {F} EXCEPT SELECT pid FROM {IX})) +
            (SELECT COUNT(*) FROM (SELECT pid FROM {IX} EXCEPT SELECT pid FROM {F}))""")
        check("index.pid == facets_v2.pid (complete located universe, #306)", ix_diff == 0,
              f"{ix_diff} pids differ between index and facets_v2")
        # SOURCE equality: index.source must equal facets_v2.source for every pid
        # (IS NOT DISTINCT FROM so NULL==NULL). A source-value drift is exactly what
        # the coverage half of build_id is meant to catch — assert it directly too.
        src_bad = scalar(f"""SELECT COUNT(*) FROM {IX} i JOIN {F} f ON i.pid=f.pid
            WHERE i.source IS DISTINCT FROM f.source""")
        check("index.source == facets_v2.source", src_bad == 0, f"{src_bad} pids with mismatched source")
        # single build_id, structured "<membership_id>:<coverage_id>"
        ix_bids = scalar(f"SELECT COUNT(DISTINCT build_id) FROM {IX}")
        check("index: single build_id", ix_bids == 1, f"{ix_bids} distinct build_ids (want 1)")
        ix_bid_fmt = scalar(f"SELECT COUNT(*) FROM {IX} WHERE build_id NOT LIKE '%:%'")
        check("index: build_id is '<membership>:<coverage>'", ix_bid_fmt == 0,
              "build_id(s) missing the ':' coverage separator")
        # single schema_version (sanity — the explorer keys behavior off it)
        ix_sv = scalar(f"SELECT COUNT(DISTINCT schema_version) FROM {IX}")
        check("index: single schema_version", ix_sv == 1, f"{ix_sv} distinct schema_versions")
        if nodebits and ix_bids == 1:
            # the membership half of the index build_id MUST equal node_bits.build_id
            # so the mask bits are interpreted under the SAME assignment (else counts
            # are computed against a stale/foreign bit layout — silently wrong).
            nb_bid = scalar(f"SELECT COUNT(DISTINCT build_id) FROM read_parquet('{nodebits}')")
            if nb_bid == 1:
                membership_half_matches = scalar(
                    f"SELECT (SELECT split_part(MIN(build_id), ':', 1) FROM {IX}) "
                    f"= (SELECT MIN(build_id) FROM read_parquet('{nodebits}'))")
                check("index build_id membership-half == node_bits build_id",
                      bool(membership_half_matches),
                      "index masks would be read under a different bit assignment than node_bits")
        if masks:
            MK = f"read_parquet('{masks}')"
            # For pids that ALSO appear in masks (i.e. have membership), the three
            # mask columns must be byte-identical — the index is a superset, not a
            # re-computation that could drift.
            mk_diff = scalar(f"""SELECT COUNT(*) FROM {IX} i JOIN {MK} m ON i.pid=m.pid
                WHERE i.material_mask    IS DISTINCT FROM m.material_mask
                   OR i.context_mask     IS DISTINCT FROM m.context_mask
                   OR i.object_type_mask IS DISTINCT FROM m.object_type_mask""")
            check("index masks == sample_facet_masks (shared pids)", mk_diff == 0,
                  f"{mk_diff} shared pids with differing masks")
            # The ONLY pids allowed to differ between the two files are the
            # no-membership located pids (#306): present in index, absent from masks,
            # and they MUST be zero-masked. Verify (a) the extra pids are exactly the
            # zero-mask ones and (b) none are in masks.
            extra_nonzero = scalar(f"""SELECT COUNT(*) FROM {IX} i
                WHERE NOT EXISTS (SELECT 1 FROM {MK} m WHERE m.pid=i.pid)
                  AND (i.material_mask <> 0 OR i.context_mask <> 0 OR i.object_type_mask <> 0)""")
            check("index: no-membership extra pids are zero-masked (#306)", extra_nonzero == 0,
                  f"{extra_nonzero} index-only pids carry a non-zero mask (should be 0)")
        elif mem:
            # No masks file to diff against, but we can still assert the #306 invariant
            # directly off membership: every index pid NOT in membership is zero-masked.
            M = f"read_parquet('{mem}')"
            extra_nonzero = scalar(f"""SELECT COUNT(*) FROM {IX} i
                WHERE NOT EXISTS (SELECT 1 FROM {M} m WHERE m.pid=i.pid)
                  AND (i.material_mask <> 0 OR i.context_mask <> 0 OR i.object_type_mask <> 0)""")
            check("index: no-membership pids zero-masked (#306, vs membership)", extra_nonzero == 0,
                  f"{extra_nonzero} no-membership pids carry a non-zero mask")

    print(f"\n{'CHECK':<44} {'RESULT':<6} DETAIL\n" + "-" * 90)
    ok = True
    for name, passed, detail in R:
        ok = ok and passed
        print(f"{name:<44} {'PASS' if passed else 'FAIL':<6} {detail}")
    print("-" * 90)
    for line in info:
        print("  info:", line)
    print("\n" + ("ALL CHECKS PASS" if ok else "FAILURES PRESENT"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
