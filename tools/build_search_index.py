#!/usr/bin/env python3
"""Offline builder for the iSamples search substrate v1 (#170).

Implements SEARCH_INDEX_V1.md: builds the sample-centric document
projection (label / description / place_name / dereferenced concept
labels), tokenizes with the canonical tokenizer (tools/search_tokenizer.py
— kept in JS parity by CI), and emits:

  <outdir>/<tag>_search_index_v1/
      shard_000.parquet .. shard_NNN.parquet   token-row substrate (§4)
      df.parquet                                global token DF sidecar
      build_stats.json                          empirical coverage (§10)

Token-row schema (§4): token VARCHAR, pid VARCHAR, field VARCHAR,
tf USMALLINT, doc_len USMALLINT.

Sharding (§6): FNV-1a 32-bit over the UTF-8 token, mod --shards.
FNV-1a is deliberate: the browser query path (#171) must compute the
same shard for a query token in JS, so the hash has to be trivially
portable (DuckDB's hash() is not). A shard whose file exceeds the byte
cap is sub-sharded by FNV-1a(pid) % M into shard_XXX_pY.parquet — a
query must then read all sub-files of its shard (documented for #171).

Memory model: DuckDB aggregates text fragments per (pid, field) and
streams them in Arrow batches; Python tokenizes and counts; token rows
spill to intermediate parquets every ~2M rows; DuckDB then does the
global DF + per-shard ordered writes. The PYTHON side is bounded (batch
+ 2M-row buffer); DuckDB's aggregation/sort working set still scales
with the corpus (fine at 6.7M samples on a dev machine; not a hard
guarantee).

Usage:
  python tools/build_search_index.py \
      --wide  ~/Data/.../isamples_202608_wide.parquet \
      --lite  https://data.isamples.org/isamples_202608_samples_map_lite_v3.parquet \
      --vocab https://data.isamples.org/vocab_labels_202608.parquet \
      --outdir /tmp/search_index --tag isamples_202608
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent))
from search_tokenizer import tokenize  # noqa: E402

V1_FIELDS = ("sample.label", "sample.description", "sample.place_name", "concept.label")
# CONTRACT AMENDMENT (2026-07-10, discovered on the first full-corpus build):
# `keywords` is pulled forward from the contract's v2 list, and label
# resolution falls back to the concept's own `label` column in the wide
# before the URI tail. Without both, the v1 index REGRESSES the benchmark's
# own example query: 'pottery Cyprus' → 0 results, because "Pottery" is not
# a concept in the 537-entry curated vocabulary — it reaches samples only as
# an OpenContext keyword concept whose label lives on the IdentifiedConcept
# row. The interim ILIKE search already covers keywords (via
# build_frontend_derived.py's appended concept_labels), so shipping v1
# without them would be a recall regression and an automatic #172 NO-GO.
CONCEPT_DIMS = {
    "material": "p__has_material_category",
    "context": "p__has_context_category",
    "object_type": "p__has_sample_object_type",
    "keywords": "p__keywords",
}
TOKEN_ROW_SCHEMA = pa.schema([
    ("token", pa.string()),
    ("pid", pa.string()),
    ("field", pa.string()),
    ("tf", pa.uint16()),
    ("doc_len", pa.uint16()),
    ("shard", pa.uint16()),
])


def fnv1a32(data: str) -> int:
    """FNV-1a 32-bit over UTF-8 bytes. JS twin must match exactly (#171)."""
    h = 0x811C9DC5
    for byte in data.encode("utf-8"):
        h ^= byte
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def uri_tail(uri: str) -> str:
    """Fallback fragment for a concept URI with no prefLabel: its last path
    segment (e.g. <…/material/1.0/pottery> -> 'pottery')."""
    return uri.rstrip("/").rsplit("/", 1)[-1] if uri else ""


def fragment_relation(con: duckdb.DuckDBPyConnection, wide: str, lite: str, vocab: str) -> None:
    """Materialize `fragments(pid, field, text, resolved)` — the document
    projection of SEARCH_INDEX_V1.md §1 — plus per-dim URI resolution stats.

    `resolved` is only meaningful for concept.label rows: TRUE when the URI
    dereferenced to a SKOS prefLabel, FALSE when we fell back to the URI
    tail (build-stat counter feeds off it).
    """
    # Decorrelated unnest+join, mirroring scripts/build_frontend_derived.py's
    # `mat` CTE — a correlated `row_id IN (SELECT unnest(...))` subquery blows
    # up the planner at 20M-row scale (documented there).
    concept_selects = []
    for dim, col in CONCEPT_DIMS.items():
        concept_selects.append(f"""
            SELECT ex.pid,
                   'concept.label' AS field,
                   COALESCE(v.pref_label, ic.label) AS pref_label,
                   ic.uri,
                   '{dim}' AS dim
            FROM (
                SELECT s.pid, u.rid
                FROM wide_samples s, UNNEST(s.{col}) AS u(rid)
            ) ex
            JOIN ic ON ic.row_id = ex.rid
            LEFT JOIN vocab v ON v.uri = ic.uri
        """)
    concepts_union = " UNION ALL ".join(concept_selects)
    con.execute(f"""
        CREATE TEMP TABLE wide_samples AS
            SELECT pid, label, description,
                   {', '.join(CONCEPT_DIMS.values())}
            FROM read_parquet('{wide}')
            WHERE otype = 'MaterialSampleRecord' AND pid IS NOT NULL;

        CREATE TEMP TABLE ic AS
            SELECT row_id, pid AS uri, label FROM read_parquet('{wide}')
            WHERE otype = 'IdentifiedConcept';

        CREATE TEMP VIEW vocab AS
            SELECT uri, pref_label FROM read_parquet('{vocab}')
            WHERE lang = 'en' OR lang IS NULL;

        CREATE TEMP TABLE concept_fragments AS
            SELECT pid, field, pref_label, uri, dim,
                   (pref_label IS NOT NULL) AS resolved
            FROM ({concepts_union});

        CREATE TEMP TABLE fragments AS
            SELECT pid, 'sample.label' AS field, label AS text, TRUE AS resolved
            FROM wide_samples WHERE label IS NOT NULL AND label != ''
          UNION ALL
            SELECT pid, 'sample.description', description, TRUE
            FROM wide_samples WHERE description IS NOT NULL AND description != ''
          UNION ALL
            SELECT l.pid, 'sample.place_name', t.place, TRUE
            FROM read_parquet('{lite}') l, UNNEST(l.place_name) AS t(place)
            WHERE t.place IS NOT NULL AND t.place != ''
          UNION ALL
            SELECT pid, field,
                   CASE WHEN resolved THEN pref_label ELSE uri END AS text,
                   resolved
            FROM concept_fragments;
    """)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wide", required=True)
    ap.add_argument("--lite", required=True)
    ap.add_argument("--vocab", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--tag", required=True, help="e.g. isamples_202608")
    # 256 default: the 202608 corpus yields ~570 MB of non-hot base rows;
    # 64 shards made ~9 MB base files against the 5 MB cap. 256 → ~2.2 MB
    # average with headroom for growth (v1.5 event/site fields).
    ap.add_argument("--shards", type=int, default=256)
    ap.add_argument("--shard-cap-mb", type=float, default=5.0)
    ap.add_argument("--batch-rows", type=int, default=200_000)
    args = ap.parse_args()

    t0 = time.time()
    out_root = Path(args.outdir) / f"{args.tag}_search_index_v1"
    out_root.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()
    fragment_relation(con, args.wide, args.lite, args.vocab)

    total_samples = con.sql(
        "SELECT count(DISTINCT pid) FROM wide_samples").fetchone()[0]
    # URI-resolution stats per dim (contract §10) — computed in SQL, cheap.
    resolution = {}
    for dim in CONCEPT_DIMS:
        row = con.sql(f"""
            SELECT count(*) FILTER (resolved), count(*)
            FROM concept_fragments WHERE dim = '{dim}'
        """).fetchone()
        total = row[1] or 1
        resolution[f"{dim}_resolved"] = round(row[0] / total, 4)
        resolution[f"{dim}_missing_pref"] = round((total - row[0]) / total, 4)
    missing_pref_count = con.sql(
        "SELECT count(*) FROM concept_fragments WHERE NOT resolved").fetchone()[0]

    # For concept fragments that missed a prefLabel, tokenize the URI TAIL,
    # not the full URI (contract: URI-tail fallback). Handled here by
    # rewriting those texts before aggregation.
    con.execute("""
        UPDATE fragments
        SET text = regexp_extract(rtrim(text, '/'), '([^/]+)$', 1)
        WHERE field = 'concept.label' AND NOT resolved;
    """)

    # Aggregate fragments per (pid, field) so each streamed row carries the
    # COMPLETE document for that pair (tf/doc_len computable in one visit).
    docs = con.sql("""
        SELECT pid, field, list(text) AS texts
        FROM fragments
        GROUP BY pid, field
    """)

    field_stats = {f: {"samples_with_field": 0, "total_tokens": 0} for f in V1_FIELDS}
    # USMALLINT truncation is a contract-semantics change when it fires, so
    # it is COUNTED, not silent (Codex review of #329): build_stats records
    # both counters + observed maxima; a non-zero count prints a warning.
    trunc = {"doc_len_docs": 0, "tf_rows": 0, "max_doc_len": 0, "max_tf": 0}
    tmp_dir = tempfile.mkdtemp(prefix="search_index_rows_")
    tmp_files: list[str] = []
    buf: dict[str, list] = {k: [] for k in ("token", "pid", "field", "tf", "doc_len", "shard")}
    buf_rows = 0

    def flush() -> None:
        nonlocal buf, buf_rows
        if not buf_rows:
            return
        table = pa.table(
            {
                "token": pa.array(buf["token"], pa.string()),
                "pid": pa.array(buf["pid"], pa.string()),
                "field": pa.array(buf["field"], pa.string()),
                "tf": pa.array(buf["tf"], pa.uint16()),
                "doc_len": pa.array(buf["doc_len"], pa.uint16()),
                "shard": pa.array(buf["shard"], pa.uint16()),
            },
            schema=TOKEN_ROW_SCHEMA,
        )
        path = os.path.join(tmp_dir, f"rows_{len(tmp_files):05d}.parquet")
        pq.write_table(table, path)
        tmp_files.append(path)
        buf = {k: [] for k in buf}
        buf_rows = 0

    reader = docs.fetch_arrow_reader(batch_size=args.batch_rows)
    for batch in reader:
        pids = batch.column("pid").to_pylist()
        fields = batch.column("field").to_pylist()
        texts_col = batch.column("texts").to_pylist()
        for pid, field, texts in zip(pids, fields, texts_col):
            tokens: list[str] = []
            for t in texts:
                tokens.extend(tokenize(t))
            if not tokens:
                continue
            raw_len = len(tokens)
            trunc["max_doc_len"] = max(trunc["max_doc_len"], raw_len)
            if raw_len > 65535:
                trunc["doc_len_docs"] += 1
            doc_len = min(raw_len, 65535)
            fs = field_stats[field]
            fs["samples_with_field"] += 1
            fs["total_tokens"] += raw_len
            for token, tf in Counter(tokens).items():
                trunc["max_tf"] = max(trunc["max_tf"], tf)
                if tf > 65535:
                    trunc["tf_rows"] += 1
                buf["token"].append(token)
                buf["pid"].append(pid)
                buf["field"].append(field)
                buf["tf"].append(min(tf, 65535))
                buf["doc_len"].append(doc_len)
                buf["shard"].append(fnv1a32(token) % args.shards)
                buf_rows += 1
            if buf_rows >= 2_000_000:
                flush()
    flush()

    if not tmp_files:
        print("ERROR: no token rows produced — empty inputs?", file=sys.stderr)
        return 1

    rows_glob = os.path.join(tmp_dir, "rows_*.parquet")

    # Sidecar df.parquet: documents are (pid, field) pairs; rows are already
    # unique per (token, pid, field), so DF is a plain count.
    con.execute(f"""
        COPY (
            SELECT token, count(*)::UINTEGER AS df
            FROM read_parquet('{rows_glob}')
            GROUP BY token ORDER BY token
        ) TO '{out_root / "df.parquet"}' (FORMAT PARQUET);
    """)

    # Hot-token isolation + per-shard ordered writes (§6).
    #
    # The contract's high-frequency rule is TOKEN-level, not shard-level: a
    # token whose postings alone would blow the byte cap is pulled OUT of its
    # base shard and written to its own sub-file set, sub-sharded by
    # fnv1a32(pid) % M with M sized so each sub-file fits the cap. The base
    # shard then stays small, so a #171 reader fetches:
    #   normal token -> its base shard (small), located by fnv1a32(token)%N;
    #   hot token    -> hot/<fnv1a32(token) hex>_p{0..M-1}.parquet, with
    #                   hotness + M read from hot_tokens.json.
    # (First full-corpus build: 'material'/'object'/'solid' etc. — vocabulary
    # boilerplate present on ~5M samples — have posting lists >100 MB; the
    # earlier shard-level split forced readers to fetch M files for EVERY
    # token, breaking the §7 cold-bytes budget for the common case.)
    #
    # Cap is enforced against parquet FILE bytes (what a browser actually
    # transfers), which is stricter than the contract's "uncompressed".
    cap_bytes = int(args.shard_cap_mb * 1024 * 1024)
    est = con.sql(f"""
        SELECT avg(len(token) + len(pid) + len(field) + 4) FROM
        (SELECT * FROM read_parquet('{rows_glob}') LIMIT 500000)
    """).fetchone()[0] or 30.0
    # Planning ratio is only a first guess (observed file ratios vary by
    # token entropy); every hot token's sub-files are VERIFIED against the
    # cap after writing and re-split at 2×M until they fit.
    compress_ratio = 0.7
    hot = con.sql(f"""
        SELECT token, count(*) AS n
        FROM read_parquet('{rows_glob}')
        GROUP BY token
        HAVING count(*) * {est} * {compress_ratio} > {cap_bytes}
    """).fetchall()
    hot_dir = out_root / "hot"
    hot_manifest: dict[str, dict] = {}
    if hot:
        hot_dir.mkdir(exist_ok=True)
        con.execute("CREATE TEMP TABLE hot_tokens (token VARCHAR PRIMARY KEY)")
        con.executemany("INSERT INTO hot_tokens VALUES (?)", [[t] for t, _ in hot])
    shard_max_bytes = 0
    shard_files = 0
    cap_violations: list[str] = []
    _hot_keys_used: set[str] = set()

    def write_hot_token(token: str, n: int) -> None:
        nonlocal shard_max_bytes, shard_files
        # FNV-1a is 32-bit, so distinct hot tokens CAN collide (Codex review
        # of #329 produced a real pair: 'tywtopf1ri'/'32jnqttihd' → a7c9bf62).
        # Readers locate hot files via hot_tokens.json (never by recomputing
        # the hash), so uniqueness only has to hold here: suffix on collision.
        base_key = f"{fnv1a32(token):08x}"
        key = base_key
        seq = 0
        while key in _hot_keys_used:
            seq += 1
            key = f"{base_key}-{seq}"
        _hot_keys_used.add(key)
        tok_sql = token.replace("'", "''")
        m_count = max(2, -(-int(n * est * compress_ratio) // cap_bytes))
        max_attempts = 6  # 2x per retry; 6 doublings is plenty
        for attempt in range(max_attempts):
            paths = []
            for m in range(m_count):
                path = hot_dir / f"{key}_p{m}.parquet"
                con.execute(f"""
                    COPY (
                        SELECT token, pid, field, tf, doc_len
                        FROM read_parquet('{rows_glob}')
                        WHERE token = '{tok_sql}'
                          AND (CAST(hash(pid) AS UBIGINT) % {m_count}) = {m}
                        ORDER BY pid, field
                    ) TO '{path}' (FORMAT PARQUET);
                """)
                paths.append(path)
            biggest = max(p.stat().st_size for p in paths)
            if biggest <= cap_bytes:
                break
            if attempt < max_attempts - 1:
                for p in paths:  # re-split finer and retry
                    p.unlink()
                m_count *= 2
            else:
                # Cap unreachable (e.g. per-file parquet overhead > cap).
                # KEEP the finest split — manifest must always describe
                # what is actually on disk — and record the violation.
                cap_violations.append(f"hot/{key}: {biggest/1e6:.1f} MB after retries")
        shard_max_bytes = max(shard_max_bytes, biggest)
        shard_files += m_count
        total_bytes = sum(
            (hot_dir / f"{key}_p{m}.parquet").stat().st_size
            for m in range(m_count))
        # Two-tier policy (Codex round 3): many hot tokens are hot for
        # STORAGE reasons (promoted because their shard co-landed with other
        # big tokens), not semantic commonness — e.g. 'island'/'genetic' at
        # ~100k postings are genuinely selective and their dedicated files
        # total only ~2.5 MB. If a token's whole posting set fits the cold
        # budget, the reader just fetches its sub-files like a normal token;
        # only tokens whose postings EXCEED the budget get the common-term
        # drop/topk treatment.
        hot_manifest[token] = {"key": key, "sub_files": m_count, "postings": n,
                               "total_bytes": total_bytes,
                               "fetchable": total_bytes <= cap_bytes}

    for token, n in hot:
        write_hot_token(token, n)
    if not hot:
        con.execute("CREATE TEMP TABLE hot_tokens (token VARCHAR PRIMARY KEY)")
    for shard in range(args.shards):
        shard_path = out_root / f"shard_{shard:03d}.parquet"
        # Write, then promote the shard's heaviest tokens to hot/ until the
        # file fits the cap. Handles near-hot skew: a few ~3 MB posting lists
        # co-landing in one shard can't be fixed by shard count alone.
        for _attempt in range(12):
            con.execute(f"""
                COPY (
                    SELECT token, pid, field, tf, doc_len
                    FROM read_parquet('{rows_glob}')
                    WHERE shard = {shard}
                      AND token NOT IN (SELECT token FROM hot_tokens)
                    ORDER BY token, pid, field
                ) TO '{shard_path}' (FORMAT PARQUET);
            """)
            size = shard_path.stat().st_size
            if size <= cap_bytes:
                break
            heaviest = con.sql(f"""
                SELECT token, count(*) AS n
                FROM read_parquet('{rows_glob}')
                WHERE shard = {shard}
                  AND token NOT IN (SELECT token FROM hot_tokens)
                GROUP BY token ORDER BY n DESC LIMIT 1
            """).fetchone()
            if heaviest is None:
                break
            con.execute("INSERT INTO hot_tokens VALUES (?)", [heaviest[0]])
            write_hot_token(heaviest[0], heaviest[1])
        else:
            # Attempts exhausted with the LAST promotion never re-written:
            # without this final rewrite the just-promoted token would sit in
            # BOTH the base file and hot/ — duplicate postings that inflate
            # tf-side scores (Codex review of #329). Rewrite once more so the
            # base shard reflects every promotion, then record the violation
            # if it still doesn't fit.
            con.execute(f"""
                COPY (
                    SELECT token, pid, field, tf, doc_len
                    FROM read_parquet('{rows_glob}')
                    WHERE shard = {shard}
                      AND token NOT IN (SELECT token FROM hot_tokens)
                    ORDER BY token, pid, field
                ) TO '{shard_path}' (FORMAT PARQUET);
            """)
            size = shard_path.stat().st_size
            if size > cap_bytes:
                cap_violations.append(f"{shard_path.name}: {size/1e6:.1f} MB after promotions")
        shard_max_bytes = max(shard_max_bytes, size)
        shard_files += 1
    # hot_topk.parquet — the all-hot-query path (Codex round-2 finding: a
    # hot token's full postings exceed the cold-bytes budget BY DEFINITION,
    # so readers must never need them). For each hot token, precompute its
    # top-K postings by STATIC single-token BM25 (IDF and doc_len norm are
    # both query-independent for a single token), field-weighted per §5.
    # Query policy (contract §3 amendment): queries mixing hot + selective
    # terms DROP the hot terms from AND matching (common-term rule); pure-
    # hot queries rank via this sidecar. K=500 keeps headroom for source/
    # facet post-filtering while staying a single small file.
    topk_path = out_root / "hot_topk.parquet"
    if hot_manifest:
        # Corpus statistics per contract §5 / Codex round 3: totalDocs is the
        # number of (pid, field) DOCUMENTS (rows are unique per
        # (token,pid,field), so distinct (pid,field) must be counted
        # explicitly), and doc-length normalization uses the PER-FIELD corpus
        # average — not a per-token average, which would re-center every hot
        # token's normalization on its own postings.
        total_docs_for_idf = con.sql(f"""
            SELECT count(*) FROM (
                SELECT pid, field FROM read_parquet('{rows_glob}')
                GROUP BY pid, field)
        """).fetchone()[0]
        hot_list_sql = ",".join(
            "'" + t.replace("'", "''") + "'" for t in hot_manifest)
        con.execute(f"""
            COPY (
                WITH field_avg AS (
                    SELECT field, avg(doc_len) AS avg_dl FROM (
                        SELECT pid, field, any_value(doc_len) AS doc_len
                        FROM read_parquet('{rows_glob}')
                        GROUP BY pid, field)
                    GROUP BY field
                ), hot_rows AS (
                    SELECT r.token, r.pid, r.field, r.tf, r.doc_len,
                           d.df, fa.avg_dl
                    FROM read_parquet('{rows_glob}') r
                    JOIN read_parquet('{out_root / "df.parquet"}') d USING (token)
                    JOIN field_avg fa USING (field)
                    WHERE r.token IN ({hot_list_sql})
                ), contrib AS (
                    SELECT token, pid,
                        (CASE field
                            WHEN 'sample.label' THEN 3.0
                            WHEN 'concept.label' THEN 2.5
                            WHEN 'sample.place_name' THEN 2.0
                            ELSE 1.0 END)
                        * ln((({total_docs_for_idf} - df + 0.5) / (df + 0.5)) + 1)
                        * (tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * doc_len / avg_dl))
                        AS c
                    FROM hot_rows
                ), per_pid AS (
                    -- §5: rank per PID by the SUM of field-weighted
                    -- contributions, not per (pid, field) posting.
                    SELECT token, pid, sum(c) AS static_score
                    FROM contrib GROUP BY token, pid
                ), ranked AS (
                    SELECT *, row_number() OVER (
                        PARTITION BY token ORDER BY static_score DESC, pid
                    ) AS rank
                    FROM per_pid
                )
                SELECT token, pid, round(static_score, 4) AS static_score, rank
                FROM ranked WHERE rank <= 500
                ORDER BY token, rank
            ) TO '{topk_path}' (FORMAT PARQUET);
        """)
        topk_bytes = topk_path.stat().st_size
        if topk_bytes > cap_bytes:
            cap_violations.append(f"hot_topk.parquet: {topk_bytes/1e6:.1f} MB")
    else:
        topk_bytes = 0
    # shard_sizes.json — file bytes of every base shard, so the reader can
    # compute a query's expected transfer BEFORE fetching (contract §6/§7,
    # round-4 review: per-query budgeting must be computable, not guessed).
    with open(out_root / "shard_sizes.json", "w") as f:
        json.dump({f"shard_{i:03d}.parquet":
                   (out_root / f"shard_{i:03d}.parquet").stat().st_size
                   for i in range(args.shards)}, f, indent=1)
        f.write("\n")
    with open(out_root / "hot_tokens.json", "w") as f:
        json.dump({
            "cap_bytes": cap_bytes,
            "query_policy": ("TWO-TIER (contract §6): tokens with fetchable=true "
                             "— reader fetches ALL their hot/ sub-files (total fits "
                             "the cold budget) and they join the AND normally. "
                             "Tokens with fetchable=false are COMMON TERMS: dropped "
                             "from AND when >=1 other term survives (UI must "
                             "disclose); all-common queries rank via "
                             "hot_topk.parquet (per-pid summed static BM25 "
                             "top-500). Non-fetchable postings files exist for "
                             "offline/#172-oracle use only."),
            "sub_shard_hash": ("sub-file membership uses DuckDB hash(pid) — a "
                               "consumer that DOES read hot postings fetches ALL "
                               "sub_files; the split function never needs "
                               "client-side computation"),
            "topk_k": 500,
            "topk_bytes": topk_bytes,
            "tokens": hot_manifest}, f, indent=1)
        f.write("\n")
    if cap_violations:
        print("WARNING: shard-cap violations (raise --shards or lower ratio):",
              *cap_violations[:10], sep="\n  ", file=sys.stderr)

    top_df = con.sql(f"""
        SELECT token, count(*) AS df FROM read_parquet('{rows_glob}')
        GROUP BY token ORDER BY df DESC LIMIT 20
    """).fetchall()
    total_uncompressed = con.sql(f"""
        SELECT sum(len(token) + len(pid) + len(field) + 4)
        FROM read_parquet('{rows_glob}')
    """).fetchone()[0]

    stats = {
        "data_version": args.tag,
        "built_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "total_samples": total_samples,
        "fields": {
            f: {
                "samples_with_field": field_stats[f]["samples_with_field"],
                "total_tokens": field_stats[f]["total_tokens"],
                "avg_doc_len": round(
                    field_stats[f]["total_tokens"]
                    / max(field_stats[f]["samples_with_field"], 1), 2),
            }
            for f in V1_FIELDS
        },
        "concept_label_uri_resolution": resolution,
        "concept_label_missing_pref_label": missing_pref_count,
        "usmallint_truncation": {
            "doc_len_docs_truncated": trunc["doc_len_docs"],
            "tf_rows_truncated": trunc["tf_rows"],
            "max_doc_len_observed": trunc["max_doc_len"],
            "max_tf_observed": trunc["max_tf"],
        },
        "shard_count": args.shards,
        "shard_files": shard_files,
        "hot_tokens": len(hot_manifest),
        "shard_cap_violations": len(cap_violations),
        "shard_hash": "fnv1a32(utf8(token)) % shards",
        "shard_max_size_mb": round(shard_max_bytes / 1024 / 1024, 2),
        "total_bytes_uncompressed": int(total_uncompressed or 0),
        "build_seconds": round(time.time() - t0, 1),
        "top_df_tokens": [[t, n] for t, n in top_df],
    }
    with open(out_root / "build_stats.json", "w") as f:
        json.dump(stats, f, indent=1)
        f.write("\n")

    for p in tmp_files:
        os.unlink(p)
    os.rmdir(tmp_dir)

    if trunc["doc_len_docs"] or trunc["tf_rows"]:
        print(f"WARNING: USMALLINT truncation occurred — doc_len docs: "
              f"{trunc['doc_len_docs']}, tf rows: {trunc['tf_rows']} "
              f"(max observed doc_len {trunc['max_doc_len']}, tf {trunc['max_tf']}) "
              "— BM25 semantics degraded for those documents", file=sys.stderr)
    print(f"built {args.tag}_search_index_v1: {shard_files} shard files, "
          f"max {stats['shard_max_size_mb']} MB, "
          f"{total_samples:,} samples, {stats['build_seconds']}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
