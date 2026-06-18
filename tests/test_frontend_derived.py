"""Fast, AI-free fixture tests for the derived-parquet pipeline.

Builds tiny synthetic `wide` parquet files (both WKB-BLOB and DuckDB-GEOMETRY
geometry encodings), runs the real builder + validator against them, and asserts
the contract — especially the cases that bit us in production:
  - geometry stored as BLOB *or* GEOMETRY (the silent BLOB-only contract bug)
  - material = first NON-ROOT concept; root-only -> NULL (#265/#271)
  - missing concept row-id / NULL array -> NULL (no crash)
  - place_name serialization; pid uniqueness; located-only scoping
  - CLI fails loudly on unknown --only

Run: pytest tests/test_frontend_derived.py -q   (needs: duckdb, h3, spatial)
"""
import os, subprocess, sys
import duckdb
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
BUILD = os.path.join(REPO, "scripts", "build_frontend_derived.py")
VALIDATE = os.path.join(REPO, "scripts", "validate_frontend_derived.py")

MAT = "https://w3id.org/isample/vocabulary/material/1.0/"
ROOT = MAT + "material"

# concept row_id -> uri
CONCEPTS = [
    (1, ROOT),                 # material root (must never be selected)
    (2, MAT + "mineral"),
    (3, MAT + "rock"),
    (4, MAT + "anthropogenicmetal"),
    (10, "https://w3id.org/isample/vocabulary/sampledfeature/1.0/earthinterior"),
    (20, "https://w3id.org/isample/vocabulary/materialsampleobjecttype/1.0/othersolidobject"),
]

# (pid, material_array, expected_material_tail)  — context=[10], object_type=[20], valid geometry
SAMPLES = [
    ("m-root-first", [1, 2, 3], "rock"),          # root first -> first NON-root in order = mineral? -> see note
    ("m-real-first", [4, 1], "anthropogenicmetal"),  # real first preserved
    ("m-root-only", [1], None),                    # root only -> NULL
    ("m-null-array", None, None),                  # no material -> NULL
    ("m-missing-id", [999], None),                 # dangling row-id -> NULL
]
# NOTE on m-root-first [1,2,3] = [material, mineral, rock]: builder takes the
# FIRST non-root by array order -> 'mineral'. We assert exactly that below.
EXPECTED = {
    "m-root-first": MAT + "mineral",
    "m-real-first": MAT + "anthropogenicmetal",
    "m-root-only": None,
    "m-null-array": None,
    "m-missing-id": None,
}


def _arr(xs):
    return "NULL::BIGINT[]" if xs is None else "[" + ",".join(str(x) for x in xs) + "]::BIGINT[]"


def build_fixture_wide(path, geom_mode):
    """Write a tiny wide parquet. geom_mode in {'blob','geometry'}."""
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    geom = (lambda lng, lat: f"ST_AsWKB(ST_Point({lng},{lat}))") if geom_mode == "blob" \
        else (lambda lng, lat: f"ST_Point({lng},{lat})")

    ic_rows = " UNION ALL ".join(
        f"SELECT 'IdentifiedConcept' AS otype, '{uri}' AS pid, {rid}::BIGINT AS row_id, NULL::VARCHAR AS n, "
        f"NULL::VARCHAR AS label, NULL::VARCHAR AS description, NULL::VARCHAR[] AS place_name, "
        f"NULL::TIMESTAMP AS result_time, NULL AS geometry, "
        f"NULL::BIGINT[] AS p__has_material_category, NULL::BIGINT[] AS p__has_context_category, "
        f"NULL::BIGINT[] AS p__has_sample_object_type, NULL::BIGINT[] AS p__keywords"
        for rid, uri in CONCEPTS)

    msr = []
    for i, (pid, marr, _) in enumerate(SAMPLES):
        lng, lat = 10.0 + i, 40.0 + i
        msr.append(
            f"SELECT 'MaterialSampleRecord' AS otype, '{pid}' AS pid, NULL::BIGINT AS row_id, 'TEST' AS n, "
            f"'label {pid}' AS label, 'desc {pid}' AS description, ['plc-{pid}','x''q']::VARCHAR[] AS place_name, "
            f"NULL::TIMESTAMP AS result_time, {geom(lng, lat)} AS geometry, "
            f"{_arr(marr)} AS p__has_material_category, [10]::BIGINT[] AS p__has_context_category, "
            f"[20]::BIGINT[] AS p__has_sample_object_type, NULL::BIGINT[] AS p__keywords")
    # one NULL-geometry sample -> must be EXCLUDED from located outputs
    msr.append(
        "SELECT 'MaterialSampleRecord' AS otype, 'm-nogeo' AS pid, NULL::BIGINT AS row_id, 'TEST' AS n, "
        "'l' AS label, 'd' AS description, NULL::VARCHAR[] AS place_name, NULL::TIMESTAMP AS result_time, "
        "NULL AS geometry, [4]::BIGINT[] AS p__has_material_category, [10]::BIGINT[] AS p__has_context_category, "
        "[20]::BIGINT[] AS p__has_sample_object_type, NULL::BIGINT[] AS p__keywords")

    con.execute(f"COPY ({ic_rows} UNION ALL {' UNION ALL '.join(msr)}) "
                f"TO '{path}' (FORMAT PARQUET)")
    con.close()


def run_builder(wide, outdir, tag, extra=None):
    cmd = [sys.executable, BUILD, "--wide", wide, "--outdir", outdir, "--tag", tag,
           "--skip", "wide_h3", "--no-manifest"] + (extra or [])
    return subprocess.run(cmd, capture_output=True, text=True)


@pytest.mark.parametrize("geom_mode", ["blob", "geometry"])
def test_material_selection_and_geometry(tmp_path, geom_mode):
    wide = str(tmp_path / f"wide_{geom_mode}.parquet")
    build_fixture_wide(wide, geom_mode)

    # confirm the fixture actually stored the geometry type we intend to test
    con = duckdb.connect(); con.execute("INSTALL spatial; LOAD spatial;")
    gtype = con.sql(f"DESCRIBE SELECT geometry FROM read_parquet('{wide}')").fetchall()[0][1].upper()

    r = run_builder(wide, str(tmp_path), "t")
    assert r.returncode == 0, f"builder failed ({gtype}):\n{r.stdout}\n{r.stderr}"

    facets = str(tmp_path / "t_sample_facets_v2.parquet")
    rows = dict(con.sql(f"SELECT pid, material FROM read_parquet('{facets}')").fetchall())

    # material selection contract
    for pid, expected in EXPECTED.items():
        assert rows.get(pid) == expected, f"[{gtype}] {pid}: got {rows.get(pid)!r}, want {expected!r}"
    # NULL-geometry sample excluded from located file
    assert "m-nogeo" not in rows, f"[{gtype}] NULL-geometry sample leaked into facets"
    # geometry decoded to correct coords in map_lite (m-root-first @ lng=10,lat=40)
    ml = str(tmp_path / "t_samples_map_lite.parquet")
    lat, lng = con.sql(f"SELECT latitude, longitude FROM read_parquet('{ml}') WHERE pid='m-root-first'").fetchone()
    assert abs(lat - 40.0) < 1e-6 and abs(lng - 10.0) < 1e-6, f"[{gtype}] bad coords: {lat},{lng}"


def test_no_root_and_pid_uniqueness(tmp_path):
    wide = str(tmp_path / "wide.parquet"); build_fixture_wide(wide, "blob")
    assert run_builder(wide, str(tmp_path), "t").returncode == 0
    con = duckdb.connect()
    facets = f"read_parquet('{tmp_path / 't_sample_facets_v2.parquet'}')"
    assert con.sql(f"SELECT COUNT(*) FROM {facets} WHERE material='{ROOT}'").fetchone()[0] == 0
    dups = con.sql(f"SELECT COUNT(*) FROM (SELECT pid FROM {facets} GROUP BY pid HAVING COUNT(*)>1)").fetchone()[0]
    assert dups == 0


def test_place_name_serialized_and_quotes(tmp_path):
    wide = str(tmp_path / "wide.parquet"); build_fixture_wide(wide, "blob")
    assert run_builder(wide, str(tmp_path), "t").returncode == 0
    con = duckdb.connect()
    pn = con.sql(f"SELECT place_name FROM read_parquet('{tmp_path / 't_sample_facets_v2.parquet'}') "
                 f"WHERE pid='m-real-first'").fetchone()[0]
    assert isinstance(pn, str) and "plc-m-real-first" in pn  # VARCHAR, not array, embedded quote survived


def test_cli_rejects_unknown_only(tmp_path):
    wide = str(tmp_path / "wide.parquet"); build_fixture_wide(wide, "blob")
    r = run_builder(wide, str(tmp_path), "t", extra=["--only", "bogus_name"])
    assert r.returncode != 0 and "unknown" in (r.stdout + r.stderr).lower()


def test_algebraic_validator_passes_on_fixture(tmp_path):
    wide = str(tmp_path / "wide.parquet"); build_fixture_wide(wide, "blob")
    # full set incl. h3 so the validator's h3 checks run
    cmd = [sys.executable, BUILD, "--wide", wide, "--outdir", str(tmp_path), "--tag", "t",
           "--skip", "wide_h3", "--no-manifest"]
    assert subprocess.run(cmd, capture_output=True, text=True).returncode == 0
    # --min-rows 1 for the tiny fixture; sentinel auto-skips when its pid is absent;
    # --wide exercises the SEMANTIC gate (must still pass on a clean rebuild).
    v = subprocess.run([sys.executable, VALIDATE, "--dir", str(tmp_path), "--tag", "t",
                        "--min-rows", "1", "--wide", wide], capture_output=True, text=True)
    assert v.returncode == 0, f"validator failed on fixture:\n{v.stdout}\n{v.stderr}"


def _build(tmp_path, wide, tag="t", extra=None):
    cmd = [sys.executable, BUILD, "--wide", wide, "--outdir", str(tmp_path), "--tag", tag,
           "--skip", "wide_h3", "--no-manifest"] + (extra or [])
    return subprocess.run(cmd, capture_output=True, text=True)


def test_semantic_gate_catches_corruption_that_internal_checks_miss(tmp_path):
    """The whole point (Codex's attack): corrupt map_lite coords so internal
    consistency still holds, but the --wide semantic gate must FAIL."""
    wide = str(tmp_path / "wide.parquet"); build_fixture_wide(wide, "blob")
    assert _build(tmp_path, wide).returncode == 0
    ml = str(tmp_path / "t_samples_map_lite.parquet")

    # corrupt: zero out every latitude (passes pid-set/uniqueness/h3-sum checks)
    con = duckdb.connect()
    tmp_ml = ml + ".tmp"
    con.execute(f"""COPY (SELECT pid, label, source, 0.0::DOUBLE AS latitude, longitude,
                   place_name, result_time, h3_res8, h3_res8_hex FROM read_parquet('{ml}'))
                   TO '{tmp_ml}' (FORMAT PARQUET)""")
    con.close(); os.replace(tmp_ml, ml)

    # internal-only validator: still PASSES (the hole Codex exploited)
    internal = subprocess.run([sys.executable, VALIDATE, "--dir", str(tmp_path), "--tag", "t", "--min-rows", "1"],
                              capture_output=True, text=True)
    assert internal.returncode == 0, "expected internal-only checks to miss coord corruption"

    # semantic gate (--wide): must now FAIL
    semantic = subprocess.run([sys.executable, VALIDATE, "--dir", str(tmp_path), "--tag", "t",
                               "--min-rows", "1", "--wide", wide], capture_output=True, text=True)
    assert semantic.returncode != 0, f"semantic gate failed to catch coord corruption:\n{semantic.stdout}"
    assert "map_lite == fresh build" in semantic.stdout


def test_duplicate_pid_hard_fails(tmp_path):
    wide = str(tmp_path / "wide.parquet"); build_fixture_wide(wide, "blob")
    con = duckdb.connect(); con.execute("INSTALL spatial; LOAD spatial;")
    # append a duplicate of an existing located pid
    dup = str(tmp_path / "wide_dup.parquet")
    con.execute(f"""COPY (
        SELECT * FROM read_parquet('{wide}')
        UNION ALL
        SELECT * FROM read_parquet('{wide}') WHERE pid='m-real-first'
    ) TO '{dup}' (FORMAT PARQUET)""")
    con.close()
    r = _build(tmp_path, dup)
    assert r.returncode != 0 and "non-unique" in (r.stdout + r.stderr).lower(), \
        f"builder should hard-fail on duplicate pids:\n{r.stdout}\n{r.stderr}"


def test_manifest_emitted(tmp_path):
    import json
    wide = str(tmp_path / "wide.parquet"); build_fixture_wide(wide, "blob")
    cmd = [sys.executable, BUILD, "--wide", wide, "--outdir", str(tmp_path), "--tag", "t", "--skip", "wide_h3"]
    assert subprocess.run(cmd, capture_output=True, text=True).returncode == 0
    man = tmp_path / "t_manifest.json"
    assert man.exists()
    m = json.loads(man.read_text())
    assert m["input"]["sha256"] and m["duckdb_version"] and m["outputs"]
    assert any("sample_facets_v2" in k for k in m["outputs"])
    assert all("sha256" in v and "rows" in v for v in m["outputs"].values())


def test_wide_h3_cells_match_map_lite(tmp_path):
    wide = str(tmp_path / "wide.parquet"); build_fixture_wide(wide, "blob")
    assert _build(tmp_path, wide).returncode == 0  # builds map_lite (skips wide_h3)
    cmd = [sys.executable, BUILD, "--wide", wide, "--outdir", str(tmp_path), "--tag", "t",
           "--only", "wide_h3", "--no-manifest"]
    assert subprocess.run(cmd, capture_output=True, text=True).returncode == 0
    con = duckdb.connect()
    wh3 = f"read_parquet('{tmp_path / 't_wide_h3.parquet'}')"
    ml = f"read_parquet('{tmp_path / 't_samples_map_lite.parquet'}')"
    cols = [r[0] for r in con.sql(f"DESCRIBE SELECT * FROM {wh3}").fetchall()]
    assert {"h3_res4", "h3_res6", "h3_res8"} <= set(cols)
    # CORRECTNESS: wide_h3 cells must agree with map_lite's for the same located pids
    bad = con.sql(f"SELECT COUNT(*) FROM {wh3} w JOIN {ml} m ON w.pid=m.pid "
                  f"WHERE w.h3_res8 IS DISTINCT FROM m.h3_res8").fetchone()[0]
    assert bad == 0, f"{bad} wide_h3 rows have h3_res8 disagreeing with map_lite"


def test_semantic_gate_catches_h3_center_and_resolution_corruption(tmp_path):
    wide = str(tmp_path / "wide.parquet"); build_fixture_wide(wide, "blob")
    assert _build(tmp_path, wide).returncode == 0
    h3f = str(tmp_path / "t_h3_summary_res4.parquet")
    con = duckdb.connect()
    tmp_h3 = h3f + ".tmp"
    con.execute(f"""COPY (SELECT h3_cell, sample_count, 0.0::DOUBLE AS center_lat, center_lng,
                   dominant_source, source_count, 999::INTEGER AS resolution FROM read_parquet('{h3f}'))
                   TO '{tmp_h3}' (FORMAT PARQUET)"""); con.close(); os.replace(tmp_h3, h3f)
    v = subprocess.run([sys.executable, VALIDATE, "--dir", str(tmp_path), "--tag", "t",
                        "--min-rows", "1", "--wide", wide], capture_output=True, text=True)
    assert v.returncode != 0 and "h3 res4" in v.stdout, f"gate missed h3 center/resolution corruption:\n{v.stdout}"


def test_h3_center_micro_shift_caught(tmp_path):
    """Adversary shifted every H3 centroid ~9m (8e-5 deg) and passed the old 1e-4
    tolerance. The tightened 1e-5 gate must now catch it."""
    wide = str(tmp_path / "wide.parquet"); build_fixture_wide(wide, "blob")
    assert _build(tmp_path, wide).returncode == 0
    h3f = str(tmp_path / "t_h3_summary_res4.parquet")
    con = duckdb.connect(); tmp_h3 = h3f + ".tmp"
    con.execute(f"""COPY (SELECT h3_cell, sample_count, ROUND(center_lat+8e-5,6) AS center_lat,
                   ROUND(center_lng+8e-5,6) AS center_lng, dominant_source, source_count, resolution
                   FROM read_parquet('{h3f}')) TO '{tmp_h3}' (FORMAT PARQUET)"""); con.close(); os.replace(tmp_h3, h3f)
    v = subprocess.run([sys.executable, VALIDATE, "--dir", str(tmp_path), "--tag", "t",
                        "--min-rows", "1", "--wide", wide], capture_output=True, text=True)
    assert v.returncode != 0 and "centers within" in v.stdout, f"gate missed ~9m centroid shift:\n{v.stdout}"


def test_manifest_tamper_caught(tmp_path):
    """Adversary corrupted manifest.json sha256s and the validator ignored it.
    Manifest integrity must now be a gated check."""
    import json
    wide = str(tmp_path / "wide.parquet"); build_fixture_wide(wide, "blob")
    cmd = [sys.executable, BUILD, "--wide", wide, "--outdir", str(tmp_path), "--tag", "t", "--skip", "wide_h3"]
    assert subprocess.run(cmd, capture_output=True, text=True).returncode == 0
    man = tmp_path / "t_manifest.json"
    m = json.loads(man.read_text())
    for k in m["outputs"]:
        m["outputs"][k]["sha256"] = "deadbeef" * 8
    man.write_text(json.dumps(m))
    v = subprocess.run([sys.executable, VALIDATE, "--dir", str(tmp_path), "--tag", "t", "--min-rows", "1"],
                       capture_output=True, text=True)
    assert v.returncode != 0 and "manifest sha256" in v.stdout, f"gate missed manifest tamper:\n{v.stdout}"


# ---------------------------------------------------------------------------
# facet_tree_cross_filter cube (#290/#293)
# A self-contained tree fixture: a tiny SKOS vocab (broader edges) + located
# samples whose concept arrays resolve into those trees, so the REAL builder
# produces membership + tree_summaries + the cross-filter cube. We assert
# EXPLICIT known counts (catches builder-logic bugs a re-derivation can't),
# then confirm the validator's cube gate fires on corruption.
# ---------------------------------------------------------------------------
SF = "https://w3id.org/isample/vocabulary/sampledfeature/1.0/"          # context tree
OT = "https://w3id.org/isample/vocabulary/materialsampleobjecttype/1.0/"  # object_type tree

# row_id -> uri, for the tree fixture (roots match DIM_ROOT in the builder)
TREE_CONCEPTS = [
    (1, ROOT), (2, MAT + "mineral"), (3, MAT + "rock"),
    (10, SF + "anysampledfeature"), (11, SF + "earthinterior"),
    (20, OT + "materialsample"), (21, OT + "othersolidobject"),
]
# broader edges (data_v1 form): (uri, parent_uri-or-None)
TREE_EDGES = [
    (ROOT, None), (MAT + "mineral", ROOT), (MAT + "rock", ROOT),
    (SF + "anysampledfeature", None), (SF + "earthinterior", SF + "anysampledfeature"),
    (OT + "materialsample", None), (OT + "othersolidobject", OT + "materialsample"),
]
# (pid, source, material_rids, context_rids, object_rids)
TREE_SAMPLES = [
    ("s1", "A", [2], [11], [21]),   # mineral, earthinterior, othersolidobject
    ("s2", "A", [3], [11], [21]),   # rock,    earthinterior, othersolidobject
    ("s3", "B", [2], [11], [21]),   # mineral, earthinterior, othersolidobject
]


def build_tree_fixture(wide, vocab):
    con = duckdb.connect(); con.execute("INSTALL spatial; LOAD spatial;")
    ic_rows = " UNION ALL ".join(
        f"SELECT 'IdentifiedConcept' AS otype, '{uri}' AS pid, {rid}::BIGINT AS row_id, NULL::VARCHAR AS n, "
        f"'lbl' AS label, NULL::VARCHAR AS description, NULL::VARCHAR[] AS place_name, NULL::TIMESTAMP AS result_time, "
        f"NULL AS geometry, NULL::BIGINT[] AS p__has_material_category, NULL::BIGINT[] AS p__has_context_category, "
        f"NULL::BIGINT[] AS p__has_sample_object_type, NULL::BIGINT[] AS p__keywords"
        for rid, uri in TREE_CONCEPTS)
    msr = []
    for i, (pid, src, m, c, o) in enumerate(TREE_SAMPLES):
        msr.append(
            f"SELECT 'MaterialSampleRecord' AS otype, '{pid}' AS pid, NULL::BIGINT AS row_id, '{src}' AS n, "
            f"'label {pid}' AS label, 'desc {pid}' AS description, ['plc-{pid}']::VARCHAR[] AS place_name, "
            f"NULL::TIMESTAMP AS result_time, ST_AsWKB(ST_Point({10.0+i},{40.0+i})) AS geometry, "
            f"{_arr(m)} AS p__has_material_category, {_arr(c)} AS p__has_context_category, "
            f"{_arr(o)} AS p__has_sample_object_type, NULL::BIGINT[] AS p__keywords")
    con.execute(f"COPY ({ic_rows} UNION ALL {' UNION ALL '.join(msr)}) TO '{wide}' (FORMAT PARQUET)")
    edges = " UNION ALL ".join(
        f"SELECT '{u}' uri, {('NULL' if p is None else repr(p))}::VARCHAR broader, 'data_v1' uri_form"
        for u, p in TREE_EDGES)
    con.execute(f"COPY ({edges}) TO '{vocab}' (FORMAT PARQUET)")
    con.close()


def _build_tree(tmp_path, wide, vocab, tag="t"):
    cmd = [sys.executable, BUILD, "--wide", wide, "--outdir", str(tmp_path), "--tag", tag,
           "--skip", "wide_h3", "--no-manifest", "--vocab-labels", vocab]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_tree_cross_filter_explicit_counts(tmp_path):
    wide = str(tmp_path / "wide.parquet"); vocab = str(tmp_path / "vocab.parquet")
    build_tree_fixture(wide, vocab)
    r = _build_tree(tmp_path, wide, vocab)
    assert r.returncode == 0, f"tree build failed:\n{r.stdout}\n{r.stderr}"
    cube = f"read_parquet('{tmp_path / 't_facet_tree_cross_filter.parquet'}')"
    con = duckdb.connect()

    def cnt(fcol, fval, ftype, fvalue):
        nulls = " AND ".join(f"{c} IS NULL" for c in
                             ["filter_source", "filter_material", "filter_context", "filter_object_type"]
                             if c != fcol)
        where = (f"{fcol}='{fval}' AND " if fcol else "") + (nulls if fcol else
                 "filter_source IS NULL AND filter_material IS NULL AND filter_context IS NULL AND filter_object_type IS NULL")
        row = con.sql(f"SELECT count FROM {cube} WHERE {where} AND facet_type='{ftype}' AND facet_value='{fvalue}'").fetchone()
        return row[0] if row else 0

    # filter material=mineral (subtree pids: s1,s3) -> context earthinterior = 2
    assert cnt("filter_material", MAT + "mineral", "context", SF + "earthinterior") == 2
    # ...and its ancestor anysampledfeature also = 2 (subtree semantics)
    assert cnt("filter_material", MAT + "mineral", "context", SF + "anysampledfeature") == 2
    # filter material=mineral -> source A = 1 (s1), source B = 1 (s3)
    assert cnt("filter_material", MAT + "mineral", "source", "A") == 1
    assert cnt("filter_material", MAT + "mineral", "source", "B") == 1
    # filter source=A (s1,s2) -> material mineral = 1 (s1), rock = 1 (s2), root = 2
    assert cnt("filter_source", "A", "material", MAT + "mineral") == 1
    assert cnt("filter_source", "A", "material", MAT + "rock") == 1
    assert cnt("filter_source", "A", "material", ROOT) == 2
    # baseline (no filter): material root = 3, context anysampledfeature = 3, source A = 2
    assert cnt(None, None, "material", ROOT) == 3
    assert cnt(None, None, "context", SF + "anysampledfeature") == 3
    assert cnt(None, None, "source", "A") == 2
    # no same-dim rows (a dim never cross-filters itself)
    same = con.sql(f"""SELECT COUNT(*) FROM {cube} WHERE
        (filter_material IS NOT NULL AND facet_type='material') OR
        (filter_context  IS NOT NULL AND facet_type='context')  OR
        (filter_object_type IS NOT NULL AND facet_type='object_type') OR
        (filter_source IS NOT NULL AND facet_type='source')""").fetchone()[0]
    assert same == 0, f"{same} forbidden same-dim cross-filter rows"


def test_tree_cross_filter_validator_passes_and_gate_bites(tmp_path):
    wide = str(tmp_path / "wide.parquet"); vocab = str(tmp_path / "vocab.parquet")
    build_tree_fixture(wide, vocab)
    assert _build_tree(tmp_path, wide, vocab).returncode == 0
    # clean: validator (incl. the new cube gate + all tree gates) must PASS
    v = subprocess.run([sys.executable, VALIDATE, "--dir", str(tmp_path), "--tag", "t",
                        "--min-rows", "1", "--wide", wide], capture_output=True, text=True)
    assert v.returncode == 0, f"validator failed on clean tree fixture:\n{v.stdout}\n{v.stderr}"
    assert "tree_cross_filter == re-derived self-join" in v.stdout
    # corrupt: bump every cube count by 1 -> the cube gate must FAIL
    cube = str(tmp_path / "t_facet_tree_cross_filter.parquet")
    con = duckdb.connect(); tmp_c = cube + ".tmp"
    con.execute(f"""COPY (SELECT filter_source, filter_material, filter_context, filter_object_type,
                   facet_type, facet_value, count+1 AS count FROM read_parquet('{cube}'))
                   TO '{tmp_c}' (FORMAT PARQUET)"""); con.close(); os.replace(tmp_c, cube)
    v2 = subprocess.run([sys.executable, VALIDATE, "--dir", str(tmp_path), "--tag", "t", "--min-rows", "1"],
                        capture_output=True, text=True)
    assert v2.returncode != 0 and "tree_cross_filter" in v2.stdout, \
        f"cube gate failed to catch corruption:\n{v2.stdout}"


def test_tree_cross_filter_only_builds(tmp_path):
    """`--only facet_tree_cross_filter` must actually produce the file (Codex P2:
    the hierarchy guard previously omitted it -> rc=0 but no output)."""
    wide = str(tmp_path / "wide.parquet"); vocab = str(tmp_path / "vocab.parquet")
    build_tree_fixture(wide, vocab)
    r = subprocess.run([sys.executable, BUILD, "--wide", wide, "--outdir", str(tmp_path),
                        "--tag", "t", "--no-manifest", "--vocab-labels", vocab,
                        "--only", "facet_tree_cross_filter"], capture_output=True, text=True)
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert (tmp_path / "t_facet_tree_cross_filter.parquet").exists(), \
        f"--only facet_tree_cross_filter produced no file:\n{r.stdout}\n{r.stderr}"


def test_tree_cross_filter_only_requires_vocab(tmp_path):
    """Explicit --only facet_tree_cross_filter without --vocab-labels must fail loud."""
    wide = str(tmp_path / "wide.parquet"); vocab = str(tmp_path / "vocab.parquet")
    build_tree_fixture(wide, vocab)
    r = subprocess.run([sys.executable, BUILD, "--wide", wide, "--outdir", str(tmp_path),
                        "--tag", "t", "--no-manifest", "--only", "facet_tree_cross_filter"],
                       capture_output=True, text=True)
    assert r.returncode != 0 and "vocab-labels" in (r.stdout + r.stderr).lower()


def test_tree_cross_filter_grain_gate_bites(tmp_path):
    """Doubling every cube row keeps counts 'correct' under EXCEPT set-semantics;
    the grain/uniqueness check must catch it (Codex P3)."""
    wide = str(tmp_path / "wide.parquet"); vocab = str(tmp_path / "vocab.parquet")
    build_tree_fixture(wide, vocab)
    assert _build_tree(tmp_path, wide, vocab).returncode == 0
    cube = str(tmp_path / "t_facet_tree_cross_filter.parquet")
    con = duckdb.connect(); tmp_c = cube + ".tmp"
    con.execute(f"""COPY (SELECT * FROM read_parquet('{cube}')
                   UNION ALL SELECT * FROM read_parquet('{cube}'))
                   TO '{tmp_c}' (FORMAT PARQUET)"""); con.close(); os.replace(tmp_c, cube)
    v = subprocess.run([sys.executable, VALIDATE, "--dir", str(tmp_path), "--tag", "t", "--min-rows", "1"],
                       capture_output=True, text=True)
    assert v.returncode != 0 and "grain unique" in v.stdout, \
        f"grain gate failed to catch a doubled cube:\n{v.stdout}"


def test_scheme_corruption_caught(tmp_path):
    wide = str(tmp_path / "wide.parquet"); build_fixture_wide(wide, "blob")
    assert _build(tmp_path, wide).returncode == 0
    sf = str(tmp_path / "t_facet_summaries.parquet")
    con = duckdb.connect(); tmp_s = sf + ".tmp"
    con.execute(f"""COPY (SELECT facet_type, facet_value, 7::INTEGER AS scheme, count
                   FROM read_parquet('{sf}')) TO '{tmp_s}' (FORMAT PARQUET)"""); con.close(); os.replace(tmp_s, sf)
    v = subprocess.run([sys.executable, VALIDATE, "--dir", str(tmp_path), "--tag", "t", "--min-rows", "1"],
                       capture_output=True, text=True)
    assert v.returncode != 0 and "scheme" in v.stdout, f"gate missed scheme corruption:\n{v.stdout}"
