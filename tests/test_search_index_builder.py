"""End-to-end fixture test for tools/build_search_index.py (#170 §4).

Scope: URI dereferencing + document projection + shard structure — the
things the tokenizer tests deliberately do NOT prove. Builds a tiny corpus
(10 docs) with a fixture vocab_labels table, runs the real builder, and
asserts against the produced substrate.
"""

import json
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

REPO = Path(__file__).resolve().parent.parent
BUILDER = REPO / "tools" / "build_search_index.py"
sys.path.insert(0, str(REPO / "tools"))
from build_search_index import fnv1a32  # noqa: E402

SHARDS = 8  # small fixture -> few shards keeps file count readable

# 10 docs. Materials: 2×Pottery, 1×Ceramic, 1×Bone, 1×unresolvable URI,
# rest no material; one doc carries a KEYWORD concept whose label exists only
# on the IdentifiedConcept row (no vocab entry) — the ic.label fallback path
# that makes OpenContext keyword concepts ('Pottery' etc.) searchable.
# (Issue spec: >=3 docs with resolvable URIs, >=1 without.)
DOCS = [
    # pid, label, description, material_uri, keyword_uri, place_names
    ("pid:001", "Red Pottery Bowl", None, "test://Pottery", None, ["Murlo, Italy"]),
    ("pid:002", "Pottery sherd", "Iron-Age context", "test://Pottery", None, []),
    ("pid:003", "Ceramic figurine", None, "test://Ceramic", None, ["Çatalhöyük"]),
    ("pid:004", "Worked bone awl", "carved bone tool", "test://Bone", None, []),
    ("pid:005", "Mystery lump", None, "test://weird/UnknownStuff", None, []),
    ("pid:006", "Basalt core", "columnar basalt", None, "test://kw/VolcanicRock", ["Axial Seamount summit caldera"]),
    ("pid:007", "Soil sample", None, None, None, []),
    ("pid:008", "Water sample", "filtered seawater", None, None, ["North Pacific Ocean"]),
    ("pid:009", "Coral fragment", None, None, None, []),
    ("pid:010", "Obsidian flake", None, None, None, []),
]
# Keyword concept has an IC label but NO vocab entry (the OC-keyword shape).
IC_LABELS = {"test://kw/VolcanicRock": "Volcanic rock"}
VOCAB = [
    ("test://Pottery", "Pottery", "en"),
    ("test://Ceramic", "Ceramic", "en"),
    ("test://Bone", "Bone", "en"),
    # deliberately NO entry for test://weird/UnknownStuff or test://kw/*
]


@pytest.fixture(scope="module")
def built_index(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("fts_fixture")
    con = duckdb.connect()

    # Concept rows get row_ids 100+; samples reference them by row_id array.
    uris = sorted({d[3] for d in DOCS if d[3]} | {d[4] for d in DOCS if d[4]})
    uri_rowid = {u: 100 + i for i, u in enumerate(uris)}
    con.execute("""
        CREATE TABLE wide (
            row_id BIGINT, pid VARCHAR, otype VARCHAR, label VARCHAR,
            description VARCHAR,
            p__has_material_category BIGINT[],
            p__has_context_category BIGINT[],
            p__has_sample_object_type BIGINT[],
            p__keywords BIGINT[]
        )""")
    for i, (pid, label, desc, mat, kw, _places) in enumerate(DOCS):
        con.execute(
            "INSERT INTO wide VALUES (?, ?, 'MaterialSampleRecord', ?, ?, ?, NULL, NULL, ?)",
            [i, pid, label, desc,
             [uri_rowid[mat]] if mat else None,
             [uri_rowid[kw]] if kw else None])
    for uri, rid in uri_rowid.items():
        con.execute(
            "INSERT INTO wide VALUES (?, ?, 'IdentifiedConcept', ?, NULL, NULL, NULL, NULL, NULL)",
            [rid, uri, IC_LABELS.get(uri)])

    con.execute("CREATE TABLE lite (pid VARCHAR, place_name VARCHAR[])")
    for pid, _l, _d, _m, _k, places in DOCS:
        con.execute("INSERT INTO lite VALUES (?, ?)", [pid, places or None])

    con.execute("CREATE TABLE vocab (uri VARCHAR, pref_label VARCHAR, lang VARCHAR)")
    for row in VOCAB:
        con.execute("INSERT INTO vocab VALUES (?, ?, ?)", list(row))

    wide_p, lite_p, vocab_p = (str(tmp / f"{n}.parquet") for n in ("wide", "lite", "vocab"))
    con.execute(f"COPY wide TO '{wide_p}' (FORMAT PARQUET)")
    con.execute(f"COPY lite TO '{lite_p}' (FORMAT PARQUET)")
    con.execute(f"COPY vocab TO '{vocab_p}' (FORMAT PARQUET)")

    out = tmp / "out"
    res = subprocess.run(
        [sys.executable, str(BUILDER),
         "--wide", wide_p, "--lite", lite_p, "--vocab", vocab_p,
         "--outdir", str(out), "--tag", "test_202601", "--shards", str(SHARDS)],
        capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    root = out / "test_202601_search_index_v1"
    q = duckdb.connect()
    rows = q.sql(f"SELECT * FROM read_parquet('{root}/shard_*.parquet')").df()
    return root, rows


def test_outputs_exist(built_index):
    root, _ = built_index
    assert (root / "df.parquet").exists()
    assert (root / "build_stats.json").exists()
    assert list(root.glob("shard_*.parquet"))
    # shard_sizes.json: every base shard listed with its true file size
    sizes = json.loads((root / "shard_sizes.json").read_text())
    assert len(sizes) == SHARDS
    for name, size in sizes.items():
        assert (root / name).stat().st_size == size


def test_uri_dereferencing_end_to_end(built_index):
    """THE core proof: searching 'pottery' finds exactly the pids whose
    material URI is <test://Pottery> — via dereferenced concept labels."""
    _, rows = built_index
    hits = rows[(rows.token == "pottery") & (rows.field == "concept.label")]
    assert sorted(hits.pid) == ["pid:001", "pid:002"]


def test_uri_tail_fallback_and_counter(built_index):
    root, rows = built_index
    # test://weird/UnknownStuff has no prefLabel -> URI tail 'unknownstuff'.
    hits = rows[(rows.token == "unknownstuff") & (rows.field == "concept.label")]
    assert list(hits.pid) == ["pid:005"]
    stats = json.loads((root / "build_stats.json").read_text())
    assert stats["concept_label_missing_pref_label"] == 1
    assert stats["concept_label_uri_resolution"]["material_missing_pref"] > 0


def test_keyword_concept_via_ic_label_fallback(built_index):
    """A keyword concept with no vocab entry resolves through the concept's
    own label (contract amendment 2026-07-10) — the path that makes
    'pottery Cyprus' work against OpenContext keyword concepts."""
    _, rows = built_index
    hits = rows[(rows.token == "volcanic") & (rows.field == "concept.label")]
    assert list(hits.pid) == ["pid:006"]
    hits2 = rows[(rows.token == "rock") & (rows.field == "concept.label")]
    assert list(hits2.pid) == ["pid:006"]


def test_field_projection_and_doc_len(built_index):
    _, rows = built_index
    # pid:001 label 'Red Pottery Bowl' -> 3 tokens, tf('pottery')=1, doc_len=3
    r = rows[(rows.pid == "pid:001") & (rows.field == "sample.label")]
    assert sorted(r.token) == ["bowl", "pottery", "red"]
    assert set(r.doc_len) == {3}
    assert set(r.tf) == {1}
    # place_name projection, diacritics folded
    r = rows[(rows.pid == "pid:003") & (rows.field == "sample.place_name")]
    assert list(r.token) == ["catalhoyuk"]
    # description projection
    r = rows[(rows.pid == "pid:002") & (rows.field == "sample.description")]
    assert sorted(r.token) == ["age", "context", "iron"]


def test_shard_assignment_matches_fnv1a(built_index):
    root, rows = built_index
    for token in ("pottery", "basalt", "catalhoyuk"):
        expected_shard = fnv1a32(token) % SHARDS
        for f in root.glob("shard_*.parquet"):
            got = duckdb.sql(
                f"SELECT count(*) FROM read_parquet('{f}') WHERE token = '{token}'"
            ).fetchone()[0]
            shard_no = int(f.stem.split("_")[1])
            if shard_no == expected_shard:
                assert got > 0, f"{token} missing from its home shard {f.name}"
            else:
                assert got == 0, f"{token} leaked into {f.name}"


def test_df_embedded_in_shards(built_index):
    """Round-5: the query path never fetches df.parquet — df ships as a
    column in every shard row and must equal the sidecar's value."""
    root, rows = built_index
    assert "df" in rows.columns
    sidecar = duckdb.sql(f"SELECT * FROM read_parquet('{root}/df.parquet')").df()
    merged = rows.merge(sidecar, on="token", suffixes=("_row", "_sidecar"))
    assert (merged.df_row == merged.df_sidecar).all()
    # BM25 constants ship in build_stats.json
    stats = json.loads((root / "build_stats.json").read_text())
    assert stats["total_documents"] == len(rows.groupby(["pid", "field"]))


def test_df_sidecar(built_index):
    root, rows = built_index
    df = duckdb.sql(f"SELECT * FROM read_parquet('{root}/df.parquet')").df()
    # 'pottery' appears in: pid:001 label, pid:002 label, pid:001+002
    # concept.label -> 4 (pid, field) docs.
    assert int(df[df.token == "pottery"].df.iloc[0]) == 4
    # DF must equal the distinct (pid, field) count for every token.
    joined = rows.groupby("token").size()
    for token, n in joined.items():
        assert int(df[df.token == token].df.iloc[0]) == n


def test_build_stats_field_coverage(built_index):
    root, _ = built_index
    stats = json.loads((root / "build_stats.json").read_text())
    assert stats["total_samples"] == 10
    assert stats["fields"]["sample.label"]["samples_with_field"] == 10
    assert stats["fields"]["sample.description"]["samples_with_field"] == 4
    assert stats["fields"]["sample.place_name"]["samples_with_field"] == 4
    assert stats["fields"]["concept.label"]["samples_with_field"] == 6  # 5 material + 1 keyword
    assert stats["concept_label_uri_resolution"]["keywords_resolved"] == 1.0
    assert stats["shard_hash"] == "fnv1a32(utf8(token)) % shards"


def test_hot_token_isolation_on_tiny_cap(tmp_path):
    """Force the byte cap to ~0 so every token is 'hot'; assert the token-level
    isolation semantics: hot tokens leave the base shards, land in
    hot/<fnv hex>_p*.parquet, are listed in hot_tokens.json, and no rows are
    lost. (At production scale only vocabulary-boilerplate tokens like
    'material' trip this — with posting lists on ~5M samples each.)"""
    con = duckdb.connect()
    con.execute("CREATE TABLE wide (row_id BIGINT, pid VARCHAR, otype VARCHAR,"
                " label VARCHAR, description VARCHAR,"
                " p__has_material_category BIGINT[],"
                " p__has_context_category BIGINT[],"
                " p__has_sample_object_type BIGINT[],"
                " p__keywords BIGINT[])")
    # pid:x carries 'pottery' in BOTH label and concept.label (multi-field);
    # pid:t1/pid:t2 are identical twins (deterministic tie case). Codex
    # round-3: the topk sidecar must rank per-PID SUMMED scores, one row per
    # (token, pid), ties broken by pid ascending.
    con.execute("INSERT INTO wide VALUES (0, 'pid:x', 'MaterialSampleRecord',"
                " 'pottery pottery pottery', NULL, [100], NULL, NULL, NULL)")
    con.execute("INSERT INTO wide VALUES (1, 'pid:y', 'MaterialSampleRecord',"
                " 'pottery basalt', NULL, NULL, NULL, NULL, NULL)")
    con.execute("INSERT INTO wide VALUES (2, 'pid:t1', 'MaterialSampleRecord',"
                " 'twin stone', NULL, NULL, NULL, NULL, NULL)")
    con.execute("INSERT INTO wide VALUES (3, 'pid:t2', 'MaterialSampleRecord',"
                " 'twin stone', NULL, NULL, NULL, NULL, NULL)")
    con.execute("INSERT INTO wide VALUES (100, 'test://P', 'IdentifiedConcept',"
                " NULL, NULL, NULL, NULL, NULL, NULL)")
    con.execute("CREATE TABLE lite (pid VARCHAR, place_name VARCHAR[])")
    con.execute("CREATE TABLE vocab (uri VARCHAR, pref_label VARCHAR, lang VARCHAR)")
    con.execute("INSERT INTO vocab VALUES ('test://P', 'pottery', 'en')")
    wide_p, lite_p, vocab_p = (str(tmp_path / f"{n}.parquet") for n in ("w", "l", "v"))
    con.execute(f"COPY wide TO '{wide_p}' (FORMAT PARQUET)")
    con.execute(f"COPY lite TO '{lite_p}' (FORMAT PARQUET)")
    con.execute(f"COPY vocab TO '{vocab_p}' (FORMAT PARQUET)")
    res = subprocess.run(
        [sys.executable, str(BUILDER), "--wide", wide_p, "--lite", lite_p,
         "--vocab", vocab_p, "--outdir", str(tmp_path / "out"),
         "--tag", "cap_test", "--shards", "2", "--shard-cap-mb", "0.000001"],
        capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    root = tmp_path / "out" / "cap_test_search_index_v1"

    manifest_full = json.loads((root / "hot_tokens.json").read_text())
    manifest = manifest_full
    assert "pottery" in manifest["tokens"]
    # two-tier policy fields present; at a ~1-byte cap nothing is fetchable
    e = manifest["tokens"]["pottery"]
    assert e["total_bytes"] > 0 and e["fetchable"] is False
    key = manifest["tokens"]["pottery"]["key"]
    assert key == f"{fnv1a32('pottery'):08x}"
    subs = list((root / "hot").glob(f"{key}_p*.parquet"))
    assert len(subs) == manifest["tokens"]["pottery"]["sub_files"] >= 2
    # hot token's rows all present across its sub-files (both pids, no dupes)
    hot_rows = duckdb.sql(
        f"SELECT pid, field, tf FROM read_parquet('{root}/hot/{key}_p*.parquet') ORDER BY pid, field"
    ).fetchall()
    # pid:x matches in TWO fields (label tf=3 + concept.label tf=1)
    assert hot_rows == [("pid:x", "concept.label", 1), ("pid:x", "sample.label", 3),
                        ("pid:y", "sample.label", 1)]
    # ...and absent from every base shard
    base = duckdb.sql(
        f"SELECT count(*) FROM read_parquet('{root}/shard_*.parquet') WHERE token='pottery'"
    ).fetchone()[0]
    assert base == 0
    # hot_topk sidecar (contract §6 common-term rule; Codex round 3):
    # ONE row per (token, pid) — per-PID summed field-weighted scores.
    assert manifest_full["topk_k"] == 500
    topk = duckdb.sql(
        f"SELECT token, pid, static_score, rank FROM read_parquet('{root}/hot_topk.parquet') "
        "WHERE token='pottery' ORDER BY rank").fetchall()
    assert [r[3] for r in topk] == list(range(1, len(topk) + 1))
    # pid:x appears ONCE despite matching in two fields (label + concept)
    assert [r[1] for r in topk] == ["pid:x", "pid:y"]
    # multi-field sum: pid:x (label tf=3 + concept.label) beats pid:y (label tf=1)
    assert topk[0][2] > topk[1][2]
    # deterministic tie: identical twins order by pid ascending
    twins = duckdb.sql(
        f"SELECT pid, static_score, rank FROM read_parquet('{root}/hot_topk.parquet') "
        "WHERE token='twin' ORDER BY rank").fetchall()
    assert [t[0] for t in twins] == ["pid:t1", "pid:t2"]
    assert twins[0][1] == twins[1][1]


def test_hot_key_collision_gets_distinct_files(tmp_path):
    """fnv1a32 is 32-bit: distinct tokens CAN collide (this pair was
    produced by Codex review and verified: both hash to 0xa7c9bf62).
    Colliding hot tokens must get DISTINCT manifest keys and files —
    silent overwrite would merge two tokens' postings."""
    a, b = "tywtopf1ri", "32jnqttihd"
    assert fnv1a32(a) == fnv1a32(b)  # the premise
    con = duckdb.connect()
    con.execute("CREATE TABLE wide (row_id BIGINT, pid VARCHAR, otype VARCHAR,"
                " label VARCHAR, description VARCHAR,"
                " p__has_material_category BIGINT[],"
                " p__has_context_category BIGINT[],"
                " p__has_sample_object_type BIGINT[],"
                " p__keywords BIGINT[])")
    con.execute(f"INSERT INTO wide VALUES (0,'pid:a','MaterialSampleRecord','{a}',NULL,NULL,NULL,NULL,NULL)")
    con.execute(f"INSERT INTO wide VALUES (1,'pid:b','MaterialSampleRecord','{b}',NULL,NULL,NULL,NULL,NULL)")
    con.execute("CREATE TABLE lite (pid VARCHAR, place_name VARCHAR[])")
    con.execute("CREATE TABLE vocab (uri VARCHAR, pref_label VARCHAR, lang VARCHAR)")
    wide_p, lite_p, vocab_p = (str(tmp_path / f"{n}.parquet") for n in ("w", "l", "v"))
    con.execute(f"COPY wide TO '{wide_p}' (FORMAT PARQUET)")
    con.execute(f"COPY lite TO '{lite_p}' (FORMAT PARQUET)")
    con.execute(f"COPY vocab TO '{vocab_p}' (FORMAT PARQUET)")
    res = subprocess.run(
        [sys.executable, str(BUILDER), "--wide", wide_p, "--lite", lite_p,
         "--vocab", vocab_p, "--outdir", str(tmp_path / "out"),
         "--tag", "coll_test", "--shards", "2", "--shard-cap-mb", "0.000001"],
        capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    root = tmp_path / "out" / "coll_test_search_index_v1"
    manifest = json.loads((root / "hot_tokens.json").read_text())["tokens"]
    assert a in manifest and b in manifest
    assert manifest[a]["key"] != manifest[b]["key"]
    # each token's rows are exactly its own pid — no cross-contamination
    for tok, pid in ((a, "pid:a"), (b, "pid:b")):
        key = manifest[tok]["key"]
        rows = duckdb.sql(
            f"SELECT DISTINCT token, pid FROM read_parquet('{root}/hot/{key}_p*.parquet')"
        ).fetchall()
        assert rows == [(tok, pid)], rows


def test_no_hot_tokens_at_default_cap(built_index):
    """Fixture-scale corpus: nothing is hot at the 5 MB default; base shards
    carry everything and hot_tokens.json is an empty manifest."""
    root, rows = built_index
    manifest = json.loads((root / "hot_tokens.json").read_text())
    assert manifest["tokens"] == {}
    stats = json.loads((root / "build_stats.json").read_text())
    assert stats["hot_tokens"] == 0
    assert stats["shard_cap_violations"] == 0
