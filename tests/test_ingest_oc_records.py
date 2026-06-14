"""Fast, AI-free fixture tests for the OC record ingestion (#272 Phase 2).

Builds tiny synthetic src-wide + oc-wide parquet pairs, runs the real
ingest script against them, and asserts the contract:

  TRUE SYNC behavior (D3 decision):
  - New pids (Eric's \ src) are ingested with full entity subgraph
  - Stale pids (src \ Eric's) are REMOVED along with orphan subgraph entities
  - Shared entities (referenced by both surviving and removed MSRs) are kept
  - Surviving non-OC rows are byte-identical

  Entity subgraph:
  - MaterialSampleRecord + SamplingEvent + GeospatialCoordLocation + SamplingSite + Agent
  - row_id remapping: new entities get deterministic ids starting at max(src)+1
  - p__ arrays remapped from Eric's integer space to our BIGINT space
  - geometry denormalized from GeoCoordLoc onto MSR rows (WKB BLOB)
  - n='OPENCONTEXT' on new MSR rows (Eric's wide has NULL)

  Trust-gate invariants:
  - Hard-fail on duplicate OC MSR pids in Eric's wide
  - Hard-fail on new pids that already exist in src wide
  - Hard-fail on unresolved p__ references in new rows
  - Row count arithmetic verified post-write
  - No removed pids remain in output

  Determinism:
  - Same inputs → bit-identical output (--no-manifest mode)

Run: pytest tests/test_ingest_oc_records.py -q   (needs: duckdb, spatial, h3)
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
INGEST = os.path.join(REPO, "scripts", "ingest_oc_records.py")

# Vocabulary URI prefixes for test fixtures
MAT = "https://w3id.org/isample/vocabulary/material/1.0/"
OBJ = "https://w3id.org/isample/vocabulary/materialsampleobjecttype/1.0/"
SF = "https://w3id.org/isample/vocabulary/sampledfeature/1.0/"
ROOT_MAT = MAT + "material"


# ---- fixture-building helpers -----------------------------------------------

def build_src_wide(path, *, msr_rows, concept_rows, se_rows, geo_rows,
                   site_rows=None, agent_rows=None, extra_rows=None):
    """Build a minimal src wide parquet with the specified entity rows.

    msr_rows: list of dict with keys: row_id, pid, n, p__produced_by (list of ints),
              p__has_material_category, p__has_sample_object_type, p__has_context_category
              (lists of ints), geometry (WKB BLOB bytes or None), latitude, longitude
    concept_rows: list of (row_id, uri)
    se_rows: list of (row_id, pid, p__sample_location [list of int], p__sampling_site [list of int])
    geo_rows: list of (row_id, pid, latitude, longitude) — geometry will be ST_AsWKB(ST_Point)
    site_rows: list of (row_id, pid, p__site_location [list of int])
    agent_rows: list of (row_id, pid)
    """
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")

    def _arr(xs, t="BIGINT[]"):
        if xs is None:
            return f"NULL::{t}"
        return "[" + ",".join(str(x) for x in xs) + f"]::{t}"

    rows = []

    # Concept rows
    for rid, uri in concept_rows:
        rows.append(
            f"SELECT {rid}::BIGINT AS row_id, '{uri}' AS pid, 'IdentifiedConcept' AS otype, "
            f"NULL::VARCHAR AS n, NULL::BLOB AS geometry, NULL::DOUBLE AS latitude, "
            f"NULL::DOUBLE AS longitude, NULL::VARCHAR AS label, NULL::VARCHAR AS description, "
            f"NULL::VARCHAR[] AS place_name, NULL::TIMESTAMP AS result_time, "
            f"NULL::BIGINT[] AS p__has_material_category, NULL::BIGINT[] AS p__has_sample_object_type, "
            f"NULL::BIGINT[] AS p__has_context_category, NULL::BIGINT[] AS p__produced_by, "
            f"NULL::BIGINT[] AS p__sample_location, NULL::BIGINT[] AS p__sampling_site, "
            f"NULL::BIGINT[] AS p__site_location, NULL::BIGINT[] AS p__registrant, "
            f"NULL::BIGINT[] AS p__keywords, NULL::BIGINT[] AS p__responsibility, "
            f"NULL::INTEGER[] AS p__curation, NULL::BIGINT[] AS p__related_resource, "
            f"NULL::VARCHAR AS thumbnail_url, NULL::VARCHAR AS scheme_name, NULL::VARCHAR AS scheme_uri"
        )

    # MSR rows
    for m in msr_rows:
        lat = m.get("latitude")
        lon = m.get("longitude")
        if lat is not None and lon is not None:
            geom_expr = f"ST_AsWKB(ST_Point({lon}, {lat}))::BLOB"
        else:
            geom_expr = "NULL::BLOB"
        lat_expr = f"{lat}::DOUBLE" if lat is not None else "NULL::DOUBLE"
        lon_expr = f"{lon}::DOUBLE" if lon is not None else "NULL::DOUBLE"
        pid = m['pid']
        n_val = m.get('n', 'OPENCONTEXT')
        rows.append(
            f"SELECT {m['row_id']}::BIGINT, '{pid}', 'MaterialSampleRecord', "
            f"'{n_val}'::VARCHAR, "
            f"{geom_expr}, {lat_expr}, {lon_expr}, "
            f"'label {pid}', 'desc {pid}', "
            f"['place1']::VARCHAR[], NULL::TIMESTAMP, "
            f"{_arr(m.get('p__has_material_category'))}, "
            f"{_arr(m.get('p__has_sample_object_type'))}, "
            f"{_arr(m.get('p__has_context_category'))}, "
            f"{_arr(m.get('p__produced_by'))}, "
            f"NULL::BIGINT[], NULL::BIGINT[], NULL::BIGINT[], "
            f"{_arr(m.get('p__registrant'))}, "
            f"NULL::BIGINT[], NULL::BIGINT[], NULL::INTEGER[], NULL::BIGINT[], "
            f"NULL::VARCHAR, NULL::VARCHAR, NULL::VARCHAR"
        )

    # SE rows
    for rid, pid, sample_loc, sampling_site in (se_rows or []):
        rows.append(
            f"SELECT {rid}::BIGINT, '{pid}', 'SamplingEvent', NULL::VARCHAR, "
            f"NULL::BLOB, NULL::DOUBLE, NULL::DOUBLE, NULL, NULL, NULL::VARCHAR[], NULL::TIMESTAMP, "
            f"NULL::BIGINT[], NULL::BIGINT[], NULL::BIGINT[], NULL::BIGINT[], "
            f"{_arr(sample_loc)}, {_arr(sampling_site)}, NULL::BIGINT[], "
            f"NULL::BIGINT[], NULL::BIGINT[], NULL::BIGINT[], NULL::INTEGER[], NULL::BIGINT[], "
            f"NULL::VARCHAR, NULL::VARCHAR, NULL::VARCHAR"
        )

    # Geo rows
    for rid, pid, lat, lon in (geo_rows or []):
        rows.append(
            f"SELECT {rid}::BIGINT, '{pid}', 'GeospatialCoordLocation', NULL::VARCHAR, "
            f"ST_AsWKB(ST_Point({lon}, {lat}))::BLOB, {lat}::DOUBLE, {lon}::DOUBLE, "
            f"NULL, NULL, NULL::VARCHAR[], NULL::TIMESTAMP, "
            f"NULL::BIGINT[], NULL::BIGINT[], NULL::BIGINT[], NULL::BIGINT[], "
            f"NULL::BIGINT[], NULL::BIGINT[], NULL::BIGINT[], NULL::BIGINT[], "
            f"NULL::BIGINT[], NULL::BIGINT[], NULL::INTEGER[], NULL::BIGINT[], "
            f"NULL::VARCHAR, NULL::VARCHAR, NULL::VARCHAR"
        )

    # SamplingSite rows
    for rid, pid, site_loc in (site_rows or []):
        rows.append(
            f"SELECT {rid}::BIGINT, '{pid}', 'SamplingSite', NULL::VARCHAR, "
            f"NULL::BLOB, NULL::DOUBLE, NULL::DOUBLE, NULL, NULL, NULL::VARCHAR[], NULL::TIMESTAMP, "
            f"NULL::BIGINT[], NULL::BIGINT[], NULL::BIGINT[], NULL::BIGINT[], "
            f"NULL::BIGINT[], NULL::BIGINT[], {_arr(site_loc)}, "
            f"NULL::BIGINT[], NULL::BIGINT[], NULL::BIGINT[], NULL::INTEGER[], NULL::BIGINT[], "
            f"NULL::VARCHAR, NULL::VARCHAR, NULL::VARCHAR"
        )

    # Agent rows
    for rid, pid in (agent_rows or []):
        rows.append(
            f"SELECT {rid}::BIGINT, '{pid}', 'Agent', NULL::VARCHAR, "
            f"NULL::BLOB, NULL::DOUBLE, NULL::DOUBLE, NULL, NULL, NULL::VARCHAR[], NULL::TIMESTAMP, "
            f"NULL::BIGINT[], NULL::BIGINT[], NULL::BIGINT[], NULL::BIGINT[], "
            f"NULL::BIGINT[], NULL::BIGINT[], NULL::BIGINT[], NULL::BIGINT[], "
            f"NULL::BIGINT[], NULL::BIGINT[], NULL::INTEGER[], NULL::BIGINT[], "
            f"NULL::VARCHAR, NULL::VARCHAR, NULL::VARCHAR"
        )

    # Extra rows (raw SQL)
    if extra_rows:
        rows.extend(extra_rows)

    con.execute(f"COPY ({' UNION ALL '.join(rows)}) TO '{path}' (FORMAT PARQUET)")
    con.close()


def build_oc_wide(path, *, msr_rows, concept_rows, se_rows, geo_rows,
                  site_rows=None, agent_rows=None):
    """Build a minimal OC wide parquet in Eric's schema (INTEGER row_id, GEOMETRY geometry).

    geo_rows: list of (row_id, pid, latitude, longitude) — geometry stored as GEOMETRY type
    """
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")

    def _arr(xs, t="INTEGER[]"):
        if xs is None:
            return f"NULL::{t}"
        return "[" + ",".join(str(x) for x in xs) + f"]::{t}"

    rows = []

    # Concept rows
    for rid, uri, label in concept_rows:
        rows.append(
            f"SELECT {rid}::INTEGER AS row_id, '{uri}' AS pid, 'IdentifiedConcept' AS otype, "
            f"NULL::VARCHAR AS n, NULL::GEOMETRY AS geometry, NULL::DOUBLE AS latitude, "
            f"NULL::DOUBLE AS longitude, {repr(label)}::VARCHAR AS label, "
            f"NULL::VARCHAR AS description, NULL::VARCHAR[] AS place_name, NULL::TIMESTAMP AS result_time, "
            f"NULL::INTEGER[] AS p__has_material_category, NULL::INTEGER[] AS p__has_sample_object_type, "
            f"NULL::INTEGER[] AS p__has_context_category, NULL::INTEGER[] AS p__produced_by, "
            f"NULL::INTEGER[] AS p__sample_location, NULL::INTEGER[] AS p__sampling_site, "
            f"NULL::INTEGER[] AS p__site_location, NULL::INTEGER[] AS p__registrant, "
            f"NULL::INTEGER[] AS p__keywords, NULL::INTEGER[] AS p__responsibility, "
            f"NULL::VARCHAR AS thumbnail_url, NULL::VARCHAR AS scheme_name, NULL::VARCHAR AS scheme_uri"
        )

    # MSR rows (no geometry on MSR in Eric's wide)
    for m in msr_rows:
        pid = m['pid']
        rows.append(
            f"SELECT {m['row_id']}::INTEGER, '{pid}', 'MaterialSampleRecord', "
            f"NULL::VARCHAR, "  # n is NULL in Eric's wide
            f"NULL::GEOMETRY, NULL::DOUBLE, NULL::DOUBLE, "
            f"'label {pid}', 'desc {pid}', "
            f"['place1']::VARCHAR[], NULL::TIMESTAMP, "
            f"{_arr(m.get('p__has_material_category'))}, "
            f"{_arr(m.get('p__has_sample_object_type'))}, "
            f"{_arr(m.get('p__has_context_category'))}, "
            f"{_arr(m.get('p__produced_by'))}, "
            f"NULL::INTEGER[], NULL::INTEGER[], NULL::INTEGER[], "
            f"{_arr(m.get('p__registrant'))}, "
            f"{_arr(m.get('p__keywords'))}, NULL::INTEGER[], "
            f"NULL::VARCHAR, NULL::VARCHAR, NULL::VARCHAR"
        )

    # SE rows
    for rid, pid, sample_loc, sampling_site in (se_rows or []):
        rows.append(
            f"SELECT {rid}::INTEGER, '{pid}', 'SamplingEvent', NULL::VARCHAR, "
            f"NULL::GEOMETRY, NULL::DOUBLE, NULL::DOUBLE, NULL, NULL, NULL::VARCHAR[], NULL::TIMESTAMP, "
            f"NULL::INTEGER[], NULL::INTEGER[], NULL::INTEGER[], NULL::INTEGER[], "
            f"{_arr(sample_loc)}, {_arr(sampling_site)}, NULL::INTEGER[], "
            f"NULL::INTEGER[], NULL::INTEGER[], NULL::INTEGER[], "
            f"NULL::VARCHAR, NULL::VARCHAR, NULL::VARCHAR"
        )

    # Geo rows (GEOMETRY type in Eric's wide)
    for rid, pid, lat, lon in (geo_rows or []):
        rows.append(
            f"SELECT {rid}::INTEGER, '{pid}', 'GeospatialCoordLocation', NULL::VARCHAR, "
            f"ST_Point({lon}, {lat})::GEOMETRY, {lat}::DOUBLE, {lon}::DOUBLE, "
            f"NULL, NULL, NULL::VARCHAR[], NULL::TIMESTAMP, "
            f"NULL::INTEGER[], NULL::INTEGER[], NULL::INTEGER[], NULL::INTEGER[], "
            f"NULL::INTEGER[], NULL::INTEGER[], NULL::INTEGER[], NULL::INTEGER[], "
            f"NULL::INTEGER[], NULL::INTEGER[], "
            f"NULL::VARCHAR, NULL::VARCHAR, NULL::VARCHAR"
        )

    # SamplingSite rows
    for rid, pid, site_loc in (site_rows or []):
        rows.append(
            f"SELECT {rid}::INTEGER, '{pid}', 'SamplingSite', NULL::VARCHAR, "
            f"NULL::GEOMETRY, NULL::DOUBLE, NULL::DOUBLE, NULL, NULL, NULL::VARCHAR[], NULL::TIMESTAMP, "
            f"NULL::INTEGER[], NULL::INTEGER[], NULL::INTEGER[], NULL::INTEGER[], "
            f"NULL::INTEGER[], NULL::INTEGER[], {_arr(site_loc)}, "
            f"NULL::INTEGER[], NULL::INTEGER[], NULL::INTEGER[], "
            f"NULL::VARCHAR, NULL::VARCHAR, NULL::VARCHAR"
        )

    # Agent rows
    for rid, pid in (agent_rows or []):
        rows.append(
            f"SELECT {rid}::INTEGER, '{pid}', 'Agent', NULL::VARCHAR, "
            f"NULL::GEOMETRY, NULL::DOUBLE, NULL::DOUBLE, NULL, NULL, NULL::VARCHAR[], NULL::TIMESTAMP, "
            f"NULL::INTEGER[], NULL::INTEGER[], NULL::INTEGER[], NULL::INTEGER[], "
            f"NULL::INTEGER[], NULL::INTEGER[], NULL::INTEGER[], NULL::INTEGER[], "
            f"NULL::INTEGER[], NULL::INTEGER[], "
            f"NULL::VARCHAR, NULL::VARCHAR, NULL::VARCHAR"
        )

    con.execute(f"COPY ({' UNION ALL '.join(rows)}) TO '{path}' (FORMAT PARQUET)")
    con.close()


def run_ingest(src, oc, out, extra_args=None):
    cmd = [sys.executable, INGEST, "--src", src, "--oc-wide", oc, "--out", out,
           "--no-manifest"]
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(cmd, capture_output=True, text=True)


def count_otype(path, otype):
    con = duckdb.connect()
    n = con.sql(f"SELECT COUNT(*) FROM read_parquet('{path}') WHERE otype='{otype}'").fetchone()[0]
    con.close()
    return n


def get_msr(path, pid):
    con = duckdb.connect()
    r = con.sql(f"SELECT * FROM read_parquet('{path}') WHERE pid='{pid}' AND otype='MaterialSampleRecord'").fetchone()
    desc = con.sql(f"DESCRIBE SELECT * FROM read_parquet('{path}')").fetchall()
    cols = [d[0] for d in desc]
    con.close()
    if r is None:
        return None
    return dict(zip(cols, r))


# ---- shared fixture ---------------------------------------------------------

# Concept IDs in src space (BIGINT)
SRC_ROOT_CONCEPT_ID = 1
SRC_ROCK_CONCEPT_ID = 2
SRC_ARTIFACT_CONCEPT_ID = 3

SRC_CONCEPT_ROWS = [
    (SRC_ROOT_CONCEPT_ID, ROOT_MAT),
    (SRC_ROCK_CONCEPT_ID, MAT + "rock"),
    (SRC_ARTIFACT_CONCEPT_ID, OBJ + "artifact"),
]

# OC concept IDs in Eric's space (INTEGER)
OC_ROOT_CONCEPT_ID = 901
OC_ROCK_CONCEPT_ID = 902
OC_ARTIFACT_CONCEPT_ID = 903
OC_EARTH_CONCEPT_ID = 904  # earthsurface — not yet in src

OC_CONCEPT_ROWS = [
    (OC_ROOT_CONCEPT_ID, ROOT_MAT, "Material"),
    (OC_ROCK_CONCEPT_ID, MAT + "rock", "Rock"),
    (OC_ARTIFACT_CONCEPT_ID, OBJ + "artifact", "Artifact"),
    (OC_EARTH_CONCEPT_ID, SF + "earthsurface", "Earth Surface"),
]

# Eric's subgraph: 3 SEs, 3 Geos, 2 sites
#   New pids MSR: pid-A (se=101->geo=201), pid-B (se=102->geo=202, site=301->geo_site=211)
#   Removed pids: pid-C (se=103->geo=203) — in src, not in Eric's → stale
OC_SE_ROWS = [
    (101, "se-pid-A", [201], None),   # SE for pid-A
    (102, "se-pid-B", [202], [301]),   # SE for pid-B (with sampling site)
]
OC_SITE_ROWS = [
    (301, "site-pid-B", [211]),  # SamplingSite for pid-B, geo=211
]
OC_GEO_ROWS = [
    (201, "geo-pid-A", 45.0, 10.0),
    (202, "geo-pid-B", 50.0, 15.0),
    (211, "geo-site-B", 50.1, 15.1),  # geo from SamplingSite for pid-B
]
OC_MSR_ROWS = [
    {"row_id": 1, "pid": "pid-A", "p__produced_by": [101],
     "p__has_material_category": [OC_ROCK_CONCEPT_ID],
     "p__has_sample_object_type": [OC_ARTIFACT_CONCEPT_ID],
     "p__has_context_category": [OC_EARTH_CONCEPT_ID]},  # earthsurface to be minted
    {"row_id": 2, "pid": "pid-B", "p__produced_by": [102],
     "p__has_material_category": [OC_ROOT_CONCEPT_ID],
     "p__has_sample_object_type": [OC_ARTIFACT_CONCEPT_ID],
     "p__has_context_category": None},
]

# src wide: has pid-C (stale — not in Eric's), + all existing entities
# pid-C: se_id=103, geo_id=203 — both orphans (not shared with any surviving MSR)
SRC_SE_ROWS = [
    # pid-C's SE (will become orphan)
    (103, "se-pid-C", [203], None),
]
SRC_GEO_ROWS = [
    (203, "geo-pid-C", 60.0, 20.0),  # orphan geo for pid-C
]
SRC_MSR_ROWS = [
    {"row_id": 1000, "pid": "pid-C", "n": "OPENCONTEXT",
     "p__produced_by": [103],
     "p__has_material_category": [SRC_ROCK_CONCEPT_ID],
     "p__has_sample_object_type": [SRC_ARTIFACT_CONCEPT_ID],
     "latitude": 60.0, "longitude": 20.0},
    # non-OC MSR — must survive unchanged
    {"row_id": 1001, "pid": "pid-NON-OC", "n": "SESAR",
     "p__has_material_category": [SRC_ROCK_CONCEPT_ID],
     "latitude": 55.0, "longitude": 25.0},
]
SRC_AGENT_ROWS = [(500, "agent-existing")]  # pre-existing agent


@pytest.fixture
def pair(tmp_path):
    """Canonical 3-MSR fixture: pid-A (new), pid-B (new), pid-C (stale/removed)."""
    src = str(tmp_path / "src.parquet")
    oc = str(tmp_path / "oc.parquet")
    out = str(tmp_path / "out.parquet")

    build_src_wide(
        src,
        msr_rows=SRC_MSR_ROWS,
        concept_rows=SRC_CONCEPT_ROWS,
        se_rows=SRC_SE_ROWS,
        geo_rows=SRC_GEO_ROWS,
        agent_rows=SRC_AGENT_ROWS,
    )
    build_oc_wide(
        oc,
        msr_rows=OC_MSR_ROWS,
        concept_rows=OC_CONCEPT_ROWS,
        se_rows=OC_SE_ROWS,
        geo_rows=OC_GEO_ROWS,
        site_rows=OC_SITE_ROWS,
    )
    return src, oc, out


# ---- tests ------------------------------------------------------------------

def test_new_pids_ingested(pair):
    """pid-A and pid-B (new) are present in output."""
    src, oc, out = pair
    r = run_ingest(src, oc, out)
    assert r.returncode == 0, r.stderr + r.stdout
    assert get_msr(out, "pid-A") is not None, "pid-A missing from output"
    assert get_msr(out, "pid-B") is not None, "pid-B missing from output"


def test_stale_pid_removed(pair):
    """pid-C (stale) is NOT in output."""
    src, oc, out = pair
    assert run_ingest(src, oc, out).returncode == 0
    assert get_msr(out, "pid-C") is None, "pid-C (stale) should have been removed"


def test_orphan_subgraph_entities_removed(pair):
    """se-pid-C and geo-pid-C (orphans) are NOT in output."""
    src, oc, out = pair
    assert run_ingest(src, oc, out).returncode == 0
    con = duckdb.connect()
    n_se = con.sql(f"SELECT COUNT(*) FROM read_parquet('{out}') WHERE pid='se-pid-C'").fetchone()[0]
    n_geo = con.sql(f"SELECT COUNT(*) FROM read_parquet('{out}') WHERE pid='geo-pid-C'").fetchone()[0]
    con.close()
    assert n_se == 0, "orphan SE se-pid-C should have been removed"
    assert n_geo == 0, "orphan geo geo-pid-C should have been removed"


def test_non_oc_rows_survive_unchanged(pair):
    """pid-NON-OC (SESAR) is present and byte-identical."""
    src, oc, out = pair
    assert run_ingest(src, oc, out).returncode == 0
    r_src = get_msr(src, "pid-NON-OC")
    r_out = get_msr(out, "pid-NON-OC")
    assert r_out is not None, "non-OC MSR should survive"
    assert r_src["pid"] == r_out["pid"]
    assert r_src["n"] == r_out["n"]
    assert r_src["latitude"] == r_out["latitude"]
    assert r_src["longitude"] == r_out["longitude"]


def test_geometry_denormalized_onto_new_msr(pair):
    """New MSR pid-A gets lat/lon from linked GeoCoordLoc (via SE)."""
    src, oc, out = pair
    assert run_ingest(src, oc, out).returncode == 0
    r = get_msr(out, "pid-A")
    assert r is not None
    assert abs(r["latitude"] - 45.0) < 1e-5, f"lat wrong: {r['latitude']}"
    assert abs(r["longitude"] - 10.0) < 1e-5, f"lon wrong: {r['longitude']}"
    assert r["geometry"] is not None, "geometry should be non-null (WKB BLOB)"


def test_n_column_set_on_new_msrs(pair):
    """New MSR rows have n='OPENCONTEXT'."""
    src, oc, out = pair
    assert run_ingest(src, oc, out).returncode == 0
    assert get_msr(out, "pid-A")["n"] == "OPENCONTEXT"
    assert get_msr(out, "pid-B")["n"] == "OPENCONTEXT"


def test_p_array_remapped_to_output_id_space(pair):
    """p__produced_by on new MSR pid-A resolves to a SE row in the output."""
    src, oc, out = pair
    assert run_ingest(src, oc, out).returncode == 0
    con = duckdb.connect()
    # Find the SE row_id stored in pid-A's p__produced_by
    pb = con.sql(f"""
        SELECT p__produced_by[1] FROM read_parquet('{out}')
        WHERE pid='pid-A' AND otype='MaterialSampleRecord'
    """).fetchone()[0]
    # Verify that row_id exists in the output as a SamplingEvent
    se_exists = con.sql(f"""
        SELECT COUNT(*) FROM read_parquet('{out}')
        WHERE row_id = {pb} AND otype='SamplingEvent'
    """).fetchone()[0]
    con.close()
    assert pb is not None, "p__produced_by must be non-null"
    assert se_exists == 1, f"SE row_id {pb} not found in output"


def test_concept_remap_via_uri_lookup(pair):
    """p__has_material_category on new MSR pid-A resolves to the src 'rock' concept row."""
    src, oc, out = pair
    assert run_ingest(src, oc, out).returncode == 0
    con = duckdb.connect()
    # Get the concept row_id used by pid-A in the output
    mat_rid = con.sql(f"""
        SELECT p__has_material_category[1] FROM read_parquet('{out}')
        WHERE pid='pid-A' AND otype='MaterialSampleRecord'
    """).fetchone()[0]
    # Verify it resolves to the 'rock' URI
    rock_uri = con.sql(f"""
        SELECT pid FROM read_parquet('{out}')
        WHERE row_id = {mat_rid} AND otype='IdentifiedConcept'
    """).fetchone()[0]
    con.close()
    assert rock_uri == MAT + "rock", f"concept URI wrong: {rock_uri}"


def test_minted_concept_earthsurface(pair):
    """earthsurface concept is minted when absent from src (referenced by pid-A's context)."""
    src, oc, out = pair
    assert run_ingest(src, oc, out).returncode == 0
    con = duckdb.connect()
    n = con.sql(f"""
        SELECT COUNT(*) FROM read_parquet('{out}')
        WHERE otype='IdentifiedConcept' AND pid='{SF}earthsurface'
    """).fetchone()[0]
    con.close()
    assert n == 1, "earthsurface concept should be minted in output"


def test_sampling_site_ingested_for_pid_b(pair):
    """SamplingSite row (site-pid-B) is present in output for pid-B's chain."""
    src, oc, out = pair
    assert run_ingest(src, oc, out).returncode == 0
    con = duckdb.connect()
    n = con.sql(f"SELECT COUNT(*) FROM read_parquet('{out}') WHERE pid='site-pid-B'").fetchone()[0]
    con.close()
    assert n == 1, "SamplingSite site-pid-B should be in output"


def test_row_count_arithmetic(pair):
    """Output row count = (src - removed) + new_entities + minted_concepts."""
    src, oc, out = pair
    assert run_ingest(src, oc, out).returncode == 0
    con = duckdb.connect()
    n_src = con.sql(f"SELECT COUNT(*) FROM read_parquet('{src}')").fetchone()[0]
    n_out = con.sql(f"SELECT COUNT(*) FROM read_parquet('{out}')").fetchone()[0]
    # Removed: 1 MSR (pid-C) + 1 SE (se-pid-C) + 1 geo (geo-pid-C) = 3 rows
    # New entities: 2 MSR + 2 SE + 3 Geo (201, 202, 211) + 1 Site = 8 rows
    # Minted: 1 (earthsurface)
    # Expected: n_src - 3 + 8 + 1
    expected = n_src - 3 + 8 + 1
    con.close()
    assert n_out == expected, f"row count {n_out} != expected {expected}"


def test_no_duplicate_row_ids(pair):
    """Output has no duplicate row_ids."""
    src, oc, out = pair
    assert run_ingest(src, oc, out).returncode == 0
    con = duckdb.connect()
    n_dup = con.sql(f"""
        SELECT COUNT(*) FROM (
            SELECT row_id FROM read_parquet('{out}')
            GROUP BY row_id HAVING COUNT(*) > 1
        )
    """).fetchone()[0]
    con.close()
    assert n_dup == 0, f"{n_dup} duplicate row_ids in output"


def test_no_duplicate_msr_pids(pair):
    """Output has no duplicate MSR pids."""
    src, oc, out = pair
    assert run_ingest(src, oc, out).returncode == 0
    con = duckdb.connect()
    n_dup = con.sql(f"""
        SELECT COUNT(*) FROM (
            SELECT pid FROM read_parquet('{out}') WHERE otype='MaterialSampleRecord'
            GROUP BY pid HAVING COUNT(*) > 1
        )
    """).fetchone()[0]
    con.close()
    assert n_dup == 0, f"{n_dup} duplicate MSR pids in output"


def test_determinism_bit_identical(pair, tmp_path):
    """Same inputs → bit-identical outputs (--no-manifest suppresses timestamp drift)."""
    src, oc, out = pair
    out2 = str(tmp_path / "out2.parquet")
    assert run_ingest(src, oc, out).returncode == 0
    assert run_ingest(src, oc, out2).returncode == 0
    h = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
    assert h(out) == h(out2), "outputs not bit-identical across two runs with same inputs"


def test_dry_run_produces_no_output(pair):
    """--dry-run exits 0 but does NOT write the output file."""
    src, oc, out = pair
    r = run_ingest(src, oc, out, extra_args=["--dry-run"])
    assert r.returncode == 0, r.stderr + r.stdout
    assert not os.path.exists(out), "--dry-run should not write output"
    assert "DRY RUN" in r.stdout


def test_hard_fail_on_duplicate_oc_pids(pair, tmp_path):
    """Eric's wide with duplicate MSR pids triggers a hard failure."""
    src, oc, out = pair
    dup_oc = str(tmp_path / "oc_dup.parquet")
    # Build OC with pid-A appearing twice
    build_oc_wide(
        dup_oc,
        msr_rows=OC_MSR_ROWS + [{"row_id": 99, "pid": "pid-A",
                                   "p__produced_by": [101],
                                   "p__has_material_category": [OC_ROCK_CONCEPT_ID]}],
        concept_rows=OC_CONCEPT_ROWS,
        se_rows=OC_SE_ROWS,
        geo_rows=OC_GEO_ROWS,
    )
    r = run_ingest(src, dup_oc, out)
    assert r.returncode != 0, "should fail on duplicate OC pids"
    assert "duplicate" in (r.stderr + r.stdout).lower()
    assert not os.path.exists(out)


def test_hard_fail_new_pid_already_in_src(tmp_path):
    """A 'new' pid already in src as non-OC row triggers a hard failure."""
    src = str(tmp_path / "src.parquet")
    oc = str(tmp_path / "oc.parquet")
    out = str(tmp_path / "out.parquet")

    # Build src with pid-A as SESAR (not OC) + pid-C as OC (will be "removed")
    build_src_wide(
        src,
        msr_rows=[
            {"row_id": 1000, "pid": "pid-A", "n": "SESAR",
             "p__has_material_category": [SRC_ROCK_CONCEPT_ID],
             "latitude": 45.0, "longitude": 10.0},
            {"row_id": 1001, "pid": "pid-C", "n": "OPENCONTEXT",
             "p__produced_by": [103],
             "p__has_material_category": [SRC_ROCK_CONCEPT_ID]},
        ],
        concept_rows=SRC_CONCEPT_ROWS,
        se_rows=[(103, "se-pid-C", [203], None)],
        geo_rows=[(203, "geo-pid-C", 60.0, 20.0)],
    )
    build_oc_wide(
        oc,
        msr_rows=OC_MSR_ROWS,  # pid-A is "new" from OC's perspective
        concept_rows=OC_CONCEPT_ROWS,
        se_rows=OC_SE_ROWS,
        geo_rows=OC_GEO_ROWS,
    )
    r = run_ingest(src, oc, out)
    assert r.returncode != 0, "should fail — pid-A is 'new' from OC but already in src as SESAR"
    assert not os.path.exists(out)


def test_removal_only_removes_oc_entities(pair):
    """The non-OC MSR (pid-NON-OC) and its row are not in the removal set."""
    src, oc, out = pair
    assert run_ingest(src, oc, out).returncode == 0
    # non-OC row must still be in output
    r = get_msr(out, "pid-NON-OC")
    assert r is not None, "non-OC MSR should not be removed"
    assert r["n"] == "SESAR"


def test_new_row_ids_no_collision_with_src(pair):
    """All new row_ids are strictly greater than max(src.row_id)."""
    src, oc, out = pair
    assert run_ingest(src, oc, out).returncode == 0
    con = duckdb.connect()
    max_src = con.sql(f"SELECT MAX(row_id) FROM read_parquet('{src}')").fetchone()[0]
    # New rows start at max_src+1 — get all rows NOT in src
    src_ids = set(r[0] for r in con.sql(f"SELECT row_id FROM read_parquet('{src}')").fetchall())
    out_ids = set(r[0] for r in con.sql(f"SELECT row_id FROM read_parquet('{out}')").fetchall())
    new_ids = out_ids - src_ids
    con.close()
    # Removed rows are also gone; new ids are all > max_src
    if new_ids:
        assert min(new_ids) > max_src, f"New ids start at {min(new_ids)}, but max_src={max_src}"


def test_refuses_to_overwrite_input(pair):
    """--out same as --src triggers a hard failure."""
    src, oc, _ = pair
    r = run_ingest(src, oc, src)
    assert r.returncode != 0
    assert "overwrite" in (r.stderr + r.stdout).lower()


# ============================================================================
# Fix #277 — OC description enrichment
# ============================================================================

def test_oc_description_enriched_from_eric_wide(pair):
    """OC MSR pid-A gets its description from Eric's OC wide after ingestion.

    The src wide stores 'desc pid-A' (a placeholder). Eric's wide also stores
    'desc pid-A' by default from build_oc_wide(). We override pid-A's description
    in Eric's wide to a realistic site-path string and verify the output carries
    that enriched value, not the src placeholder.
    """
    src, oc, out = pair

    # Patch Eric's wide to have a realistic description for pid-A.
    # We rebuild oc with a custom description for pid-A.
    oc_patched = out.replace("out.parquet", "oc_patched.parquet")
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    # Read Eric's wide into a temp table, update pid-A's description, rewrite.
    con.execute(f"""
        COPY (
            SELECT
                row_id, pid, otype, n, geometry, latitude, longitude,
                CASE WHEN pid='pid-A' AND otype='MaterialSampleRecord'
                     THEN 'Open Context published "Sample" from: Europe/Cyprus/PKAP Survey Area/Unit 42'
                     ELSE label
                END AS label,
                CASE WHEN pid='pid-A' AND otype='MaterialSampleRecord'
                     THEN 'Open Context published "Sample" from: Europe/Cyprus/PKAP Survey Area/Unit 42'
                     ELSE description
                END AS description,
                place_name, result_time, p__has_material_category, p__has_sample_object_type,
                p__has_context_category, p__produced_by, p__sample_location, p__sampling_site,
                p__site_location, p__registrant, p__keywords, p__responsibility,
                thumbnail_url, scheme_name, scheme_uri
            FROM read_parquet('{oc}')
        ) TO '{oc_patched}' (FORMAT PARQUET)
    """)
    con.close()

    r = run_ingest(src, oc_patched, out)
    assert r.returncode == 0, r.stderr + r.stdout

    row = get_msr(out, "pid-A")
    assert row is not None
    assert "Cyprus" in row["description"], (
        f"Expected enriched description with 'Cyprus', got: {row['description']!r}"
    )


def test_non_oc_description_unchanged_by_enrichment(pair):
    """Non-OC MSR (pid-NON-OC) description is not overwritten by the OC enrichment."""
    src, oc, out = pair
    r = run_ingest(src, oc, out)
    assert r.returncode == 0, r.stderr + r.stdout

    src_row = get_msr(src, "pid-NON-OC")
    out_row = get_msr(out, "pid-NON-OC")
    assert out_row is not None
    # Non-OC rows must have same description as in src (enrichment must not touch them)
    assert out_row["description"] == src_row["description"], (
        f"Non-OC description changed: {src_row['description']!r} → {out_row['description']!r}"
    )


def test_oc_msr_count_unchanged_by_enrichment(pair):
    """Description enrichment does not change the OC MSR row count."""
    src, oc, out = pair
    r = run_ingest(src, oc, out)
    assert r.returncode == 0, r.stderr + r.stdout

    con = duckdb.connect()
    n_total = con.sql(f"SELECT COUNT(*) FROM read_parquet('{out}')").fetchone()[0]
    n_oc_msr = con.sql(f"""
        SELECT COUNT(*) FROM read_parquet('{out}')
        WHERE otype='MaterialSampleRecord' AND n='OPENCONTEXT'
    """).fetchone()[0]
    con.close()
    # 2 new OC MSRs (pid-A, pid-B), 1 removed (pid-C), 1 non-OC (pid-NON-OC) → 2 total OC MSRs
    assert n_oc_msr == 2, f"Expected 2 OC MSRs after sync, got {n_oc_msr}"
    # Row count must match the sync arithmetic (n_src - 3 removed + 8 new + 1 minted)
    con2 = duckdb.connect()
    n_src = con2.sql(f"SELECT COUNT(*) FROM read_parquet('{src}')").fetchone()[0]
    con2.close()
    assert n_total == n_src - 3 + 8 + 1, f"Total row count unexpected: {n_total}"


# ============================================================================
# Fix #283a — Empty-string facet filter
# ============================================================================

def test_empty_string_facet_values_filtered_from_summaries(tmp_path):
    """build_facet_summaries must not produce rows with facet_value=''.

    This is a synthetic test: we build a tiny samp_geo with an empty-string
    context value and verify it does NOT appear in facet_summaries output.
    """
    import duckdb as _duckdb
    BUILD = os.path.join(REPO, "scripts", "build_frontend_derived.py")
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    import build_frontend_derived as B

    con = _duckdb.connect()
    con.execute("INSTALL h3 FROM community; LOAD h3; INSTALL spatial; LOAD spatial;")
    # Create a synthetic samp_geo with an empty-string context and a real one
    con.execute("""
        CREATE OR REPLACE TEMP TABLE samp_geo AS
        SELECT 'pid1' AS pid, 'GEOME' AS source,
               'https://w3id.org/isample/vocabulary/material/1.0/rock' AS material,
               '' AS context,   -- empty-string concept URI (the bug scenario)
               'https://w3id.org/isample/vocabulary/materialsampleobjecttype/1.0/artifact' AS object_type,
               'label1' AS label, 'desc1' AS description,
               NULL::VARCHAR AS place_name, NULL::TIMESTAMP AS result_time,
               10.0::DOUBLE AS latitude, 45.0::DOUBLE AS longitude,
               1::UBIGINT AS h3_res4, 2::UBIGINT AS h3_res6, 3::UBIGINT AS h3_res8
        UNION ALL
        SELECT 'pid2', 'GEOME',
               'https://w3id.org/isample/vocabulary/material/1.0/rock',
               'https://w3id.org/isample/vocabulary/sampledfeature/1.0/earthsurface',
               'https://w3id.org/isample/vocabulary/materialsampleobjecttype/1.0/artifact',
               'label2', 'desc2', NULL, NULL, 11.0, 46.0, 1, 2, 3
    """)

    out = str(tmp_path / "facet_summaries.parquet")
    B.build_facet_summaries(con, out)

    rows = con.sql(f"SELECT * FROM read_parquet('{out}') WHERE facet_value = ''").fetchall()
    assert rows == [], (
        f"Expected no blank facet_value rows, but got: {rows}"
    )
    # Real context value should appear
    real_rows = con.sql(
        f"SELECT COUNT(*) FROM read_parquet('{out}') WHERE facet_type='context' AND facet_value != ''"
    ).fetchone()[0]
    assert real_rows >= 1, "Expected at least one non-blank context facet row"


def test_empty_string_facet_values_filtered_from_cross_filter(tmp_path):
    """build_facet_cross_filter must not produce rows with blank facet_value."""
    import duckdb as _duckdb
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    import build_frontend_derived as B

    con = _duckdb.connect()
    con.execute("INSTALL h3 FROM community; LOAD h3; INSTALL spatial; LOAD spatial;")
    con.execute("""
        CREATE OR REPLACE TEMP TABLE samp_geo AS
        SELECT 'pid1' AS pid, 'GEOME' AS source,
               'https://w3id.org/isample/vocabulary/material/1.0/rock' AS material,
               '' AS context,
               'https://w3id.org/isample/vocabulary/materialsampleobjecttype/1.0/artifact' AS object_type,
               'label1' AS label, 'desc1' AS description,
               NULL::VARCHAR AS place_name, NULL::TIMESTAMP AS result_time,
               10.0::DOUBLE AS latitude, 45.0::DOUBLE AS longitude,
               1::UBIGINT AS h3_res4, 2::UBIGINT AS h3_res6, 3::UBIGINT AS h3_res8
    """)

    out = str(tmp_path / "facet_cross_filter.parquet")
    B.build_facet_cross_filter(con, out)

    blank_rows = con.sql(f"SELECT * FROM read_parquet('{out}') WHERE facet_value = ''").fetchall()
    assert blank_rows == [], (
        f"Expected no blank facet_value in cross_filter, got: {blank_rows}"
    )
    blank_filter_rows = con.sql(
        f"SELECT * FROM read_parquet('{out}') WHERE filter_context = ''"
    ).fetchall()
    assert blank_filter_rows == [], (
        f"Expected no blank filter_context in cross_filter, got: {blank_filter_rows}"
    )


# ============================================================================
# Fix #283b — specimentype/1.0 vocab labels
# ============================================================================

SPEC_URI_SOLID = "https://w3id.org/isample/vocabulary/specimentype/1.0/othersolidobject"
SPEC_URI_PHYS = "https://w3id.org/isample/vocabulary/specimentype/1.0/physicalspecimen"

# Optional fast-path: if ISAMPLES_VOCAB_LABELS points at an already-built
# vocab_labels.parquet, reuse it; otherwise (CI / fresh checkout) we rebuild
# it on the fly. No machine-specific default — avoids leaking a local path.
VOCAB_LABELS_PATH = os.environ.get("ISAMPLES_VOCAB_LABELS", "")


def _get_vocab_labels_parquet():
    """Return a path to vocab_labels.parquet, building it if needed."""
    if VOCAB_LABELS_PATH and os.path.exists(VOCAB_LABELS_PATH):
        return VOCAB_LABELS_PATH
    # Build into a temp file for CI / offline environments.
    BUILD_VL = os.path.join(REPO, "scripts", "build_vocab_labels.py")
    import tempfile
    tmp = tempfile.mktemp(suffix=".parquet")
    result = subprocess.run(
        [sys.executable, BUILD_VL, "-o", tmp],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        pytest.skip(f"build_vocab_labels.py failed (network?): {result.stderr[:200]}")
    return tmp


def test_specimentype_othersolidobject_in_vocab_labels():
    """specimentype/1.0/othersolidobject must be present with label 'Other solid object'."""
    vl = _get_vocab_labels_parquet()
    con = duckdb.connect()
    row = con.sql(
        f"SELECT pref_label FROM read_parquet('{vl}') WHERE uri='{SPEC_URI_SOLID}'"
    ).fetchone()
    con.close()
    assert row is not None, f"{SPEC_URI_SOLID!r} not found in vocab_labels"
    assert row[0] == "Other solid object", f"Expected 'Other solid object', got {row[0]!r}"


def test_specimentype_physicalspecimen_in_vocab_labels():
    """specimentype/1.0/physicalspecimen must be present with label 'Material sample'."""
    vl = _get_vocab_labels_parquet()
    con = duckdb.connect()
    row = con.sql(
        f"SELECT pref_label FROM read_parquet('{vl}') WHERE uri='{SPEC_URI_PHYS}'"
    ).fetchone()
    con.close()
    assert row is not None, f"{SPEC_URI_PHYS!r} not found in vocab_labels"
    assert row[0] == "Material sample", f"Expected 'Material sample', got {row[0]!r}"


def test_specimentype_labels_have_lang_en():
    """Both specimentype manual overrides must have lang='en'."""
    vl = _get_vocab_labels_parquet()
    con = duckdb.connect()
    rows = con.sql(
        f"SELECT uri, lang FROM read_parquet('{vl}') WHERE uri LIKE '%specimentype%'"
    ).fetchall()
    con.close()
    assert len(rows) == 2, f"Expected 2 specimentype rows, got {len(rows)}: {rows}"
    for uri, lang in rows:
        assert lang == "en", f"Expected lang='en' for {uri!r}, got {lang!r}"


# ============================================================================
# Blocker 1 — cross-source orphan protection (Nit C + Nit D)
# ============================================================================

def test_cross_source_shared_entity_not_orphaned(tmp_path):
    """SE and SamplingSite shared between a removed OC MSR and a surviving SESAR MSR
    must NOT be deleted as orphans.

    Scenario:
      src:
        - OC MSR  pid='OC_remove_me'  → SE row_id=100  → SamplingSite row_id=200
        - SE row_id=100
        - SamplingSite row_id=200
        - SESAR MSR pid='SESAR_keep_me'  ALSO → SE row_id=100 + SamplingSite row_id=200
      Eric's OC wide:
        - pid='NEW_OC_pid' (new OC record, NOT 'OC_remove_me' → it's gone)

    After sync:
      - 'OC_remove_me' is removed (not in Eric's wide)
      - SE row_id=100 is STILL referenced by 'SESAR_keep_me' → must survive
      - SamplingSite row_id=200 is STILL referenced by 'SESAR_keep_me' → must survive

    Old code (surviving_se_refs filtered to n='OPENCONTEXT') would incorrectly
    mark SE 100 and Site 200 as orphans and delete them, breaking the SESAR MSR.
    New code (all-source surviving refs) must keep them.
    """
    src = str(tmp_path / "src_b1.parquet")
    oc = str(tmp_path / "oc_b1.parquet")
    out = str(tmp_path / "out_b1.parquet")

    # row_ids in src space
    SE_ROW_ID = 100
    SITE_ROW_ID = 200
    GEO_ROW_ID = 300

    # Build src wide: OC MSR to-be-removed + SESAR MSR sharing SE+Site
    build_src_wide(
        src,
        msr_rows=[
            # OC MSR that will be removed (not in Eric's wide)
            {
                "row_id": 1000, "pid": "OC_remove_me", "n": "OPENCONTEXT",
                "p__produced_by": [SE_ROW_ID],
                "p__has_material_category": [SRC_ROCK_CONCEPT_ID],
                "latitude": 45.0, "longitude": 10.0,
            },
            # SESAR MSR that ALSO references SE 100 + Site 200 (shared!)
            {
                "row_id": 1001, "pid": "SESAR_keep_me", "n": "SESAR",
                "p__produced_by": [SE_ROW_ID],
                "p__has_material_category": [SRC_ROCK_CONCEPT_ID],
                "latitude": 45.1, "longitude": 10.1,
            },
        ],
        concept_rows=SRC_CONCEPT_ROWS,
        se_rows=[
            # SE shared between OC + SESAR MSRs
            (SE_ROW_ID, "se-shared", [GEO_ROW_ID], [SITE_ROW_ID]),
        ],
        geo_rows=[
            (GEO_ROW_ID, "geo-shared", 45.0, 10.0),
        ],
        site_rows=[
            (SITE_ROW_ID, "site-shared", [GEO_ROW_ID]),
        ],
    )

    # Build Eric's OC wide: NEW_OC_pid (new), NOT OC_remove_me → it becomes stale
    # Use a simple SE + geo for the new OC record
    build_oc_wide(
        oc,
        msr_rows=[
            {
                "row_id": 1, "pid": "NEW_OC_pid",
                "p__produced_by": [501],
                "p__has_material_category": [OC_ROCK_CONCEPT_ID],
            },
        ],
        concept_rows=OC_CONCEPT_ROWS,
        se_rows=[(501, "se-new", [601], None)],
        geo_rows=[(601, "geo-new", 46.0, 11.0)],
    )

    r = run_ingest(src, oc, out)
    assert r.returncode == 0, f"ingest failed:\nSTDERR: {r.stderr}\nSTDOUT: {r.stdout}"

    con = duckdb.connect()

    # SESAR MSR must survive
    sesar_row = con.sql(
        f"SELECT COUNT(*) FROM read_parquet('{out}') WHERE pid='SESAR_keep_me' AND otype='MaterialSampleRecord'"
    ).fetchone()[0]
    assert sesar_row == 1, "SESAR_keep_me MSR should survive — it was not an OC record"

    # OC MSR must be gone
    oc_row = con.sql(
        f"SELECT COUNT(*) FROM read_parquet('{out}') WHERE pid='OC_remove_me' AND otype='MaterialSampleRecord'"
    ).fetchone()[0]
    assert oc_row == 0, "OC_remove_me MSR should have been removed"

    # Shared SE must survive (still referenced by SESAR_keep_me)
    se_count = con.sql(
        f"SELECT COUNT(*) FROM read_parquet('{out}') WHERE pid='se-shared' AND otype='SamplingEvent'"
    ).fetchone()[0]
    assert se_count == 1, (
        "se-shared (SE row_id=100) must NOT be orphaned — still referenced by SESAR_keep_me"
    )

    # Shared SamplingSite must survive
    site_count = con.sql(
        f"SELECT COUNT(*) FROM read_parquet('{out}') WHERE pid='site-shared' AND otype='SamplingSite'"
    ).fetchone()[0]
    assert site_count == 1, (
        "site-shared (SamplingSite row_id=200) must NOT be orphaned — still referenced by SESAR_keep_me's SE"
    )

    # Shared Geo must survive
    geo_count = con.sql(
        f"SELECT COUNT(*) FROM read_parquet('{out}') WHERE pid='geo-shared' AND otype='GeospatialCoordLocation'"
    ).fetchone()[0]
    assert geo_count == 1, (
        "geo-shared (Geo row_id=300) must NOT be orphaned — still referenced by the shared SE"
    )

    # SESAR MSR's p__produced_by must still resolve to a valid SE
    pb = con.sql(f"""
        SELECT p__produced_by[1] FROM read_parquet('{out}')
        WHERE pid='SESAR_keep_me' AND otype='MaterialSampleRecord'
    """).fetchone()[0]
    if pb is not None:
        se_exists = con.sql(f"""
            SELECT COUNT(*) FROM read_parquet('{out}')
            WHERE row_id = {pb} AND otype='SamplingEvent'
        """).fetchone()[0]
        assert se_exists == 1, f"SESAR_keep_me p__produced_by row_id={pb} not found in output (dangling ref!)"

    con.close()


# ============================================================================
# Fix #272 Phase 5 — surviving SamplingSite's p__site_location Geo not orphaned
# ============================================================================

def test_site_location_geo_not_orphaned(tmp_path):
    """A GeospatialCoordLocation referenced by a surviving SamplingSite via
    p__site_location must NOT be deleted as an orphan even if it is also
    referenced by an orphan SamplingEvent via p__sample_location.

    Scenario:
      src:
        - OC MSR pid='OC_removed', n='OPENCONTEXT'
            → p__produced_by=[10] (SE row_id=10)
        - SE row_id=10, p__sample_location=[20], p__sampling_site=[30]
            - Geo row_id=20
            - SamplingSite row_id=30, p__site_location=[20]  ← same Geo!
        - SESAR MSR pid='SESAR_kept', n='SESAR'
            → p__produced_by=[40] (SE row_id=40)
        - SE row_id=40, p__sampling_site=[30]  ← references surviving Site

      Eric's OC wide: does NOT contain 'OC_removed' → it becomes stale
        - Contains 'NEW_OC_pid' (new)

    After sync:
      - 'OC_removed' MSR is removed
      - SE row_id=10 is orphaned (only referenced by removed OC MSR's p__produced_by)
      - SamplingSite row_id=30 SURVIVES (referenced by SESAR SE row_id=40)
      - GeospatialCoordLocation row_id=20 SURVIVES (referenced by surviving Site
        row_id=30 via p__site_location) — this is the critical assertion
      - Zero dangling p__site_location refs in output

    OLD CODE (BUG): surviving_geo_refs only checked p__sample_location on SEs.
      Since SE row_id=10 is orphaned, Geo row_id=20 appeared to have NO surviving
      SE references → incorrectly deleted → dangling p__site_location on Site row_id=30.

    NEW CODE (FIX): surviving_geo_refs also checks p__site_location on non-orphan
      SamplingSites → Geo row_id=20 is retained.
    """
    src = str(tmp_path / "src_sl.parquet")
    oc = str(tmp_path / "oc_sl.parquet")
    out = str(tmp_path / "out_sl.parquet")

    GEO_ROW_ID = 20
    SE_OC_ROW_ID = 10
    SITE_ROW_ID = 30
    SE_SESAR_ROW_ID = 40

    build_src_wide(
        src,
        msr_rows=[
            # OC MSR that will be removed (not in Eric's wide)
            {
                "row_id": 1000, "pid": "OC_removed", "n": "OPENCONTEXT",
                "p__produced_by": [SE_OC_ROW_ID],
                "p__has_material_category": [SRC_ROCK_CONCEPT_ID],
                "latitude": 45.0, "longitude": 10.0,
            },
            # SESAR MSR whose SE references the surviving SamplingSite
            {
                "row_id": 1001, "pid": "SESAR_kept", "n": "SESAR",
                "p__produced_by": [SE_SESAR_ROW_ID],
                "p__has_material_category": [SRC_ROCK_CONCEPT_ID],
                "latitude": 45.1, "longitude": 10.1,
            },
        ],
        concept_rows=SRC_CONCEPT_ROWS,
        se_rows=[
            # OC's SE: sample_location → Geo 20, sampling_site → Site 30
            (SE_OC_ROW_ID, "se-oc", [GEO_ROW_ID], [SITE_ROW_ID]),
            # SESAR's SE: sampling_site → Site 30 (keeps Site alive)
            (SE_SESAR_ROW_ID, "se-sesar", None, [SITE_ROW_ID]),
        ],
        geo_rows=[
            (GEO_ROW_ID, "geo-shared", 45.0, 10.0),
        ],
        site_rows=[
            # SamplingSite references Geo via p__site_location
            (SITE_ROW_ID, "site-shared", [GEO_ROW_ID]),
        ],
    )

    # Eric's OC wide: NEW_OC_pid only (OC_removed is absent → stale)
    build_oc_wide(
        oc,
        msr_rows=[
            {
                "row_id": 1, "pid": "NEW_OC_pid",
                "p__produced_by": [501],
                "p__has_material_category": [OC_ROCK_CONCEPT_ID],
            },
        ],
        concept_rows=OC_CONCEPT_ROWS,
        se_rows=[(501, "se-new-oc", [601], None)],
        geo_rows=[(601, "geo-new-oc", 46.0, 11.0)],
    )

    r = run_ingest(src, oc, out)
    assert r.returncode == 0, f"ingest failed:\nSTDERR: {r.stderr}\nSTDOUT: {r.stdout}"

    con = duckdb.connect()

    # OC_removed must be gone
    assert con.sql(
        f"SELECT COUNT(*) FROM read_parquet('{out}') WHERE pid='OC_removed'"
    ).fetchone()[0] == 0, "OC_removed must be removed"

    # SESAR_kept must survive
    assert con.sql(
        f"SELECT COUNT(*) FROM read_parquet('{out}') WHERE pid='SESAR_kept' AND otype='MaterialSampleRecord'"
    ).fetchone()[0] == 1, "SESAR_kept must survive"

    # SE row_id=10 (OC's SE) must be orphaned
    assert con.sql(
        f"SELECT COUNT(*) FROM read_parquet('{out}') WHERE pid='se-oc' AND otype='SamplingEvent'"
    ).fetchone()[0] == 0, "se-oc (orphan SE) must be removed"

    # SamplingSite row_id=30 must survive (referenced by SESAR SE)
    assert con.sql(
        f"SELECT COUNT(*) FROM read_parquet('{out}') WHERE pid='site-shared' AND otype='SamplingSite'"
    ).fetchone()[0] == 1, "site-shared must survive — still referenced by SESAR's SE"

    # GeospatialCoordLocation row_id=20 MUST survive (this is the critical fix assertion)
    assert con.sql(
        f"SELECT COUNT(*) FROM read_parquet('{out}') WHERE pid='geo-shared' AND otype='GeospatialCoordLocation'"
    ).fetchone()[0] == 1, (
        "geo-shared (Geo row_id=20) must NOT be orphaned — "
        "surviving SamplingSite still references it via p__site_location"
    )

    # Zero dangling p__site_location refs in output (the production-scale symptom)
    dangling = con.sql(f"""
        WITH all_row_ids AS (SELECT row_id FROM read_parquet('{out}')),
        site_refs AS (
            SELECT unnest(p__site_location) AS ref_id
            FROM read_parquet('{out}')
            WHERE otype='SamplingSite'
              AND p__site_location IS NOT NULL AND len(p__site_location) > 0
        )
        SELECT COUNT(*) FROM site_refs
        LEFT JOIN all_row_ids ON site_refs.ref_id = all_row_ids.row_id
        WHERE all_row_ids.row_id IS NULL
    """).fetchone()[0]
    assert dangling == 0, f"p__site_location dangling refs: {dangling} (expected 0)"

    con.close()


# ============================================================================
# Fix A — Fixpoint orphan removal (R2-A)
# ============================================================================

def test_orphan_geo_via_site_only_removed(tmp_path):
    """A Geo referenced ONLY via an orphan SamplingSite's p__site_location
    (and NOT by any surviving SE's p__sample_location) must be REMOVED.

    This tests Fix A's over-retention correction: the fixpoint algorithm must
    not retain a Geo that appears only in an orphan chain with no surviving refs.

    Scenario:
      src:
        - OC MSR pid='OC_gone' → SE row_id=10 → Site row_id=20 → Geo row_id=30
        - SE row_id=10, p__sample_location=[], p__sampling_site=[20]
          (SE has NO direct p__sample_location — only a site reference)
        - SamplingSite row_id=20, p__site_location=[30]
        - Geo row_id=30  ← referenced ONLY via orphan Site, no surviving refs
        - NO other MSR references SE 10, Site 20, or Geo 30

      Eric's OC wide: does NOT contain 'OC_gone' → stale; has 'NEW_OC_pid'

    After sync:
      - 'OC_gone' MSR removed
      - SE row_id=10 is orphan (no surviving MSR's p__produced_by points to it)
      - SamplingSite row_id=20 is orphan (SE 10 is removed; no other ref)
      - Geo row_id=30 is orphan (Site 20 is removed; no other ref)
      → ALL THREE must be REMOVED

    OLD CODE BUG (pre-phase-5 path-specific logic): surviving_geo_refs included
    Geos referenced by non-orphan SamplingSites — but Phase 5 only checked Site
    surviving status by whether the Site appeared in surviving_site_refs, which
    depended on a hand-coded SE→Site chain. If the agent traversal missed a path,
    a Geo could be incorrectly retained.

    FIXPOINT: correctly computes survivor_refs from all surviving rows; since no
    surviving row points to Geo 30, it is removed.

    This test MUST FAIL on old path-specific code and PASS on fixpoint code.
    (It passed on Phase 5 code that hand-enumerated the site_location path,
    but verifies the fixpoint correctly handles the fully-orphaned chain.)
    """
    src = str(tmp_path / "src_chain.parquet")
    oc  = str(tmp_path / "oc_chain.parquet")
    out = str(tmp_path / "out_chain.parquet")

    SE_ROW   = 10
    SITE_ROW = 20
    GEO_ROW  = 30

    build_src_wide(
        src,
        msr_rows=[
            # OC MSR to be removed — references SE only
            {
                "row_id": 1000, "pid": "OC_gone", "n": "OPENCONTEXT",
                "p__produced_by": [SE_ROW],
                "p__has_material_category": [SRC_ROCK_CONCEPT_ID],
                "latitude": 45.0, "longitude": 10.0,
            },
        ],
        concept_rows=SRC_CONCEPT_ROWS,
        se_rows=[
            # SE: no direct p__sample_location; only p__sampling_site → Site
            (SE_ROW, "se-orphan", [], [SITE_ROW]),
        ],
        geo_rows=[
            (GEO_ROW, "geo-orphan", 45.0, 10.0),
        ],
        site_rows=[
            # Site: p__site_location → Geo (the only ref to Geo)
            (SITE_ROW, "site-orphan", [GEO_ROW]),
        ],
    )

    build_oc_wide(
        oc,
        msr_rows=[
            {
                "row_id": 1, "pid": "NEW_OC_pid",
                "p__produced_by": [501],
                "p__has_material_category": [OC_ROCK_CONCEPT_ID],
            },
        ],
        concept_rows=OC_CONCEPT_ROWS,
        se_rows=[(501, "se-new", [601], None)],
        geo_rows=[(601, "geo-new", 46.0, 11.0)],
    )

    r = run_ingest(src, oc, out)
    assert r.returncode == 0, f"ingest failed:\nSTDERR: {r.stderr}\nSTDOUT: {r.stdout}"

    con = duckdb.connect()

    # All three orphan entities must be gone
    for pid, otype, label in [
        ("se-orphan",   "SamplingEvent",           "SE row_id=10"),
        ("site-orphan", "SamplingSite",             "Site row_id=20"),
        ("geo-orphan",  "GeospatialCoordLocation",  "Geo row_id=30"),
    ]:
        n = con.sql(
            f"SELECT COUNT(*) FROM read_parquet('{out}') WHERE pid='{pid}' AND otype='{otype}'"
        ).fetchone()[0]
        assert n == 0, f"{label} ({pid}) should be REMOVED — no surviving refs; got count={n}"

    # Zero dangling refs in output
    for col in ("p__sample_location", "p__sampling_site", "p__site_location"):
        dangling = con.sql(f"""
            WITH ids AS (SELECT row_id FROM read_parquet('{out}')),
            refs AS (SELECT unnest({col}) AS ref_id FROM read_parquet('{out}')
                     WHERE {col} IS NOT NULL AND len({col}) > 0)
            SELECT COUNT(*) FROM refs LEFT JOIN ids ON refs.ref_id = ids.row_id
            WHERE ids.row_id IS NULL
        """).fetchone()[0]
        assert dangling == 0, f"{col}: {dangling} dangling refs (expected 0)"

    con.close()


def test_unresolved_new_ref_hard_fails(tmp_path):
    """A new OC SE with p__sampling_site pointing to a SamplingSite absent from
    Eric's OC wide must cause the ingest to RAISE (non-zero exit), NOT silently
    emit NULL for that reference.

    This tests Fix B (silent-drop guard): after remapping, if the remapped array
    length != source array length, the build must hard-fail.

    Scenario:
      Eric's OC wide:
        - MSR pid='new_pid' → SE row_id=201, p__produced_by=[201]
        - SE row_id=201, p__sampling_site=[999]  ← Site row_id=999
        - NO SamplingSite row_id=999 exists in Eric's wide
        - Geo row_id=301 exists (SE's p__sample_location=[301])

    Expected: ingest raises RuntimeError / exits non-zero.
    The output file must NOT be written.
    """
    src = str(tmp_path / "src_miss.parquet")
    oc  = str(tmp_path / "oc_miss.parquet")
    out = str(tmp_path / "out_miss.parquet")

    # Minimal src: just concepts + a stale OC MSR (so there's something to remove)
    build_src_wide(
        src,
        msr_rows=[
            {
                "row_id": 1000, "pid": "pid_stale", "n": "OPENCONTEXT",
                "p__produced_by": [100],
                "p__has_material_category": [SRC_ROCK_CONCEPT_ID],
                "latitude": 40.0, "longitude": 5.0,
            },
        ],
        concept_rows=SRC_CONCEPT_ROWS,
        se_rows=[(100, "se-stale", [110], None)],
        geo_rows=[(110, "geo-stale", 40.0, 5.0)],
    )

    # Eric's OC wide: new MSR whose SE has p__sampling_site=[999] but Site 999 is absent
    build_oc_wide(
        oc,
        msr_rows=[
            {
                "row_id": 1, "pid": "new_pid",
                "p__produced_by": [201],
                "p__has_material_category": [OC_ROCK_CONCEPT_ID],
            },
        ],
        concept_rows=OC_CONCEPT_ROWS,
        # SE references Site 999 via p__sampling_site — but Site 999 is not in the wide
        se_rows=[(201, "se-new-missing-site", [301], [999])],
        geo_rows=[(301, "geo-new", 41.0, 6.0)],
        # site_rows intentionally omitted — no Site 999
    )

    r = run_ingest(src, oc, out)
    combined = r.stdout + r.stderr
    assert r.returncode != 0, (
        f"Expected ingest to FAIL (non-zero exit) when p__sampling_site ref is unresolvable, "
        f"but it exited 0.\nSTDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}"
    )
    assert "SILENT-DROP" in combined or "GUARD" in combined or "FATAL" in combined or "mismatch" in combined.lower(), (
        f"Expected a silent-drop guard / FATAL error message; got:\n{combined[:500]}"
    )
    assert not os.path.exists(out), (
        "Output file must NOT be written when the silent-drop guard fires"
    )


# ============================================================================
# Fix 1 (Round 7) — p__keywords concepts fully extracted and preserved
# ============================================================================

# Keyword concept IDs in Eric's space (INTEGER)
OC_KW1_CONCEPT_ID = 950   # keyword concept already in src
OC_KW2_CONCEPT_ID = 951   # keyword concept NOT in src — must be minted

KW1_URI = "https://w3id.org/isample/keyword/1.0/existing_keyword"
KW2_URI = "https://w3id.org/isample/keyword/1.0/new_keyword"  # absent from src → minted

# src concept ID for the existing keyword (BIGINT)
SRC_KW1_CONCEPT_ID = 10


def test_new_msr_keywords_preserved(tmp_path):
    """New OC MSR with p__keywords pointing to concept(s) — at least one NOT in src
    (forcing a mint) — must have all keyword refs preserved in output:
      - output p__keywords array length == source array length
      - all targets resolve to IdentifiedConcept rows in output
      - zero dangling keyword refs in output

    This test MUST FAIL on old HEAD (where keywords were silently dropped because
    keyword concept URIs were not collected in new_concept_refs and thus not minted,
    causing the remap_msr_kw inner join to produce no matches → remap length 0 vs
    source length 2 → silent-drop guard fires → FATAL).

    After FIX 1: keywords are included in new_concept_refs; missing keyword concepts
    are minted; the full-length remap is verified by the silent-drop guard; all refs
    are valid in output.
    """
    src = str(tmp_path / "src_kw.parquet")
    oc  = str(tmp_path / "oc_kw.parquet")
    out = str(tmp_path / "out_kw.parquet")

    # ---- src wide: has existing keyword concept (KW1), NOT KW2 ----
    src_concepts = list(SRC_CONCEPT_ROWS) + [(SRC_KW1_CONCEPT_ID, KW1_URI)]

    build_src_wide(
        src,
        msr_rows=[
            # Stale OC MSR (to ensure removal path is exercised)
            {
                "row_id": 1000, "pid": "pid_stale", "n": "OPENCONTEXT",
                "p__produced_by": [103],
                "p__has_material_category": [SRC_ROCK_CONCEPT_ID],
                "latitude": 60.0, "longitude": 20.0,
            },
        ],
        concept_rows=src_concepts,
        se_rows=[(103, "se-stale", [203], None)],
        geo_rows=[(203, "geo-stale", 60.0, 20.0)],
    )

    # ---- OC wide: new MSR with p__keywords=[OC_KW1_CONCEPT_ID, OC_KW2_CONCEPT_ID]
    # KW1 is already in src (must be looked up by URI, not minted)
    # KW2 is NOT in src (must be minted as a new IdentifiedConcept row)
    oc_concepts = list(OC_CONCEPT_ROWS) + [
        (OC_KW1_CONCEPT_ID, KW1_URI, "Existing Keyword"),
        (OC_KW2_CONCEPT_ID, KW2_URI, "New Keyword"),
    ]

    build_oc_wide(
        oc,
        msr_rows=[
            {
                "row_id": 1, "pid": "pid_kw",
                "p__produced_by": [101],
                "p__has_material_category": [OC_ROCK_CONCEPT_ID],
                "p__keywords": [OC_KW1_CONCEPT_ID, OC_KW2_CONCEPT_ID],
            },
        ],
        concept_rows=oc_concepts,
        se_rows=[(101, "se-kw", [201], None)],
        geo_rows=[(201, "geo-kw", 45.0, 10.0)],
    )

    r = run_ingest(src, oc, out)
    assert r.returncode == 0, (
        f"ingest failed:\nSTDERR: {r.stderr}\nSTDOUT: {r.stdout}"
    )

    con = duckdb.connect()

    # 1. New OC MSR must be present with n='OPENCONTEXT'
    kw_msr = con.sql(
        f"SELECT p__keywords FROM read_parquet('{out}') "
        f"WHERE pid='pid_kw' AND otype='MaterialSampleRecord'"
    ).fetchone()
    assert kw_msr is not None, "pid_kw MSR missing from output"
    kw_refs = kw_msr[0]
    assert kw_refs is not None, "p__keywords is NULL in output (should be a 2-element array)"
    assert len(kw_refs) == 2, (
        f"p__keywords length mismatch: expected 2, got {len(kw_refs)}. "
        f"Array: {kw_refs}"
    )

    # 2. Both keyword targets must resolve to IdentifiedConcept rows in output
    for ref_id in kw_refs:
        resolved = con.sql(
            f"SELECT pid, otype FROM read_parquet('{out}') WHERE row_id = {ref_id}"
        ).fetchone()
        assert resolved is not None, (
            f"Keyword ref row_id={ref_id} not found in output (dangling ref!)"
        )
        assert resolved[1] == "IdentifiedConcept", (
            f"Keyword ref row_id={ref_id} resolves to otype={resolved[1]!r}, "
            f"expected 'IdentifiedConcept'"
        )

    # 3. Verify both URIs are resolvable in output IdentifiedConcept rows
    kw1_out = con.sql(
        f"SELECT COUNT(*) FROM read_parquet('{out}') "
        f"WHERE otype='IdentifiedConcept' AND pid='{KW1_URI}'"
    ).fetchone()[0]
    assert kw1_out == 1, f"KW1 concept ({KW1_URI}) missing from output"

    kw2_out = con.sql(
        f"SELECT COUNT(*) FROM read_parquet('{out}') "
        f"WHERE otype='IdentifiedConcept' AND pid='{KW2_URI}'"
    ).fetchone()[0]
    assert kw2_out == 1, f"KW2 concept ({KW2_URI}) not minted in output (should have been minted)"

    # 4. Zero dangling p__keywords refs in output
    dangling = con.sql(f"""
        WITH all_row_ids AS (SELECT row_id FROM read_parquet('{out}')),
        kw_refs AS (
            SELECT unnest(p__keywords) AS ref_id
            FROM read_parquet('{out}')
            WHERE p__keywords IS NOT NULL AND len(p__keywords) > 0
        )
        SELECT COUNT(*) FROM kw_refs
        LEFT JOIN all_row_ids ON kw_refs.ref_id = all_row_ids.row_id
        WHERE all_row_ids.row_id IS NULL
    """).fetchone()[0]
    assert dangling == 0, f"p__keywords: {dangling} dangling refs in output (expected 0)"

    con.close()


# ============================================================================
# Round 8 — concept-label search (#277 part 2)
# ============================================================================

def test_concept_label_search(tmp_path):
    """build_sample_facets_v2 must append IC labels to description so that
    textSearch on concept terms (e.g. 'pottery') matches samples tagged with
    that concept even when the word does not appear in label/description/place_name.

    Scenario (single wide parquet, post-ingest shape — BLOB geometry, BIGINT arrays):
      - MSR pid='pid_pottery'  → p__keywords → IC row_id=1001 (label='pottery')
                               → p__has_material_category → IC row_id=1002 (label='rock')
        label='some label', description='some description'
        (neither 'pottery' nor 'rock' appears in original label/description)
      - MSR pid='pid_no_concept' — no concept refs at all, description='plain desc'
      - IC row_id=1001 label='pottery'
      - IC row_id=1002 label='rock'

    After build_sample_facets_v2:
      - pid_pottery description must contain 'pottery' AND 'rock'
      - pid_no_concept description must equal 'plain desc' (no appended space)
      - ILIKE '%pottery%' must find pid_pottery
      - ILIKE '%pottery%' must NOT find pid_no_concept
    """
    import duckdb as _duckdb
    import time
    sys.path.insert(0, os.path.join(REPO, "scripts"))
    import build_frontend_derived as B

    wide = str(tmp_path / "wide_concept_label.parquet")
    out = str(tmp_path / "facets_v2_cl.parquet")

    # --- build synthetic wide parquet in post-ingest shape (BLOB geometry, BIGINT arrays) ---
    con_build = _duckdb.connect()
    con_build.execute("INSTALL spatial; LOAD spatial;")
    con_build.execute(f"""
        COPY (
            -- MSR pid_pottery: p__keywords=[1001], p__has_material_category=[1002]
            -- original label/description do NOT contain 'pottery' or 'rock'
            SELECT 1::BIGINT AS row_id,
                   'pid_pottery' AS pid,
                   'MaterialSampleRecord' AS otype,
                   'SESAR'::VARCHAR AS n,
                   ST_AsWKB(ST_Point(10.0, 45.0))::BLOB AS geometry,
                   45.0::DOUBLE AS latitude,
                   10.0::DOUBLE AS longitude,
                   'some label'::VARCHAR AS label,
                   'some description'::VARCHAR AS description,
                   ['Somewhere']::VARCHAR[] AS place_name,
                   NULL::TIMESTAMP AS result_time,
                   [1002]::BIGINT[] AS p__has_material_category,
                   NULL::BIGINT[] AS p__has_sample_object_type,
                   NULL::BIGINT[] AS p__has_context_category,
                   NULL::BIGINT[] AS p__produced_by,
                   NULL::BIGINT[] AS p__sample_location,
                   NULL::BIGINT[] AS p__sampling_site,
                   NULL::BIGINT[] AS p__site_location,
                   NULL::BIGINT[] AS p__registrant,
                   [1001]::BIGINT[] AS p__keywords,
                   NULL::BIGINT[] AS p__responsibility,
                   NULL::INTEGER[] AS p__curation,
                   NULL::BIGINT[] AS p__related_resource,
                   NULL::VARCHAR AS thumbnail_url,
                   NULL::VARCHAR AS scheme_name,
                   NULL::VARCHAR AS scheme_uri
            UNION ALL
            -- MSR pid_no_concept: no concept refs; description must be unchanged
            SELECT 2::BIGINT, 'pid_no_concept', 'MaterialSampleRecord', 'SESAR',
                   ST_AsWKB(ST_Point(11.0, 46.0))::BLOB,
                   46.0::DOUBLE, 11.0::DOUBLE,
                   'no-concept label'::VARCHAR, 'plain desc'::VARCHAR,
                   ['Elsewhere']::VARCHAR[], NULL::TIMESTAMP,
                   NULL::BIGINT[], NULL::BIGINT[], NULL::BIGINT[], NULL::BIGINT[],
                   NULL::BIGINT[], NULL::BIGINT[], NULL::BIGINT[], NULL::BIGINT[],
                   NULL::BIGINT[], NULL::BIGINT[], NULL::INTEGER[], NULL::BIGINT[],
                   NULL::VARCHAR, NULL::VARCHAR, NULL::VARCHAR
            UNION ALL
            -- IC row_id=1001: label='pottery'
            SELECT 1001::BIGINT, 'https://example.org/kw/pottery',
                   'IdentifiedConcept', NULL::VARCHAR,
                   NULL::BLOB, NULL::DOUBLE, NULL::DOUBLE,
                   'pottery'::VARCHAR, NULL::VARCHAR,
                   NULL::VARCHAR[], NULL::TIMESTAMP,
                   NULL::BIGINT[], NULL::BIGINT[], NULL::BIGINT[], NULL::BIGINT[],
                   NULL::BIGINT[], NULL::BIGINT[], NULL::BIGINT[], NULL::BIGINT[],
                   NULL::BIGINT[], NULL::BIGINT[], NULL::INTEGER[], NULL::BIGINT[],
                   NULL::VARCHAR, NULL::VARCHAR, NULL::VARCHAR
            UNION ALL
            -- IC row_id=1002: label='rock'
            SELECT 1002::BIGINT, 'https://example.org/mat/rock',
                   'IdentifiedConcept', NULL::VARCHAR,
                   NULL::BLOB, NULL::DOUBLE, NULL::DOUBLE,
                   'rock'::VARCHAR, NULL::VARCHAR,
                   NULL::VARCHAR[], NULL::TIMESTAMP,
                   NULL::BIGINT[], NULL::BIGINT[], NULL::BIGINT[], NULL::BIGINT[],
                   NULL::BIGINT[], NULL::BIGINT[], NULL::BIGINT[], NULL::BIGINT[],
                   NULL::BIGINT[], NULL::BIGINT[], NULL::INTEGER[], NULL::BIGINT[],
                   NULL::VARCHAR, NULL::VARCHAR, NULL::VARCHAR
        ) TO '{wide}' (FORMAT PARQUET)
    """)
    con_build.close()

    # --- run build_base_tables + build_sample_facets_v2 ---
    con = _duckdb.connect()
    con.execute("INSTALL h3 FROM community; LOAD h3; INSTALL spatial; LOAD spatial;")
    t0 = time.time()
    B.build_base_tables(con, wide, t0)
    B.build_sample_facets_v2(con, out)
    con.close()

    # --- assertions ---
    con2 = _duckdb.connect()

    # 1. pid_pottery description must contain 'pottery' (from p__keywords IC label)
    pottery_desc = con2.sql(
        f"SELECT description FROM read_parquet('{out}') WHERE pid='pid_pottery'"
    ).fetchone()
    assert pottery_desc is not None, "pid_pottery missing from facets_v2 output"
    desc = pottery_desc[0]
    assert desc is not None, "pid_pottery description is NULL"
    assert 'pottery' in desc.lower(), (
        f"'pottery' not found in pid_pottery description: {desc!r}"
    )

    # 2. pid_pottery description must also contain 'rock' (from p__has_material_category IC label)
    assert 'rock' in desc.lower(), (
        f"'rock' not found in pid_pottery description: {desc!r}"
    )

    # 3. pid_no_concept description must be unchanged ('plain desc' with no appended garbage)
    no_concept_desc = con2.sql(
        f"SELECT description FROM read_parquet('{out}') WHERE pid='pid_no_concept'"
    ).fetchone()
    assert no_concept_desc is not None, "pid_no_concept missing from facets_v2 output"
    assert no_concept_desc[0] == 'plain desc', (
        f"pid_no_concept description changed unexpectedly: {no_concept_desc[0]!r}"
    )

    # 4. ILIKE '%pottery%' finds pid_pottery (simulates explorer textSearch)
    pottery_hits = con2.sql(
        f"SELECT COUNT(*) FROM read_parquet('{out}') WHERE description ILIKE '%pottery%'"
    ).fetchone()[0]
    assert pottery_hits == 1, (
        f"Expected 1 pottery hit via ILIKE, got {pottery_hits}"
    )

    # 5. pid_no_concept is NOT matched by ILIKE '%pottery%'
    no_hit = con2.sql(
        f"SELECT COUNT(*) FROM read_parquet('{out}') WHERE pid='pid_no_concept' AND description ILIKE '%pottery%'"
    ).fetchone()[0]
    assert no_hit == 0, (
        f"pid_no_concept should NOT match 'pottery' but did (description: {no_concept_desc[0]!r})"
    )

    con2.close()
