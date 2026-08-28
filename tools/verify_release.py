#!/usr/bin/env python3
"""verify_release.py — hash a release's data files, and re-verify any host against those hashes.

Two modes:

  hash   Walk a release directory and write a *release hash manifest*: every
         .parquet/.json file (relative path, bytes, sha256). This is the
         machine-readable statement of "these exact bytes are release X".

           python3 tools/verify_release.py hash --dir ~/Data/iSample/pqg_refining/202609/publish \
               --release-id isamples_202609 --out provenance/isamples_202609/release_hashes.json

  check  Re-download (or re-read) every file named in that manifest from a host
         (--base https://data.isamples.org) or a directory (--dir) and compare
         size and sha256. Exit 0 only if every file matches.

           python3 tools/verify_release.py check --manifest provenance/isamples_202609/release_hashes.json \
               --base https://data.isamples.org
           python3 tools/verify_release.py check --manifest ... --dir /path/to/mirror --only 'isamples_202609_h3_*'

         Files are streamed; nothing is kept on disk. A wrong size fails fast
         (HEAD) before the body is fetched. --only takes a glob over the
         relative path; --skip-prefix drops e.g. the 900-shard search index
         when a quick check is wanted (say so in the report — a skipped file is
         not a verified file).

This is the reproducibility programme's step 8 (REPRODUCIBLE_PIPELINE_PLAN_2026-08-25.md):
a build's hashes (from the per-step manifests) are recorded once, and any copy —
R2, a mirror, a Zenodo deposit unpacked locally — can be checked against them.
The #334 release manifest (size/etag) stays the Explorer's boot-time cross-check;
this one is the byte-level truth.
"""
import argparse
import datetime
import fnmatch
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

CHUNK = 1 << 20
EXTS = (".parquet", ".json")
# data.isamples.org sits behind Cloudflare, which answers urllib's default
# "Python-urllib" agent with 403; identify ourselves instead.
UA = "isamples-verify-release/1 (+https://github.com/isamplesorg/isamplesorg.github.io)"


def _req(url, method="GET"):
    return urllib.request.Request(url, method=method, headers={"User-Agent": UA})


def sha256_path(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_url(url, expected_bytes=None, timeout=60):
    """Stream a URL, returning (bytes_read, sha256). HEAD first to fail fast on size."""
    with urllib.request.urlopen(_req(url, "HEAD"), timeout=timeout) as r:
        cl = r.headers.get("Content-Length")
        if expected_bytes is not None and cl is not None and int(cl) != expected_bytes:
            return int(cl), None  # size mismatch: don't bother downloading
    h = hashlib.sha256()
    n = 0
    with urllib.request.urlopen(_req(url), timeout=timeout) as r:
        for chunk in iter(lambda: r.read(CHUNK), b""):
            h.update(chunk)
            n += len(chunk)
    return n, h.hexdigest()


def cmd_hash(args):
    root = os.path.abspath(args.dir)
    files = {}
    for dirpath, _, names in os.walk(root):
        for name in sorted(names):
            if not name.endswith(EXTS) or name.endswith(".manifest.json"):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if args.only and not fnmatch.fnmatch(rel, args.only):
                continue
            files[rel] = {"bytes": os.path.getsize(full), "sha256": sha256_path(full)}
            print(f"  {files[rel]['sha256'][:12]}  {files[rel]['bytes']:>12,}  {rel}")
    if not files:
        print("ERROR: no files found", file=sys.stderr)
        return 2
    doc = {
        "schema": "release_hashes/1",
        "release_id": args.release_id,
        "generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "source_dir": root.replace(os.path.expanduser("~"), "~"),
        "file_count": len(files),
        "total_bytes": sum(f["bytes"] for f in files.values()),
        "files": dict(sorted(files.items())),
    }
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
        with open(args.out, "w") as fh:
            json.dump(doc, fh, indent=1)
        print(f"wrote {args.out}: {len(files)} files, {doc['total_bytes']/1e6:.1f} MB")
    else:
        json.dump(doc, sys.stdout, indent=1)
    return 0


def cmd_check(args):
    with open(args.manifest) as fh:
        doc = json.load(fh)
    files = doc["files"]
    if bool(args.base) == bool(args.dir):
        print("ERROR: give exactly one of --base or --dir", file=sys.stderr)
        return 2
    base = args.base.rstrip("/") if args.base else None
    ok = mismatch = missing = skipped = 0
    rows = []
    for rel, exp in files.items():
        if args.only and not fnmatch.fnmatch(rel, args.only):
            skipped += 1
            continue
        if args.skip_prefix and rel.startswith(args.skip_prefix):
            skipped += 1
            continue
        try:
            if base:
                n, digest = sha256_url(f"{base}/{rel}", exp["bytes"], timeout=args.timeout)
            else:
                path = os.path.join(args.dir, rel)
                if not os.path.exists(path):
                    raise FileNotFoundError(path)
                n = os.path.getsize(path)
                digest = sha256_path(path) if n == exp["bytes"] else None
        except (urllib.error.HTTPError, urllib.error.URLError, FileNotFoundError) as e:
            missing += 1
            rows.append(("MISSING", rel, str(e)[:80]))
            print(f"  MISSING   {rel}  ({str(e)[:60]})")
            continue
        if n != exp["bytes"]:
            mismatch += 1
            rows.append(("SIZE", rel, f"{n} != {exp['bytes']}"))
            print(f"  SIZE      {rel}  {n:,} != {exp['bytes']:,}")
        elif digest != exp["sha256"]:
            mismatch += 1
            rows.append(("SHA256", rel, f"{digest[:12]} != {exp['sha256'][:12]}"))
            print(f"  SHA256    {rel}  {digest[:12]}… != {exp['sha256'][:12]}…")
        else:
            ok += 1
            if args.verbose:
                print(f"  ok        {rel}")
    target = base or os.path.abspath(args.dir)
    verdict = "VERIFIED" if (mismatch == 0 and missing == 0 and ok > 0) else "FAILED"
    print(f"\n{verdict}: {doc.get('release_id')} on {target} — {ok} ok, {mismatch} mismatched, {missing} missing, "
          f"{skipped} skipped (of {len(files)} listed)" + ("" if not skipped else "  [skipped files are NOT verified]"))
    if args.report:
        with open(args.report, "w") as fh:
            json.dump({"release_id": doc.get("release_id"), "target": target, "verdict": verdict,
                       "checked_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                       "ok": ok, "mismatched": mismatch, "missing": missing, "skipped": skipped,
                       "problems": [{"kind": k, "file": f, "detail": d} for k, f, d in rows]}, fh, indent=1)
    return 0 if verdict == "VERIFIED" else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1], formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("hash", help="write a release hash manifest from a directory")
    h.add_argument("--dir", required=True)
    h.add_argument("--release-id", required=True)
    h.add_argument("--out")
    h.add_argument("--only", help="glob over the relative path")
    h.set_defaults(fn=cmd_hash)
    c = sub.add_parser("check", help="verify a host or directory against a release hash manifest")
    c.add_argument("--manifest", required=True)
    c.add_argument("--base", help="e.g. https://data.isamples.org")
    c.add_argument("--dir", help="local mirror directory")
    c.add_argument("--only", help="glob over the relative path")
    c.add_argument("--skip-prefix", help="skip files under this relative prefix (reported as skipped)")
    c.add_argument("--timeout", type=int, default=120)
    c.add_argument("--report", help="write a JSON report")
    c.add_argument("-v", "--verbose", action="store_true")
    c.set_defaults(fn=cmd_check)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
