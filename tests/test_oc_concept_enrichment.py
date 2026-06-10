"""Fast, AI-free fixture tests for the OC concept enrichment (#272, fixes #260).

Builds tiny synthetic src-wide + oc-wide parquet pairs, runs the real
enrichment script + independent validator against them, and asserts the
contract — especially the production cases:
  - OC wins UNCONDITIONALLY (incl. OC root-only replacing src "specifics")
  - array ORDER preserved (frontend picks first non-root by order)
  - concepts missing from src are minted deterministically (#260's
    otheranthropogenicmaterial was absent from the frozen export entirely)
  - non-OC rows and non-overlay columns byte-identical
  - determinism: same inputs -> bit-identical output
  - validator FAILS on tampered output (overlay reverted; concept row dropped)
  - hard failure on duplicate OC pids / unresolved OC concept refs

Run: pytest tests/test_oc_concept_enrichment.py -q   (needs: duckdb)
"""
import hashlib
import json
import os
import subprocess
import sys

import duckdb
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ENRICH = os.path.join(REPO, "scripts", "enrich_wide_with_oc_concepts.py")
VALIDATE = os.path.join(REPO, "scripts", "validate_oc_concept_enrichment.py")

MAT = "https://w3id.org/isample/vocabulary/material/1.0/"
OBJ = "https://w3id.org/isample/vocabulary/materialsampleobjecttype/1.0/"
ROOT = MAT + "material"

# ---- src wide fixture -------------------------------------------------------
# concepts present in src (row_id, uri). NOTE: 'otheranthropogenicmaterial'
# is deliberately ABSENT (mirrors the frozen export).
SRC_CONCEPTS = [
    (101, ROOT),
    (102, MAT + "anthropogenicmetal"),
    (103, MAT + "rock"),
    (104, MAT + "biogenicnonorganicmaterial"),
    (105, OBJ + "artifact"),
    (106, OBJ + "othersolidobject"),
]
# (row_id, pid, mat_ids, obj_ids) — src MaterialSampleRecords
SRC_SAMPLES = [
    # the #260 shape: ceramic with the junk trio; OC will correct it
    (1, "ark:/28722/k2p55x96j", [102, 104, 103], [105]),
    # OC will replace specifics with ROOT-only (unconditional-win case)
    (2, "ark:/28722/rootonly", [103, 104], [105]),
    # OC sample whose URI list ORDER differs from src order
    (3, "ark:/28722/order", [103, 102], [106]),
    # NOT in OC -> must remain byte-identical
    (4, "igsn:NONOC1", [103], [106]),
]
# a non-MSR entity row that shares NOTHING with the overlay -> untouched
SRC_OTHER = [(50, "event-1", "SamplingEvent")]

# ---- oc wide fixture --------------------------------------------------------
OC_CONCEPTS = [
    (9001, MAT + "otheranthropogenicmaterial", "Other anthropogenic material",
     "iSamples Materials Vocabulary", MAT + "materialsvocabulary"),
    (9002, ROOT, "Material", "iSamples Materials Vocabulary", MAT + "materialsvocabulary"),
    (9003, MAT + "rock", "Rock", "iSamples Materials Vocabulary", MAT + "materialsvocabulary"),
    (9004, OBJ + "artifact", "Artifact", None, None),
    (9005, MAT + "organicmaterial", "Organic material", None, None),
]
# (pid, mat_ids, obj_ids)
OC_SAMPLES = [
    ("ark:/28722/k2p55x96j", [9001], [9004]),            # the #260 correction
    ("ark:/28722/rootonly", [9002], [9004]),             # OC root-only wins
    ("ark:/28722/order", [9003, 9001, 9005], [9004]),    # order must survive
    ("ark:/28722/newrecord", [9001], [9004]),            # NOT in src -> not ingested
]

SRC_NULL_COLS = [  # (name, sqltype) — non-overlay columns carried in the fixture
    ("label", "VARCHAR"), ("description", "VARCHAR"), ("thumbnail_url", "VARCHAR"),
    ("scheme_name", "VARCHAR"), ("scheme_uri", "VARCHAR"),
    ("p__has_context_category", "BIGINT[]"), ("p__keywords", "BIGINT[]"),
]


def _arr(xs, t="BIGINT[]"):
    return f"NULL::{t}" if xs is None else "[" + ",".join(str(x) for x in xs) + f"]::{t}"


def _null_cols(overrides=None):
    o = overrides or {}
    return ", ".join(
        f"{o[c]} AS {c}" if c in o else f"NULL::{t} AS {c}" for c, t in SRC_NULL_COLS)


def build_src(path):
    con = duckdb.connect()
    rows = []
    for rid, uri in SRC_CONCEPTS:
        rows.append(
            f"SELECT {rid}::BIGINT AS row_id, '{uri}' AS pid, 'IdentifiedConcept' AS otype, "
            f"NULL::VARCHAR AS n, NULL::BIGINT[] AS p__has_material_category, "
            f"NULL::BIGINT[] AS p__has_sample_object_type, "
            + _null_cols({"label": f"'{uri}'"}))
    for rid, pid, mats, objs in SRC_SAMPLES:
        rows.append(
            f"SELECT {rid}::BIGINT, '{pid}', 'MaterialSampleRecord', 'TEST', "
            f"{_arr(mats)}, {_arr(objs)}, "
            + _null_cols({"label": f"'label {pid}'", "description": f"'desc {pid}'",
                          "thumbnail_url": f"'https://t/{rid}.jpg'",
                          "p__keywords": "[101]::BIGINT[]"}))
    for rid, pid, otype in SRC_OTHER:
        rows.append(
            f"SELECT {rid}::BIGINT, '{pid}', '{otype}', NULL, "
            f"NULL::BIGINT[], NULL::BIGINT[], " + _null_cols())
    con.execute(f"COPY ({' UNION ALL '.join(rows)}) TO '{path}' (FORMAT PARQUET)")
    con.close()


def build_oc(path, samples=None, concepts=None, extra_msr_sql=None):
    con = duckdb.connect()
    rows = []
    for rid, uri, label, sname, suri in (concepts or OC_CONCEPTS):
        rows.append(
            f"SELECT {rid}::INTEGER AS row_id, '{uri}' AS pid, 'IdentifiedConcept' AS otype, "
            f"{'NULL' if label is None else repr(label)}::VARCHAR AS label, "
            f"{'NULL' if sname is None else repr(sname)}::VARCHAR AS scheme_name, "
            f"{'NULL' if suri is None else repr(suri)}::VARCHAR AS scheme_uri, "
            f"NULL::INTEGER[] AS p__has_material_category, NULL::INTEGER[] AS p__has_sample_object_type")
    for pid, mats, objs in (samples or OC_SAMPLES):
        rows.append(
            f"SELECT NULL::INTEGER, '{pid}', 'MaterialSampleRecord', NULL::VARCHAR, "
            f"NULL::VARCHAR, NULL::VARCHAR, {_arr(mats, 'INTEGER[]')}, {_arr(objs, 'INTEGER[]')}")
    if extra_msr_sql:
        rows.append(extra_msr_sql)
    con.execute(f"COPY ({' UNION ALL '.join(rows)}) TO '{path}' (FORMAT PARQUET)")
    con.close()


def run_enrich(src, oc, out, no_manifest=False):
    cmd = [sys.executable, ENRICH, "--src", src, "--oc-wide", oc, "--out", out]
    if no_manifest:
        cmd.append("--no-manifest")
    return subprocess.run(cmd, capture_output=True, text=True)


def run_validate(src, oc, out):
    return subprocess.run(
        [sys.executable, VALIDATE, "--src", src, "--oc-wide", oc, "--out", out],
        capture_output=True, text=True)


def mats_of(out, pid):
    con = duckdb.connect()
    r = con.sql(f"""
        SELECT (SELECT list(c.pid ORDER BY u.ord)
                FROM UNNEST(s.p__has_material_category) WITH ORDINALITY u(rid, ord)
                JOIN read_parquet('{out}') c ON c.row_id=u.rid AND c.otype='IdentifiedConcept')
        FROM read_parquet('{out}') s
        WHERE s.pid='{pid}' AND s.otype='MaterialSampleRecord'""").fetchone()
    con.close()
    return r[0] if r else None


@pytest.fixture
def pair(tmp_path):
    src, oc, out = (str(tmp_path / n) for n in ("src.parquet", "oc.parquet", "out.parquet"))
    build_src(src)
    build_oc(oc)
    return src, oc, out


def test_overlay_corrects_260_shape(pair):
    src, oc, out = pair
    r = run_enrich(src, oc, out)
    assert r.returncode == 0, r.stderr + r.stdout
    assert mats_of(out, "ark:/28722/k2p55x96j") == [MAT + "otheranthropogenicmaterial"]


def test_oc_root_only_wins_unconditionally(pair):
    src, oc, out = pair
    assert run_enrich(src, oc, out).returncode == 0
    # src had [rock, biogenic...]; OC says root-only -> root-only WINS (#272 policy)
    assert mats_of(out, "ark:/28722/rootonly") == [ROOT]


def test_uri_order_preserved(pair):
    src, oc, out = pair
    assert run_enrich(src, oc, out).returncode == 0
    assert mats_of(out, "ark:/28722/order") == [
        MAT + "rock", MAT + "otheranthropogenicmaterial", MAT + "organicmaterial"]


def test_non_oc_rows_untouched_and_new_records_not_ingested(pair):
    src, oc, out = pair
    assert run_enrich(src, oc, out).returncode == 0
    con = duckdb.connect()
    # non-OC sample + SamplingEvent rows byte-identical
    diff = con.sql(f"""
        SELECT (SELECT COUNT(*) FROM ((SELECT * FROM read_parquet('{src}') WHERE pid IN ('igsn:NONOC1','event-1'))
                EXCEPT ALL (SELECT * FROM read_parquet('{out}') WHERE pid IN ('igsn:NONOC1','event-1'))))
             + (SELECT COUNT(*) FROM ((SELECT * FROM read_parquet('{out}') WHERE pid IN ('igsn:NONOC1','event-1'))
                EXCEPT ALL (SELECT * FROM read_parquet('{src}') WHERE pid IN ('igsn:NONOC1','event-1'))))
    """).fetchone()[0]
    assert diff == 0
    # OC-only sample NOT ingested
    n = con.sql(f"SELECT COUNT(*) FROM read_parquet('{out}') WHERE pid='ark:/28722/newrecord'").fetchone()[0]
    assert n == 0
    con.close()


def test_minted_concepts_deterministic_ids_and_metadata(pair):
    src, oc, out = pair
    assert run_enrich(src, oc, out).returncode == 0
    con = duckdb.connect()
    minted = con.sql(f"""
        SELECT row_id, pid, label, scheme_name FROM read_parquet('{out}')
        WHERE row_id > 106 ORDER BY row_id""").fetchall()
    con.close()
    # missing URIs sorted: organicmaterial < otheranthropogenicmaterial
    assert [m[1] for m in minted] == [MAT + "organicmaterial", MAT + "otheranthropogenicmaterial"]
    assert [m[0] for m in minted] == [107, 108]
    assert minted[1][2] == "Other anthropogenic material"
    assert minted[1][3] == "iSamples Materials Vocabulary"


def test_determinism_bit_identical(pair):
    src, oc, out = pair
    out2 = out.replace("out.parquet", "out2.parquet")
    assert run_enrich(src, oc, out, no_manifest=True).returncode == 0
    assert run_enrich(src, oc, out2, no_manifest=True).returncode == 0
    h = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
    assert h(out) == h(out2)


def test_manifest_written_with_counts(pair):
    src, oc, out = pair
    assert run_enrich(src, oc, out).returncode == 0
    man = json.load(open(out + ".manifest.json"))
    c = man["counts"]
    assert c["overlay_pids"] == 4 and c["overlay_matched"] == 3
    assert c["overlay_unmatched_new_oc_records"] == 1
    assert c["minted_concepts"] == 2
    assert man["inputs"]["src"]["sha256"] and man["output"]["sha256"]


def test_validator_passes_on_good_output(pair):
    src, oc, out = pair
    assert run_enrich(src, oc, out).returncode == 0
    r = run_validate(src, oc, out)
    assert r.returncode == 0, r.stdout + r.stderr


def test_validator_fails_on_reverted_overlay(pair, tmp_path):
    """Adversary: a 'rebuild' that silently kept the src junk values must FAIL."""
    src, oc, out = pair
    assert run_enrich(src, oc, out).returncode == 0
    tampered = str(tmp_path / "tampered.parquet")
    con = duckdb.connect()
    con.execute(f"""
        COPY (
          SELECT o.* REPLACE (
            (CASE WHEN o.pid='ark:/28722/k2p55x96j' AND o.otype='MaterialSampleRecord'
             THEN [102,104,103]::BIGINT[] ELSE o.p__has_material_category END) AS p__has_material_category)
          FROM read_parquet('{out}') o ORDER BY row_id
        ) TO '{tampered}' (FORMAT PARQUET, COMPRESSION ZSTD)""")
    con.close()
    r = run_validate(src, oc, tampered)
    assert r.returncode != 0
    assert "overlay applied" in r.stdout


def test_validator_fails_on_dropped_minted_concept(pair, tmp_path):
    src, oc, out = pair
    assert run_enrich(src, oc, out).returncode == 0
    tampered = str(tmp_path / "dropped.parquet")
    con = duckdb.connect()
    con.execute(f"""COPY (SELECT * FROM read_parquet('{out}') WHERE row_id IS NULL OR row_id <> 108
                   ORDER BY row_id) TO '{tampered}' (FORMAT PARQUET, COMPRESSION ZSTD)""")
    con.close()
    r = run_validate(src, oc, tampered)
    assert r.returncode != 0


def test_hard_fail_on_duplicate_oc_pids(pair):
    src, oc, out = pair
    dup_oc = oc.replace("oc.parquet", "oc_dup.parquet")
    build_oc(dup_oc, samples=OC_SAMPLES + [("ark:/28722/k2p55x96j", [9003], [9004])])
    r = run_enrich(src, dup_oc, out)
    assert r.returncode != 0
    assert "duplicate" in (r.stderr + r.stdout)
    assert not os.path.exists(out)


def test_hard_fail_on_unresolved_oc_concept_ref(pair):
    src, oc, out = pair
    bad_oc = oc.replace("oc.parquet", "oc_bad.parquet")
    build_oc(bad_oc, samples=[("ark:/28722/k2p55x96j", [99999], [9004])])
    r = run_enrich(src, bad_oc, out)
    assert r.returncode != 0
    assert "resolve" in (r.stderr + r.stdout)
    assert not os.path.exists(out)


def test_validator_fails_on_nulled_overlay_columns(pair, tmp_path):
    """Codex round-1 BLOCKER: keep the OC URI lists but wreck a popup-facing
    column (label) on overlay rows — must FAIL, not pass as 'overlay ok'."""
    src, oc, out = pair
    assert run_enrich(src, oc, out).returncode == 0
    tampered = str(tmp_path / "nulled.parquet")
    con = duckdb.connect()
    con.execute(f"""
        COPY (
          SELECT o.* REPLACE (
            (CASE WHEN o.pid LIKE 'ark:/28722/%' AND o.otype='MaterialSampleRecord'
             THEN NULL ELSE o.label END) AS label)
          FROM read_parquet('{out}') o ORDER BY row_id
        ) TO '{tampered}' (FORMAT PARQUET, COMPRESSION ZSTD)""")
    con.close()
    r = run_validate(src, oc, tampered)
    assert r.returncode != 0
    assert "non-replaced columns identical" in r.stdout


def test_validator_fails_on_duplicated_pid_replacing_sentinel(pair, tmp_path):
    """Codex round-1 BLOCKER: replace the sentinel row with a duplicate of
    another overlay pid (unique row_id) — counts stay equal; sets must not."""
    src, oc, out = pair
    assert run_enrich(src, oc, out).returncode == 0
    tampered = str(tmp_path / "dup_pid.parquet")
    con = duckdb.connect()
    # drop the sentinel row entirely; insert a full clone of another overlay
    # row (correct arrays!) reusing the sentinel's row_id. Counts all balance;
    # only SET checks notice.
    con.execute(f"""
        COPY (
          SELECT * FROM read_parquet('{out}')
          WHERE NOT (pid='ark:/28722/k2p55x96j' AND otype='MaterialSampleRecord')
          UNION ALL
          SELECT o.* REPLACE (1::BIGINT AS row_id)
          FROM read_parquet('{out}') o
          WHERE o.pid='ark:/28722/order' AND o.otype='MaterialSampleRecord'
          ORDER BY row_id
        ) TO '{tampered}' (FORMAT PARQUET, COMPRESSION ZSTD)""")
    con.close()
    r = run_validate(src, oc, tampered)
    assert r.returncode != 0


def test_empty_oc_array_normalizes_to_null(pair, tmp_path):
    """Documented normalization: OC `[]` -> NULL in the output (pqg issue #8
    convention). All real OC rows are non-empty; this pins the edge behavior."""
    src, oc, out = pair
    empty_oc = str(tmp_path / "oc_empty.parquet")
    build_oc(empty_oc, samples=[("ark:/28722/k2p55x96j", [], [9004])])
    assert run_enrich(src, empty_oc, out).returncode == 0
    con = duckdb.connect()
    mats = con.sql(f"""SELECT p__has_material_category FROM read_parquet('{out}')
        WHERE pid='ark:/28722/k2p55x96j' AND otype='MaterialSampleRecord'""").fetchone()[0]
    con.close()
    assert mats is None


def test_refuses_to_overwrite_input(pair):
    src, oc, _ = pair
    r = run_enrich(src, oc, src)
    assert r.returncode != 0
    assert "overwrite" in (r.stderr + r.stdout)
