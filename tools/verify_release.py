#!/usr/bin/env python3
"""verify_release.py — hash a release's data files, and re-verify any host against those hashes.

Two modes:

  hash   Walk a release directory and write a *release hash manifest*: every
         .parquet/.json file (relative path, bytes, sha256). Always complete —
         there is deliberately no filter, so a manifest can never look
         authoritative while omitting files.

           python3 tools/verify_release.py hash --dir ~/Data/iSample/pqg_refining/202609/publish \
               --release-id isamples_202609 --out provenance/isamples_202609/release_hashes.json

  check  Re-download (or re-read) every file named in that manifest from a host
         (--base https://data.isamples.org) or a directory (--dir) and compare
         size and sha256.

           python3 tools/verify_release.py check --manifest provenance/isamples_202609/release_hashes.json \
               --base https://data.isamples.org
           python3 tools/verify_release.py check --manifest ... --dir /path/to/mirror --only 'isamples_202609_h3_*'

         Verdicts and exit codes:
           VERIFIED (0)  every listed file was checked and matches
           PARTIAL  (3)  every *checked* file matches but --only/--skip-prefix left
                         some unchecked; exit 0 only with --allow-partial
           FAILED   (1)  a mismatch, a missing file, or an operational error
         Files are streamed, never stored. Redirects are refused (a "mirror"
         that redirects to the origin is not a copy). Bodies are requested
         unencoded (Accept-Encoding: identity) and any Content-Encoding fails
         the file. A wrong HEAD size fails fast before the body is fetched.

This is the reproducibility programme's step 8 (REPRODUCIBLE_PIPELINE_PLAN_2026-08-25.md):
a build's hashes are recorded once, and any copy — R2, a mirror, a Zenodo deposit
unpacked locally — can be checked against them. The #334 release manifest
(size/etag) stays the Explorer's boot-time cross-check; this one is the
byte-level truth.
"""
import argparse
import datetime
import fnmatch
import hashlib
import http.client
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

CHUNK = 1 << 20
EXTS = (".parquet", ".json")
SCHEMA = "release_hashes/1"
# Relative paths a manifest may contain: plain segments, '/' separators, no '..',
# no absolute paths, no backslashes, no URL-significant characters.
PATH_RE = re.compile(r"^(?!/)(?!.*(^|/)\.\.(/|$))[A-Za-z0-9._\-/]+$")
# data.isamples.org sits behind Cloudflare, which answers urllib's default
# "Python-urllib" agent with 403; identify ourselves instead.
UA = "isamples-verify-release/1 (+https://github.com/isamplesorg/isamplesorg.github.io)"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, f"redirect to {newurl} refused (not a copy)", headers, fp)


_OPENER = urllib.request.build_opener(_NoRedirect)


def _open(url, method="GET", timeout=120):
    req = urllib.request.Request(url, method=method,
                                 headers={"User-Agent": UA, "Accept-Encoding": "identity"})
    return _OPENER.open(req, timeout=timeout)


def hash_and_count(fobj):
    """Return (bytes_read, sha256) over one read pass, so size and digest agree."""
    h = hashlib.sha256()
    n = 0
    for chunk in iter(lambda: fobj.read(CHUNK), b""):
        h.update(chunk)
        n += len(chunk)
    return n, h.hexdigest()


def fetch_hash(url, expected_bytes, timeout):
    """Stream `url`; return (bytes_read, sha256 | None, note). Fails fast on a
    HEAD size mismatch; verifies GET status/framing; a short body is a failure."""
    try:
        with _open(url, "HEAD", timeout) as r:
            cl = r.headers.get("Content-Length")
            if cl is not None and int(cl) != expected_bytes:
                return int(cl), None, "HEAD size"
    except urllib.error.HTTPError as e:
        if e.code not in (405, 501):      # HEAD unsupported: fall through to GET
            raise
    with _open(url, "GET", timeout) as r:
        if r.status != 200:
            raise urllib.error.HTTPError(url, r.status, "non-200 GET", r.headers, None)
        enc = r.headers.get("Content-Encoding")
        if enc and enc.lower() != "identity":
            return 0, None, f"Content-Encoding {enc}"
        cl = r.headers.get("Content-Length")
        if cl is not None and int(cl) != expected_bytes:
            return int(cl), None, "GET size"
        n, digest = hash_and_count(r)
    return n, digest, ""


def cmd_hash(args):
    root = os.path.realpath(args.dir)
    files = {}
    skipped_links = []
    for dirpath, dirnames, names in os.walk(root, followlinks=False):
        dirnames.sort()
        for name in sorted(names):
            if not name.endswith(EXTS) or name.endswith(".manifest.json"):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if os.path.islink(full):
                skipped_links.append(rel)        # a symlink is not release content
                continue
            if not PATH_RE.match(rel):
                print(f"ERROR: path not representable in a manifest: {rel}", file=sys.stderr)
                return 2
            with open(full, "rb") as f:
                n, digest = hash_and_count(f)
            files[rel] = {"bytes": n, "sha256": digest}
            print(f"  {digest[:12]}  {n:>12,}  {rel}")
    if skipped_links:
        print(f"ERROR: {len(skipped_links)} symlinked file(s) in the release dir (not hashed): "
              + ", ".join(skipped_links[:5]), file=sys.stderr)
        return 2
    if not files:
        print("ERROR: no files found", file=sys.stderr)
        return 2
    doc = {
        "schema": SCHEMA,
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


def load_manifest(path):
    with open(path) as fh:
        doc = json.load(fh)
    if doc.get("schema") != SCHEMA:
        raise ValueError(f"unexpected manifest schema {doc.get('schema')!r} (want {SCHEMA})")
    files = doc.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("manifest has no files")
    if doc.get("file_count") != len(files):
        raise ValueError(f"file_count {doc.get('file_count')} != {len(files)} entries")
    total = 0
    for rel, e in files.items():
        if not PATH_RE.match(rel):
            raise ValueError(f"bad path in manifest: {rel!r}")
        if not (isinstance(e.get("bytes"), int) and e["bytes"] >= 0):
            raise ValueError(f"bad bytes for {rel}")
        if not (isinstance(e.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", e["sha256"])):
            raise ValueError(f"bad sha256 for {rel}")
        total += e["bytes"]
    if doc.get("total_bytes") != total:
        raise ValueError(f"total_bytes {doc.get('total_bytes')} != sum {total}")
    return doc


def cmd_check(args):
    if bool(args.base) == bool(args.dir):
        print("ERROR: give exactly one of --base or --dir", file=sys.stderr)
        return 2
    try:
        doc = load_manifest(args.manifest)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"ERROR: manifest rejected: {e}", file=sys.stderr)
        return 2
    files = doc["files"]
    base = args.base.rstrip("/") if args.base else None
    root = os.path.realpath(args.dir) if args.dir else None
    ok, problems, skipped = 0, [], []
    for rel, exp in files.items():
        if (args.only and not fnmatch.fnmatch(rel, args.only)) or (args.skip_prefix and rel.startswith(args.skip_prefix)):
            skipped.append(rel)
            continue
        try:
            if base:
                url = base + "/" + "/".join(urllib.parse.quote(seg, safe="") for seg in rel.split("/"))
                n, digest, note = fetch_hash(url, exp["bytes"], args.timeout)
            else:
                path = os.path.realpath(os.path.join(root, rel))
                if os.path.commonpath([root, path]) != root:
                    raise ValueError("path escapes --dir")
                if os.path.islink(os.path.join(root, rel)):
                    raise ValueError("symlink, not a copy")
                if not os.path.isfile(path):
                    raise FileNotFoundError(path)
                n = os.path.getsize(path)
                note = "size"
                digest = None
                if n == exp["bytes"]:
                    with open(path, "rb") as f:
                        n, digest = hash_and_count(f)
                    note = ""
        except (urllib.error.HTTPError, urllib.error.URLError, FileNotFoundError) as e:
            problems.append(("MISSING", rel, str(e)[:100]))
            print(f"  MISSING   {rel}  ({str(e)[:70]})")
            continue
        except (OSError, ValueError, http.client.HTTPException, TimeoutError) as e:
            problems.append(("ERROR", rel, f"{type(e).__name__}: {str(e)[:100]}"))
            print(f"  ERROR     {rel}  ({type(e).__name__}: {str(e)[:60]})")
            continue
        if digest is None or n != exp["bytes"]:
            problems.append(("SIZE", rel, f"{n} != {exp['bytes']} ({note})"))
            print(f"  SIZE      {rel}  {n:,} != {exp['bytes']:,}  ({note})")
        elif digest != exp["sha256"]:
            problems.append(("SHA256", rel, f"{digest[:12]} != {exp['sha256'][:12]}"))
            print(f"  SHA256    {rel}  {digest[:12]}… != {exp['sha256'][:12]}…")
        else:
            ok += 1
            if args.verbose:
                print(f"  ok        {rel}")
    target = base or root
    if problems or ok == 0:
        verdict, code = "FAILED", 1
    elif skipped:
        verdict, code = "PARTIAL", (0 if args.allow_partial else 3)
    else:
        verdict, code = "VERIFIED", 0
    print(f"\n{verdict}: {doc['release_id']} on {target} — {ok} ok, {len(problems)} problem(s), "
          f"{len(skipped)} skipped (of {len(files)} listed)"
          + ("" if not skipped else "  [skipped files were NOT checked]"))
    if args.report:
        with open(args.report, "w") as fh:
            json.dump({"release_id": doc["release_id"], "target": target, "verdict": verdict, "exit_code": code,
                       "checked_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                       "manifest": os.path.abspath(args.manifest), "only": args.only, "skip_prefix": args.skip_prefix,
                       "ok": ok, "problems": [{"kind": k, "file": f, "detail": d} for k, f, d in problems],
                       "skipped": skipped}, fh, indent=1)
    return code


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1], formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("hash", help="write a complete release hash manifest from a directory")
    h.add_argument("--dir", required=True)
    h.add_argument("--release-id", required=True)
    h.add_argument("--out")
    h.set_defaults(fn=cmd_hash)
    c = sub.add_parser("check", help="verify a host or directory against a release hash manifest")
    c.add_argument("--manifest", required=True)
    c.add_argument("--base", help="e.g. https://data.isamples.org")
    c.add_argument("--dir", help="local mirror directory")
    c.add_argument("--only", help="glob over the relative path (verdict becomes PARTIAL)")
    c.add_argument("--skip-prefix", help="skip files under this relative prefix (verdict becomes PARTIAL)")
    c.add_argument("--allow-partial", action="store_true", help="exit 0 on PARTIAL")
    c.add_argument("--timeout", type=int, default=120)
    c.add_argument("--report", help="write a JSON report")
    c.add_argument("-v", "--verbose", action="store_true")
    c.set_defaults(fn=cmd_check)
    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
