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
streams them in Arrow batches; Python tokenizes and counts (bounded
memory); intermediate token-row parquets go to a temp dir; DuckDB then
does the global DF + per-shard ordered writes. Scales to the 6.7M-sample
corpus without holding token rows in RAM.

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
CONCEPT_DIMS = {
    "material": "p__has_material_category",
    "context": "p__has_context_category",
    "object_type": "p__has_sample_object_type",
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
                   v.pref_label,
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
            SELECT row_id, pid AS uri FROM read_parquet('{wide}')
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
    ap.add_argument("--shards", type=int, default=64)
    ap.add_argument("--shard-cap-mb", type=float, default=5.0)
    ap.add_argument("--sub-shards", type=int, default=8,
                    help="M for hash(pid) %% M sub-sharding of over-cap shards")
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
            doc_len = min(len(tokens), 65535)
            fs = field_stats[field]
            fs["samples_with_field"] += 1
            fs["total_tokens"] += len(tokens)
            for token, tf in Counter(tokens).items():
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

    # Per-shard ordered writes + byte-cap sub-sharding (§6).
    cap_bytes = int(args.shard_cap_mb * 1024 * 1024)
    shard_max_bytes = 0
    shard_files = 0
    for shard in range(args.shards):
        shard_path = out_root / f"shard_{shard:03d}.parquet"
        con.execute(f"""
            COPY (
                SELECT token, pid, field, tf, doc_len
                FROM read_parquet('{rows_glob}')
                WHERE shard = {shard}
                ORDER BY token, pid, field
            ) TO '{shard_path}' (FORMAT PARQUET);
        """)
        size = shard_path.stat().st_size
        if size > cap_bytes:
            # Sub-shard by FNV-1a(pid) % M. A #171 reader must fetch all
            # sub-files for the shard (presence of shard_XXX_p0.parquet
            # signals the split; the base file is removed).
            for m in range(args.sub_shards):
                con.execute(f"""
                    COPY (
                        SELECT token, pid, field, tf, doc_len
                        FROM read_parquet('{rows_glob}')
                        WHERE shard = {shard}
                          AND (CAST(hash(pid) AS UBIGINT) % {args.sub_shards}) = {m}
                        ORDER BY token, pid, field
                    ) TO '{out_root / f"shard_{shard:03d}_p{m}.parquet"}' (FORMAT PARQUET);
                """)
            shard_path.unlink()
            sizes = [(out_root / f"shard_{shard:03d}_p{m}.parquet").stat().st_size
                     for m in range(args.sub_shards)]
            shard_max_bytes = max(shard_max_bytes, *sizes)
            shard_files += args.sub_shards
        else:
            shard_max_bytes = max(shard_max_bytes, size)
            shard_files += 1

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
        "shard_count": args.shards,
        "shard_files": shard_files,
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

    print(f"built {args.tag}_search_index_v1: {shard_files} shard files, "
          f"max {stats['shard_max_size_mb']} MB, "
          f"{total_samples:,} samples, {stats['build_seconds']}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
