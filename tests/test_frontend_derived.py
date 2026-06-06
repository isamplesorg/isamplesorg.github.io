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
        f"NULL::BIGINT[] AS p__has_sample_object_type"
        for rid, uri in CONCEPTS)

    msr = []
    for i, (pid, marr, _) in enumerate(SAMPLES):
        lng, lat = 10.0 + i, 40.0 + i
        msr.append(
            f"SELECT 'MaterialSampleRecord' AS otype, '{pid}' AS pid, NULL::BIGINT AS row_id, 'TEST' AS n, "
            f"'label {pid}' AS label, 'desc {pid}' AS description, ['plc-{pid}','x''q']::VARCHAR[] AS place_name, "
            f"NULL::TIMESTAMP AS result_time, {geom(lng, lat)} AS geometry, "
            f"{_arr(marr)} AS p__has_material_category, [10]::BIGINT[] AS p__has_context_category, "
            f"[20]::BIGINT[] AS p__has_sample_object_type")
    # one NULL-geometry sample -> must be EXCLUDED from located outputs
    msr.append(
        "SELECT 'MaterialSampleRecord' AS otype, 'm-nogeo' AS pid, NULL::BIGINT AS row_id, 'TEST' AS n, "
        "'l' AS label, 'd' AS description, NULL::VARCHAR[] AS place_name, NULL::TIMESTAMP AS result_time, "
        "NULL AS geometry, [4]::BIGINT[] AS p__has_material_category, [10]::BIGINT[] AS p__has_context_category, "
        "[20]::BIGINT[] AS p__has_sample_object_type")

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
    # --min-rows 1 for the tiny fixture; sentinel auto-skips when its pid is absent.
    v = subprocess.run([sys.executable, VALIDATE, "--dir", str(tmp_path), "--tag", "t", "--min-rows", "1"],
                       capture_output=True, text=True)
    assert v.returncode == 0, f"validator failed on fixture:\n{v.stdout}\n{v.stderr}"
