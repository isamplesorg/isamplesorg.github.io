#!/usr/bin/env python3
"""Independent trust gate for the OC concept enrichment (#272).

Validates an enriched wide AGAINST ITS INPUTS — it re-derives the expected
result from (src, oc-wide) with its own SQL (deliberately NOT importing the
enrichment script) and asserts the written output matches. Exits non-zero on
any failure so it can gate a publish.

What a wrong output looks like and which check catches it:
  - an OC pid kept the frozen export's junk materials  -> overlay-applied
  - URI list order scrambled (changes facet selection) -> overlay-applied (order-sensitive)
  - a non-OC row was modified                          -> non-overlay untouched
  - rows dropped/duplicated                            -> row accounting / grain
  - minted concept missing, wrong id, or extra rows    -> minted concepts exact
  - #260 ceramic still "anthropogenic metal"           -> sentinel

Usage:
  python scripts/validate_oc_concept_enrichment.py \
      --src isamples_202604_wide.parquet \
      --oc-wide oc_isamples_pqg_wide_2026-06-09.parquet \
      --out isamples_202606_wide.parquet
"""
import argparse
import hashlib
import json
import os
import sys

import duckdb

SENTINEL_PID = "ark:/28722/k2p55x96j"  # #260: ceramic, must carry otheranthropogenicmaterial
SENTINEL_MATERIAL = "https://w3id.org/isample/vocabulary/material/1.0/otheranthropogenicmaterial"
DIMS = [("p__has_material_category", "mat"), ("p__has_sample_object_type", "obj")]


def sha256_file(path, _b=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_b), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--oc-wide", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    con = duckdb.connect()
    SRC = f"read_parquet('{a.src}')"
    OC = f"read_parquet('{a.oc_wide}')"
    OUT = f"read_parquet('{a.out}')"

    R, info = [], []
    def check(name, passed, detail=""):
        R.append((name, bool(passed), detail))
    def scalar(sql):
        return con.sql(sql).fetchone()[0]

    # ---- input integrity: duplicate OC concept row_ids would fan one
    # reference into several URIs through every resolve join below (Codex
    # round-2) — reject the inputs before deriving expectations from them.
    n_dup_oc_crid = scalar(
        f"SELECT COUNT(*) FROM (SELECT row_id FROM {OC} WHERE otype='IdentifiedConcept' "
        f"AND row_id IS NOT NULL GROUP BY row_id HAVING COUNT(*)>1)")
    check("OC concept row_ids unique (input integrity)", n_dup_oc_crid == 0,
          f"{n_dup_oc_crid} duplicated OC IdentifiedConcept row_ids")
    n_dup_oc_pid = scalar(
        f"SELECT COUNT(*) FROM (SELECT pid FROM {OC} WHERE otype='MaterialSampleRecord' "
        f"GROUP BY pid HAVING COUNT(*)>1)")
    check("OC MSR pids unique (input integrity)", n_dup_oc_pid == 0,
          f"{n_dup_oc_pid} duplicated OC MaterialSampleRecord pids")
    # unresolved OC concept refs: the inner joins below would silently DROP
    # them from the expectation (Codex round-3) — the gate must reject the
    # input the same way the enricher does, since it may run standalone.
    n_unresolved = scalar(f"""
        SELECT COUNT(*) FROM (
          SELECT u.rid FROM {OC} s, UNNEST(s.p__has_material_category) AS u(rid)
          WHERE s.otype='MaterialSampleRecord'
          UNION ALL
          SELECT u.rid FROM {OC} s, UNNEST(s.p__has_sample_object_type) AS u(rid)
          WHERE s.otype='MaterialSampleRecord') refs
        LEFT JOIN (SELECT row_id FROM {OC} WHERE otype='IdentifiedConcept') c
          ON c.row_id = refs.rid
        WHERE c.row_id IS NULL""")
    check("all OC concept refs resolve (input integrity)", n_unresolved == 0,
          f"{n_unresolved} dangling OC concept references")

    # ---- expected per-pid ORDERED URI lists from OC (independent derivation)
    con.execute(f"""
    CREATE TEMP TABLE exp_oc AS
      SELECT s.pid,
        (SELECT list(c.pid ORDER BY u.ord, c.pid)
           FROM UNNEST(s.p__has_material_category) WITH ORDINALITY AS u(rid, ord)
           JOIN {OC} c ON c.row_id=u.rid AND c.otype='IdentifiedConcept') AS mat_uris,
        (SELECT list(c.pid ORDER BY u.ord, c.pid)
           FROM UNNEST(s.p__has_sample_object_type) WITH ORDINALITY AS u(rid, ord)
           JOIN {OC} c ON c.row_id=u.rid AND c.otype='IdentifiedConcept') AS obj_uris
      FROM {OC} s WHERE s.otype='MaterialSampleRecord';
    """)

    # ---- actual per-pid URI lists in OUT (resolve out's row_ids -> out's concepts)
    con.execute(f"""
    CREATE TEMP TABLE out_concepts AS
      SELECT row_id, pid AS uri FROM {OUT} WHERE otype='IdentifiedConcept';
    CREATE TEMP TABLE act_out AS
      SELECT s.pid,
        (SELECT list(c.uri ORDER BY u.ord, c.uri)
           FROM UNNEST(s.p__has_material_category) WITH ORDINALITY AS u(rid, ord)
           JOIN out_concepts c ON c.row_id=u.rid) AS mat_uris,
        (SELECT list(c.uri ORDER BY u.ord, c.uri)
           FROM UNNEST(s.p__has_sample_object_type) WITH ORDINALITY AS u(rid, ord)
           JOIN out_concepts c ON c.row_id=u.rid) AS obj_uris
      FROM {OUT} s
      WHERE s.otype='MaterialSampleRecord' AND s.pid IN (SELECT pid FROM exp_oc);
    """)

    # --- 1. overlay applied, order-sensitive, both dims; pid SET equality ----
    # (Codex round-1 BLOCKER: an inner join + count let a duplicated-pid /
    # dropped-sentinel output pass. Use set EXCEPTs, not counts.)
    bad_overlay = scalar("""
        SELECT COUNT(*) FROM exp_oc e JOIN act_out o ON o.pid=e.pid
        WHERE e.mat_uris IS DISTINCT FROM o.mat_uris
           OR e.obj_uris IS DISTINCT FROM o.obj_uris""")
    check("overlay applied (OC == OUT, ordered, both dims)", bad_overlay == 0,
          f"{bad_overlay} overlay pids differ from OC expectation")
    pid_set_diff = scalar(f"""
      WITH expected AS (
        SELECT e.pid FROM exp_oc e
        JOIN {SRC} s ON s.pid=e.pid AND s.otype='MaterialSampleRecord')
      SELECT (SELECT COUNT(*) FROM (SELECT pid FROM expected EXCEPT SELECT pid FROM act_out))
           + (SELECT COUNT(*) FROM (SELECT pid FROM act_out EXCEPT SELECT pid FROM expected))""")
    check("overlay pid SET == (OC ∩ src) pid SET", pid_set_diff == 0,
          f"{pid_set_diff} pids differ between expected and actual overlay sets")
    dup_overlay_pid = scalar(
        "SELECT COUNT(*) FROM (SELECT pid FROM act_out GROUP BY pid HAVING COUNT(*)>1)")
    check("overlay pids distinct in OUT", dup_overlay_pid == 0,
          f"{dup_overlay_pid} duplicated overlay pids in OUT")

    # --- 2. ALL src rows present + ALL non-replaced columns identical --------
    # (Codex round-1 BLOCKER: comparing only non-overlay rows let an output
    # null label/thumbnail/geometry on overlay rows and still pass. Compare
    # EVERY src row on EVERY column except the two replaced arrays — keyed by
    # row_id with row hashes, not full-table EXCEPT, so it scales to 20.7M.)
    keep_cols = [r[0] for r in con.sql(f"DESCRIBE SELECT * FROM {SRC}").fetchall()
                 if r[0] not in ("p__has_material_category", "p__has_sample_object_type")]
    keep_expr = ", ".join(keep_cols)
    missing_rows = scalar(f"""
        SELECT COUNT(*) FROM {SRC} s LEFT JOIN {OUT} o ON o.row_id = s.row_id
        WHERE o.row_id IS NULL""")
    check("every src row_id present in OUT", missing_rows == 0, f"{missing_rows} src rows missing")
    col_diff = scalar(f"""
        WITH sh AS (SELECT row_id, hash(ROW({keep_expr})) AS h FROM {SRC}),
             oh AS (SELECT row_id, hash(ROW({keep_expr})) AS h FROM {OUT})
        SELECT COUNT(*) FROM sh JOIN oh ON oh.row_id = sh.row_id WHERE sh.h <> oh.h""")
    check("all non-replaced columns identical (every src row)", col_diff == 0,
          f"{col_diff} rows differ outside the two replaced arrays")
    # the two replaced arrays: must equal src for everything that is NOT an
    # overlay MaterialSampleRecord (overlay rows are covered by check 1).
    arr_diff = scalar(f"""
        SELECT COUNT(*) FROM {SRC} s JOIN {OUT} o ON o.row_id = s.row_id
        WHERE NOT (s.otype='MaterialSampleRecord' AND s.pid IN (SELECT pid FROM exp_oc))
          AND (s.p__has_material_category IS DISTINCT FROM o.p__has_material_category
            OR s.p__has_sample_object_type IS DISTINCT FROM o.p__has_sample_object_type)""")
    check("replaced arrays untouched outside the overlay", arr_diff == 0,
          f"{arr_diff} non-overlay rows had their concept arrays modified")

    # --- 3. minted concepts: EXACT full-row expectation, re-derived ----------
    # (Codex round-2 MAJOR: URI-set + metadata spot checks let shifted row_ids
    # and smuggled column values pass. Re-derive the complete expected minted
    # rows — deterministic ids max(src)+rank(uri), every other column NULL
    # except pid/otype/label/scheme — and demand exact equality, all columns.)
    max_src = scalar(f"SELECT COALESCE(MAX(row_id),0) FROM {SRC}")
    src_schema = [(r[0], r[1]) for r in con.sql(f"DESCRIBE SELECT * FROM {SRC}").fetchall()]
    exp_minted_cols = ", ".join(
        {
            "row_id": f"({max_src} + ROW_NUMBER() OVER (ORDER BY uri))::{dict(src_schema)['row_id']} AS row_id",
            "pid": "uri AS pid",
            "otype": "'IdentifiedConcept' AS otype",
            "label": "label",
            "scheme_name": "scheme_name",
            "scheme_uri": "scheme_uri",
        }.get(c, f"NULL::{t} AS {c}")
        for c, t in src_schema)
    con.execute(f"""
    CREATE TEMP TABLE expected_minted AS
      WITH oc_uris AS (
        SELECT DISTINCT unnest(mat_uris) AS uri FROM exp_oc
        UNION SELECT DISTINCT unnest(obj_uris) FROM exp_oc),
      missing AS (
        -- NOT EXISTS, not NOT IN: a NULL-pid src concept would make NOT IN
        -- evaluate UNKNOWN and silently empty this set (Codex round-3 MINOR)
        SELECT uri FROM oc_uris u
        WHERE u.uri IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM {SRC} s
                          WHERE s.otype='IdentifiedConcept' AND s.pid = u.uri)),
      meta AS (
        SELECT pid AS uri, MIN(label) AS label, MIN(scheme_name) AS scheme_name,
               MIN(scheme_uri) AS scheme_uri
        FROM {OC} WHERE otype='IdentifiedConcept' GROUP BY pid)
      SELECT {exp_minted_cols}
      FROM (SELECT m.uri, t.label, t.scheme_name, t.scheme_uri
            FROM missing m JOIN meta t ON t.uri = m.uri);
    """)
    all_cols = ", ".join(c for c, _ in src_schema)
    minted_exact_diff = scalar(f"""
      SELECT (SELECT COUNT(*) FROM (
                (SELECT {all_cols} FROM expected_minted)
                EXCEPT (SELECT {all_cols} FROM {OUT} WHERE row_id > {max_src})))
           + (SELECT COUNT(*) FROM (
                (SELECT {all_cols} FROM {OUT} WHERE row_id > {max_src})
                EXCEPT (SELECT {all_cols} FROM expected_minted)))""")
    check("minted rows EXACTLY match re-derived expectation (all columns)",
          minted_exact_diff == 0, f"{minted_exact_diff} full-row mismatches among minted rows")

    # --- 4. grain + accounting ----------------------------------------------
    n_src, n_out = scalar(f"SELECT COUNT(*) FROM {SRC}"), scalar(f"SELECT COUNT(*) FROM {OUT}")
    n_minted = scalar(f"SELECT COUNT(*) FROM {OUT} WHERE row_id > {max_src}")
    check("row accounting (out == src + minted)", n_out == n_src + n_minted,
          f"out={n_out:,} src={n_src:,} minted={n_minted}")
    dup = scalar(f"SELECT COUNT(*) FROM (SELECT row_id FROM {OUT} GROUP BY row_id HAVING COUNT(*)>1)")
    check("out row_id unique", dup == 0, f"{dup} duplicate row_ids")

    # --- 5. every referenced concept resolves in OUT -------------------------
    dangling = scalar(f"""
      SELECT COUNT(*) FROM (
        SELECT u.rid FROM {OUT} s, UNNEST(s.p__has_material_category) AS u(rid)
        WHERE s.otype='MaterialSampleRecord'
        UNION ALL
        SELECT u.rid FROM {OUT} s, UNNEST(s.p__has_sample_object_type) AS u(rid)
        WHERE s.otype='MaterialSampleRecord') refs
      LEFT JOIN out_concepts c ON c.row_id = refs.rid
      WHERE c.row_id IS NULL""")
    check("no dangling concept references in OUT", dangling == 0, f"{dangling} dangling refs")

    # --- 6. #260 sentinel ----------------------------------------------------
    # N/A ONLY if the pid is absent from the INPUTS (fixtures). If src+oc both
    # carry it, its absence from the overlay output is a FAILURE, not a skip
    # (Codex round-1: a dropped sentinel row was silently 'N/A').
    in_inputs = scalar(f"""
        SELECT COUNT(*) FROM {SRC} s
        WHERE s.pid='{SENTINEL_PID}' AND s.otype='MaterialSampleRecord'
          AND s.pid IN (SELECT pid FROM exp_oc)""")
    row = con.sql(f"SELECT mat_uris FROM act_out WHERE pid='{SENTINEL_PID}'").fetchone()
    if not in_inputs and row is None:
        info.append(f"sentinel {SENTINEL_PID} not present in inputs (N/A for this dataset)")
    else:
        check(f"sentinel {SENTINEL_PID} == [{SENTINEL_MATERIAL.rsplit('/',1)[1]}]",
              row is not None and row[0] == [SENTINEL_MATERIAL],
              f"got {row[0] if row else 'MISSING ROW'}")

    # --- 7. manifest integrity (if present) ----------------------------------
    mpath = a.out + ".manifest.json"
    if os.path.exists(mpath):
        try:
            man = json.load(open(mpath))
        except Exception as e:
            man = None
            check("manifest parses", False, f"unreadable: {e}")
        if man:
            check("manifest output sha256 matches file",
                  man.get("output", {}).get("sha256") == sha256_file(a.out),
                  "out file does not match its manifest")
            for key, path in (("src", a.src), ("oc_wide", a.oc_wide)):
                msha = man.get("inputs", {}).get(key, {}).get("sha256")
                if msha:
                    check(f"manifest input sha256 matches --{key.replace('_','-')}",
                          msha == sha256_file(path), f"{key} sha mismatch")
    else:
        info.append("no .manifest.json next to --out (manifest verification skipped)")

    print(f"\n{'CHECK':<52} {'RESULT':<6} DETAIL\n" + "-" * 100)
    ok = True
    for name, passed, detail in R:
        ok = ok and passed
        print(f"{name:<52} {'PASS' if passed else 'FAIL':<6} {detail}")
    print("-" * 100)
    for line in info:
        print("  info:", line)
    print("\n" + ("ALL CHECKS PASS" if ok else "FAILURES PRESENT"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
