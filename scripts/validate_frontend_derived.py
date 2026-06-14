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
                  "h3_res8::UBIGINT AS h3_res8, h3_h3_to_string(h3_res8) AS h3_res8_hex, "
                  "place_name::VARCHAR AS pn FROM samp_geo")
        file_ml = (f"SELECT pid, label, source, latitude, longitude, result_time, h3_res8, h3_res8_hex, "
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
