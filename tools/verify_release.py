#!/usr/bin/env python3
"""verify_release.py — hash a release's data files, and re-verify any host against those hashes.

Two modes:

  hash   Walk a release directory and write a *release hash manifest*: every
         .parquet/.json file except *.manifest.json build sidecars (relative
         path, bytes, sha256). Complete for a quiescent directory — there is
         deliberately no filter, so a manifest can never look authoritative
         while omitting files.

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
         "Matches" means: matched when read. Files are checked one after
         another; a target that changes while the run is in progress (or a
         directory being written while `hash` walks it) is outside the
         contract — verify quiescent, versioned copies. Files are streamed,
         never stored. Redirects are refused (a "mirror"
         that redirects to the origin is not a copy). Bodies are requested
         unencoded (Accept-Encoding: identity) and any Content-Encoding fails
         the file. A wrong HEAD size fails fast before the body is fetched.
         --dir checks refuse a symlink at the file itself; an ancestor
         directory symlink that still resolves inside --dir is accepted.

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
import tempfile
import urllib.error
import urllib.parse
import urllib.request

CHUNK = 1 << 20
EXTS = (".parquet", ".json")
SCHEMA = "release_hashes/1"
# Relative paths a manifest may contain: '/'-separated segments of
# [A-Za-z0-9._-], no empty/'.'/'..' segments, no leading slash, no trailing
# slash, nothing URL- or shell-significant.
SEG_RE = re.compile(r"[A-Za-z0-9._\-]+")


def valid_rel_path(rel):
    if not isinstance(rel, str) or not rel or rel.startswith("/") or rel.endswith("/"):
        return False
    segs = rel.split("/")
    return all(SEG_RE.fullmatch(seg) and seg not in (".", "..") for seg in segs)


def resolved_inside(path, root):
    """True if realpath(path) is root or beneath it."""
    try:
        return os.path.commonpath([os.path.realpath(path), root]) == root
    except ValueError:          # different drives (Windows)
        return False


def same_file(a, b):
    """True if two paths name the same inode (catches hard links, not just symlinks)."""
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def write_json_atomic(path, obj):
    """Write via a temp file in the destination directory, then os.replace()."""
    d = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(obj, fh, indent=1)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def parse_base(base):
    """Validate --base: http(s), a host, no query/fragment; return it normalised."""
    u = urllib.parse.urlsplit(base)
    if u.scheme not in ("http", "https") or not u.netloc or u.query or u.fragment or "?" in base or "#" in base:
        raise ValueError(f"--base must be http(s)://host[/path] without query or fragment: {base!r}")
    return urllib.parse.urlunsplit((u.scheme, u.netloc, u.path.rstrip("/"), "", ""))
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
    if not os.path.isdir(root):
        print(f"ERROR: not a directory: {args.dir}", file=sys.stderr)
        return 2
    if not args.release_id.strip():
        print("ERROR: --release-id must be non-empty", file=sys.stderr)
        return 2
    if args.out and resolved_inside(os.path.dirname(os.path.realpath(args.out)) or ".", root):
        print("ERROR: --out must not be inside --dir (it would become an unlisted or self-invalidating file)", file=sys.stderr)
        return 2
    files = {}
    skipped_links = []

    def _walk_error(err):          # an unreadable subtree would silently shrink the manifest
        raise err

    try:
        walk = list(os.walk(root, followlinks=False, onerror=_walk_error))
    except OSError as e:
        print(f"ERROR: cannot read the whole release dir: {e}", file=sys.stderr)
        return 2
    for dirpath, dirnames, names in walk:
        if os.path.islink(dirpath) or any(os.path.islink(os.path.join(dirpath, d)) for d in dirnames):
            for d in dirnames:
                if os.path.islink(os.path.join(dirpath, d)):
                    skipped_links.append(os.path.relpath(os.path.join(dirpath, d), root) + "/")
        for name in sorted(names):
            if not name.endswith(EXTS) or name.endswith(".manifest.json"):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            if os.path.islink(full):
                skipped_links.append(rel)        # a symlink is not release content
                continue
            if not valid_rel_path(rel):
                print(f"ERROR: path not representable in a manifest: {rel}", file=sys.stderr)
                return 2
            if args.out and same_file(full, args.out):
                print(f"ERROR: --out is the same file as release content {rel}", file=sys.stderr)
                return 2
            try:
                with open(full, "rb") as f:
                    n, digest = hash_and_count(f)
            except OSError as e:
                print(f"ERROR: cannot read {rel}: {e}", file=sys.stderr)
                return 2
            files[rel] = {"bytes": n, "sha256": digest}
            print(f"  {digest[:12]}  {n:>12,}  {rel}")
    if skipped_links:
        print(f"ERROR: {len(skipped_links)} symlinked entr(y/ies) in the release dir (a manifest describes real files only): "
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
        write_json_atomic(args.out, doc)
        print(f"wrote {args.out}: {len(files)} files, {doc['total_bytes']/1e6:.1f} MB")
    else:
        json.dump(doc, sys.stdout, indent=1)
    return 0


def load_manifest(path):
    def _int(v):
        return isinstance(v, int) and not isinstance(v, bool) and v >= 0

    with open(path, "rb") as fh:
        raw = fh.read()
    doc = json.loads(raw)
    if not isinstance(doc, dict):
        raise ValueError("manifest is not a JSON object")
    if doc.get("schema") != SCHEMA:
        raise ValueError(f"unexpected manifest schema {doc.get('schema')!r} (want {SCHEMA})")
    if not isinstance(doc.get("release_id"), str) or not doc["release_id"]:
        raise ValueError("missing release_id")
    files = doc.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("manifest has no files")
    if not _int(doc.get("file_count")) or doc["file_count"] != len(files):
        raise ValueError(f"file_count {doc.get('file_count')!r} != {len(files)} entries")
    total = 0
    for rel, e in files.items():
        if not valid_rel_path(rel):
            raise ValueError(f"bad path in manifest: {rel!r}")
        if not isinstance(e, dict) or not _int(e.get("bytes")):
            raise ValueError(f"bad entry for {rel}")
        if not (isinstance(e.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", e["sha256"])):
            raise ValueError(f"bad sha256 for {rel}")
        total += e["bytes"]
    if not _int(doc.get("total_bytes")) or doc["total_bytes"] != total:
        raise ValueError(f"total_bytes {doc.get('total_bytes')!r} != sum {total}")
    doc["_manifest_sha256"] = hashlib.sha256(raw).hexdigest()
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
    try:
        base = parse_base(args.base) if args.base else None
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    root = os.path.realpath(args.dir) if args.dir else None
    if root and not os.path.isdir(root):
        print(f"ERROR: not a directory: {args.dir}", file=sys.stderr)
        return 2
    if args.report:
        rp = os.path.realpath(args.report)
        if (root and resolved_inside(rp, root)) or same_file(args.report, args.manifest) or rp == os.path.realpath(args.manifest):
            print("ERROR: --report must not be inside --dir nor alias the manifest", file=sys.stderr)
            return 2
        if root and any(same_file(args.report, os.path.join(root, rel)) for rel in files):
            print("ERROR: --report is the same file (hard link) as a listed release file", file=sys.stderr)
            return 2
    checked, problems, skipped = [], [], []
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
            checked.append(rel)
            if args.verbose:
                print(f"  ok        {rel}")
    ok = len(checked)
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
        write_json_atomic(args.report, {"release_id": doc["release_id"], "target": target, "verdict": verdict, "exit_code": code,
                       "checked_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
                       "manifest": os.path.abspath(args.manifest), "manifest_sha256": doc["_manifest_sha256"],
                       "only": args.only, "skip_prefix": args.skip_prefix,
                       "ok": ok, "verified_files": checked,
                       "problems": [{"kind": k, "file": f, "detail": d} for k, f, d in problems],
                       "skipped": skipped})
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
