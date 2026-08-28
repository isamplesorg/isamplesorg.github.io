#!/usr/bin/env python3
"""Build an enriched unified-wide parquet by left-joining OC thumbnails — deterministically.

Takes the unified wide parquet (thumbnail_url is NULL for all samples because the
upstream iSamples export doesn't carry thumbnails — see issue #131) and fills in
thumbnail_url for the OpenContext samples that appear in Eric Kansa's
oc_isamples_pqg.parquet (the narrow one — thumbnails live on
MaterialSampleRecord rows).

This is step 2 of the reproducible 202609 chain (REPRODUCIBLE_PIPELINE_PLAN_2026-08-25.md):
    export → wide (pqg.sql_converter) → wide+thumbnails (THIS) → OC concepts → OC true-sync
    → derived files → search index.

Policy: OC is authoritative — for every MaterialSampleRecord row whose pid has an OC
thumbnail, thumbnail_url is REPLACED by the OC value (a pre-existing src value is
overwritten; the manifest counts overlaps and changed values). Rows of other entity
types are never touched even if they share a pid. Whitespace-only URLs count as empty.

Determinism contract (mirrors pqg.sql_converter's):
  * Same input bytes → same output ROWS: one thumbnail per pid (the lexically smallest,
    and the script FAILS if any pid carries more than one distinct non-empty URL unless
    --allow-multi is given), rows emitted in ascending `row_id` (must be unique and
    non-null in --src; the script fails otherwise). The output is verified row by row
    against that policy (identical row_id set, exact thumbnail per row, physical order)
    before it is moved into place.
  * With the same installed DuckDB binary and --threads 1 (default) repeated runs have
    produced byte-identical files (verified on the 202609 chain and the January wide).
    DuckDB documents row-order preservation, not stable Parquet encoding, so byte
    identity is a per-environment observation; the manifest records enough to say
    which environment (DuckDB version, platform, Python, script SHA-256, git SHA + dirty flag).
  * Unless --no-manifest, every run writes {out}.manifest.json: input SHA-256s (taken
    BEFORE the build), output SHA-256 + size, counts, environment, argv.

Usage:
    python scripts/enrich_wide_with_oc_thumbnails.py \\
        --src ~/Data/iSample/pqg_refining/202609/isamples_202609_wide_step1.parquet \\
        --oc  ~/Data/iSample/oc_snapshots/oc_isamples_pqg_2026-06-09.parquet \\
        --out ~/Data/iSample/pqg_refining/202609/isamples_202609_wide_step2_thumbs.parquet

Run it twice on the same inputs and compare the two SHA-256s in the manifests: they
must match. (Older usage, 202604: --src zenodo_wide_2026-01-09.parquet --oc the
Nov-2025 OC narrow, which no longer exists — see the plan's block B.)
"""
import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time

import duckdb


def sha256_file(path, _bufsize=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_bufsize), b""):
            h.update(chunk)
    return h.hexdigest()


def git_sha():
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return None


def q(path):
    """Quote a filesystem path as a SQL string literal (DuckDB: double the single quotes)."""
    return "'" + str(path).replace("'", "''") + "'"


def same_file(a, b):
    """True if two paths name the same file (resolving symlinks); False if either is missing."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return os.path.realpath(a) == os.path.realpath(b)


def git_dirty():
    """True if THIS SCRIPT differs from HEAD (so git_sha alone would misdescribe it);
    it says nothing about the rest of the repository."""
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain", "--", os.path.abspath(__file__)],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        return bool(out)
    except Exception:
        return None


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--src', required=True, help='source unified wide parquet (row_id unique, non-null)')
    p.add_argument('--oc',  required=True, help="Eric's OC narrow parquet (pid, thumbnail_url)")
    p.add_argument('--out', required=True, help='output path for the enriched parquet')
    p.add_argument('--threads', type=int, default=1,
                   help='DuckDB threads (default 1 for byte-reproducible output; rows are identical regardless)')
    p.add_argument('--allow-multi', action='store_true',
                   help='tolerate pids with >1 distinct thumbnail (keeps the lexically smallest) instead of failing')
    p.add_argument('--no-manifest', action='store_true', help='skip writing {out}.manifest.json')
    args = p.parse_args()

    for f in (args.src, args.oc):
        if not os.path.exists(f):
            print(f'ERROR: missing {f}', file=sys.stderr)
            return 2
    out_abs = os.path.abspath(args.out)
    mpath = out_abs + ".manifest.json"
    inputs = (os.path.abspath(args.src), os.path.abspath(args.oc))
    for dest in (out_abs, mpath):
        if any(same_file(dest, i) for i in inputs):
            print(f'ERROR: {dest} would overwrite an input', file=sys.stderr)
            return 2
    out_dir = os.path.dirname(out_abs) or '.'
    os.makedirs(out_dir, exist_ok=True)

    # Input sizes + hashes BEFORE the build, so the manifest describes what was read.
    # (A concurrent writer between this hash and the COPY would not be detected.)
    t0 = time.time()
    src_bytes, oc_bytes = os.path.getsize(args.src), os.path.getsize(args.oc)
    src_sha, oc_sha = sha256_file(args.src), sha256_file(args.oc)
    print(f'[{time.time()-t0:.1f}s] hashed inputs')

    con = duckdb.connect()
    con.execute(f"PRAGMA threads={int(args.threads)}")
    con.execute("SET preserve_insertion_order = true")
    SRC, OC = q(args.src), q(args.oc)

    print(f'source:  {args.src}')
    print(f'oc:      {args.oc}')
    print(f'out:     {args.out}')
    print(f'duckdb:  {duckdb.__version__}  threads={args.threads}')

    # --- preconditions on --src: row_id is the total order we emit in -------------
    t0 = time.time()
    n_src, n_rowid, n_rowid_distinct, n_null_pid = con.execute(f"""
        SELECT COUNT(*), COUNT(row_id), COUNT(DISTINCT row_id), COUNT(*) FILTER (WHERE pid IS NULL)
        FROM read_parquet({SRC})
    """).fetchone()
    if not (n_src == n_rowid == n_rowid_distinct):
        print(f'ERROR: --src row_id must be unique and non-null '
              f'(rows={n_src:,} non-null={n_rowid:,} distinct={n_rowid_distinct:,})', file=sys.stderr)
        return 3
    src_cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM read_parquet({SRC})").fetchall()]
    for needed in ('row_id', 'pid', 'otype', 'thumbnail_url'):
        if needed not in src_cols:
            print(f'ERROR: --src lacks column {needed}', file=sys.stderr)
            return 3
    print(f'[{time.time()-t0:.1f}s] src rows: {n_src:,} (row_id unique, non-null; {n_null_pid:,} with NULL pid; {len(src_cols)} columns)')

    # --- one thumbnail per pid, chosen deterministically ---------------------------
    t0 = time.time()
    con.execute(f"""
        CREATE TEMP TABLE oc_thumbs AS
        SELECT pid,
               min(url)            AS thumbnail_url,   -- lexically smallest = stable choice
               COUNT(DISTINCT url) AS n_distinct
        FROM (SELECT pid, NULLIF(TRIM(thumbnail_url), '') AS url FROM read_parquet({OC}))
        WHERE url IS NOT NULL AND pid IS NOT NULL
        GROUP BY pid
    """)
    n_pids, n_multi = con.execute(
        "SELECT COUNT(*), COUNT(*) FILTER (WHERE n_distinct > 1) FROM oc_thumbs").fetchone()
    print(f'[{time.time()-t0:.1f}s] oc thumbnails: {n_pids:,} pids, {n_multi:,} with >1 distinct URL')
    if n_multi and not args.allow_multi:
        print(f'ERROR: {n_multi:,} OC pids carry more than one distinct thumbnail_url; '
              f'pass --allow-multi to keep the lexically smallest', file=sys.stderr)
        return 4

    # --- the policy, as one SQL expression used for BOTH the build and the check ---
    # OC wins for MaterialSampleRecord rows; every other row keeps its value.
    POLICY = "CASE WHEN p.otype = 'MaterialSampleRecord' AND oc.thumbnail_url IS NOT NULL " \
             "THEN oc.thumbnail_url ELSE p.thumbnail_url END"

    # --- join + write in row_id order, to a unique temp file in the output dir -----
    fd, tmp_out = tempfile.mkstemp(prefix=os.path.basename(out_abs) + '.', suffix='.tmp', dir=out_dir)
    TMP = q(tmp_out)
    try:
        os.close(fd)
        t0 = time.time()
        con.execute(f"""
            COPY (
              SELECT p.* REPLACE ({POLICY} AS thumbnail_url)
              FROM read_parquet({SRC}) p
              LEFT JOIN oc_thumbs oc ON p.pid = oc.pid
              ORDER BY p.row_id
            )
            TO {TMP} (FORMAT PARQUET, COMPRESSION ZSTD)
        """)
        print(f'[{time.time()-t0:.1f}s] wrote {tmp_out}')

        # --- verify before moving into place ----------------------------------------
        # (a) output row_id non-null/unique, same count as src, physically ascending
        #     (file_row_number is DuckDB's explicit file order);
        # (b) every src row joins exactly one out row on row_id (with (a) and equal
        #     counts this proves the row_id sets are identical);
        # (c) per row: thumbnail_url == POLICY exactly, and EVERY other column is
        #     unchanged (IS DISTINCT FROM on each, list columns included).
        t0 = time.time()
        n_out, n_out_rowid, n_out_distinct, n_order_breaks = con.execute(f"""
            SELECT COUNT(*), COUNT(row_id), COUNT(DISTINCT row_id),
                   COUNT(*) FILTER (WHERE prev IS NOT NULL AND row_id <= prev)
            FROM (SELECT row_id, lag(row_id) OVER (ORDER BY file_row_number) AS prev
                  FROM read_parquet({TMP}, file_row_number = true))
        """).fetchone()
        other_cols = [c for c in src_cols if c != 'thumbnail_url']
        qi = lambda name: '"' + name.replace('"', '""') + '"'      # quote an identifier
        unchanged_pred = " OR ".join(f'p.{qi(c)} IS DISTINCT FROM o.{qi(c)}' for c in other_cols)
        joined, mismatched, other_changed, replaced, overlap, changed, with_thumb = con.execute(f"""
            SELECT
              COUNT(*),
              COUNT(*) FILTER (WHERE o.thumbnail_url IS DISTINCT FROM ({POLICY})),
              COUNT(*) FILTER (WHERE {unchanged_pred}),
              COUNT(*) FILTER (WHERE p.otype = 'MaterialSampleRecord' AND oc.thumbnail_url IS NOT NULL),
              COUNT(*) FILTER (WHERE p.otype = 'MaterialSampleRecord' AND oc.thumbnail_url IS NOT NULL
                                 AND NULLIF(TRIM(p.thumbnail_url), '') IS NOT NULL),
              COUNT(*) FILTER (WHERE o.thumbnail_url IS DISTINCT FROM p.thumbnail_url),
              COUNT(*) FILTER (WHERE NULLIF(TRIM(o.thumbnail_url), '') IS NOT NULL)
            FROM read_parquet({SRC}) p
            JOIN read_parquet({TMP}) o ON p.row_id = o.row_id
            LEFT JOIN oc_thumbs oc ON p.pid = oc.pid
        """).fetchone()
        problems = []
        if not (n_out == n_out_rowid == n_out_distinct == n_src):
            problems.append(f'row_id count/uniqueness: out {n_out:,} (non-null {n_out_rowid:,}, distinct {n_out_distinct:,}) vs src {n_src:,}')
        if joined != n_src: problems.append(f'row_id sets differ: {joined:,} of {n_src:,} src rows found in out')
        if n_order_breaks: problems.append(f'{n_order_breaks:,} rows out of ascending row_id order')
        if mismatched: problems.append(f'{mismatched:,} rows whose thumbnail_url != policy')
        if other_changed: problems.append(f'{other_changed:,} rows with a non-thumbnail column changed')
        print(f'[{time.time()-t0:.1f}s] verified: {n_out:,} rows, same row_id set, ascending, {len(other_cols)} other columns unchanged; '
              f'replaced {replaced:,} (of which {overlap:,} already had a value), {changed:,} rows changed, '
              f'{with_thumb:,} rows with a thumbnail')
        if problems:
            print('ERROR: verification failed: ' + '; '.join(problems), file=sys.stderr)
            return 5
        # Publish order: hash the verified temp, drop any old sidecar, THEN rename —
        # so a fresh output can never sit next to a stale manifest (losing the
        # sidecar on a failed rename is the safer failure).
        out_bytes = os.path.getsize(tmp_out)
        out_sha = sha256_file(tmp_out)
        if os.path.exists(mpath):
            os.remove(mpath)
        os.replace(tmp_out, out_abs)
    finally:
        if os.path.exists(tmp_out):
            os.remove(tmp_out)
    print(f'output: {out_bytes/1e6:.1f} MB  sha256 {out_sha}')

    if not args.no_manifest:
        manifest = {
            "script": os.path.basename(__file__),
            "script_sha256": sha256_file(os.path.abspath(__file__)),
            "argv": sys.argv,
            "git_sha": git_sha(),
            "script_dirty_vs_git_sha": git_dirty(),
            "environment": {
                "duckdb_version": duckdb.__version__,
                "python": platform.python_version(),
                "platform": platform.platform(),
                "threads": args.threads,
                "parquet": {"compression": "ZSTD", "row_group_size": "duckdb default"},
            },
            "policy": ("OC thumbnails: OC is authoritative for MaterialSampleRecord rows (thumbnail_url "
                       "replaced by the pid's OC URL); other entity types untouched; one URL per pid "
                       "(lexically smallest; fails on conflicts unless --allow-multi); rows emitted in "
                       "ascending row_id; output verified row-by-row (policy + every other column) before rename. "
                       "Reproducible chain step 2 (REPRODUCIBLE_PIPELINE_PLAN_2026-08-25.md)"),
            "inputs": {
                "src": {"path": args.src, "bytes": src_bytes, "sha256": src_sha},
                "oc":  {"path": args.oc,  "bytes": oc_bytes,  "sha256": oc_sha},
            },
            "counts": {
                "src_rows": n_src,
                "src_rows_null_pid": n_null_pid,
                "oc_pids_with_thumbnail": n_pids,
                "oc_pids_multi_thumbnail": n_multi,
                "msr_rows_replaced": replaced,
                "msr_rows_replaced_that_had_a_value": overlap,
                "rows_changed": changed,
                "out_rows": n_out,
                "out_rows_with_thumbnail": with_thumb,
            },
            "output": {"path": args.out, "bytes": out_bytes, "sha256": out_sha},
        }
        fd, mtmp = tempfile.mkstemp(prefix=os.path.basename(mpath) + '.', suffix='.tmp', dir=out_dir)
        try:
            with os.fdopen(fd, 'w') as fh:
                json.dump(manifest, fh, indent=2)
            os.replace(mtmp, mpath)
        finally:
            if os.path.exists(mtmp):
                os.remove(mtmp)
        print(f'manifest -> {mpath}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
