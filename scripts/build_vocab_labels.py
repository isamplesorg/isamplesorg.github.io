#!/usr/bin/env python3
"""
Build vocab_labels.parquet from the SKOS TTL vocabularies that iSamples uses.

The Explorer and Python notebooks need a stable lookup from vocabulary URIs
(e.g. https://w3id.org/isample/vocabulary/sampledfeature/1.0/pasthumanoccupationsite)
to human-readable labels (e.g. "Past human occupation site"). This script
parses every SKOS TTL listed in scripts/generate_vocab_docs.sh, emits one row
per (concept URI, language) pair, and writes a single parquet file.

Output columns:
    uri          str    Concept URI (vocab-form OR data-form — see uri_form)
    uri_form     str    "vocab"   = URI as declared in the TTL
                        "data_v1" = synthesized URI with "/1.0/" version
                                    segment after the scheme root (the
                                    convention used in iSamples export
                                    records and downstream parquet files).
    pref_label   str    skos:prefLabel (or rdfs:label fallback)
    lang         str    BCP47 language tag, default "en"
    scheme       str    skos:inScheme URI (or derived)
    definition   str?   skos:definition (best-available language)
    alt_labels   list   skos:altLabel values plus prefLabels from any
                        cross-vocab redeclarations of the same URI.
    source_ttl   str    URL of the TTL the canonical row came from.
    broader      str?   canonical skos:broader parent (lexicographically first
                        when a concept has several; see broader_count)
    broader_count int   number of skos:broader parents declared

The dual-form (vocab + data_v1) emission is a workaround for a known
mismatch: the vocabulary TTLs declare concepts without a version segment,
but iSamples export records carry URIs with a "/1.0/" segment. See
issue #148 for the full background.

Issue: https://github.com/isamplesorg/isamplesorg.github.io/issues/148

Usage:
    pip install -r scripts/requirements.txt
    python scripts/build_vocab_labels.py              # writes ./vocab_labels.parquet
    python scripts/build_vocab_labels.py -o /tmp/v.parquet
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import rdflib
from rdflib.namespace import RDF, RDFS, SKOS

# Keep this list in sync with scripts/generate_vocab_docs.sh.
# When a new vocabulary is added there, add it here too.
VOCAB_TTLS: list[str] = [
    # Core iSamples vocabularies
    "https://raw.githubusercontent.com/isamplesorg/vocabularies/main/vocabulary/material_type.ttl",
    "https://raw.githubusercontent.com/isamplesorg/vocabularies/main/vocabulary/sampled_feature_type.ttl",
    "https://raw.githubusercontent.com/isamplesorg/vocabularies/main/vocabulary/material_sample_object_type.ttl",
    # Earth Science extension
    "https://raw.githubusercontent.com/isamplesorg/metadata_profile_earth_science/main/vocabulary/earthenv_material_extension_mineral_group.ttl",
    "https://raw.githubusercontent.com/isamplesorg/metadata_profile_earth_science/main/vocabulary/earthenv_material_extension_rock_sediment.ttl",
    "https://raw.githubusercontent.com/isamplesorg/metadata_profile_earth_science/main/vocabulary/earthenv_sampled_feature_role.ttl",
    "https://raw.githubusercontent.com/isamplesorg/metadata_profile_earth_science/main/vocabulary/earthenv_materialsampleobject_type.ttl",
    # Archaeology / OpenContext extension
    "https://raw.githubusercontent.com/isamplesorg/metadata_profile_archaeology/main/vocabulary/opencontext_material_extension.ttl",
    "https://raw.githubusercontent.com/isamplesorg/metadata_profile_archaeology/main/vocabulary/opencontext_materialsampleobjecttype.ttl",
    # Biology extension
    "https://raw.githubusercontent.com/isamplesorg/metadata_profile_biology/main/vocabulary/biology_sampledfeature_extension.ttl",
]

PREFERRED_LANG = "en"

# Deprecated / legacy concept URIs that are absent from the live SKOS TTLs but
# still appear in older source data (e.g. SESAR records using the specimentype/1.0
# namespace, superseded by materialsampleobjecttype/1.0). These rows are injected
# directly so the Explorer can display human-readable labels instead of raw URI
# path tails. Each entry: (uri, pref_label, lang, scheme).
# Issue #283b: 169 SESAR records carry these deprecated URIs.
MANUAL_LABEL_OVERRIDES: list[tuple[str, str, str, str | None]] = [
    (
        "https://w3id.org/isample/vocabulary/specimentype/1.0/othersolidobject",
        "Other solid object",
        "en",
        "https://w3id.org/isample/vocabulary/specimentype/1.0/",
    ),
    (
        "https://w3id.org/isample/vocabulary/specimentype/1.0/physicalspecimen",
        "Material sample",
        "en",
        "https://w3id.org/isample/vocabulary/specimentype/1.0/",
    ),
]

# When a concept URI is declared in more than one TTL, prefer the row whose
# source TTL's URL contains one of these path fragments. The fragments are
# matched against the concept URI: a URI containing "vocabulary/material/"
# prefers a row from a TTL URL containing "vocabulary/material" (i.e. the
# core material_type.ttl) over OpenContext or Earth Sci redeclarations.
CANONICAL_TTL_HINTS: tuple[tuple[str, str], ...] = (
    ("vocabulary/material/",                "vocabularies/main/vocabulary/material_type"),
    ("vocabulary/sampledfeature/",          "vocabularies/main/vocabulary/sampled_feature_type"),
    ("vocabulary/materialsampleobjecttype/", "vocabularies/main/vocabulary/material_sample_object_type"),
    ("vocabulary/specimentype/",             "vocabularies/main/vocabulary/material_sample_object_type"),
)


def _data_form_uris(vocab_uri: str) -> list[str]:
    """Synthesize the URI form(s) used in iSamples export records.

    Each iSamples scheme uses its own version segment and slug-casing
    convention (yes, really — see issue #148). Returns possibly-multiple
    aliases when the data layer uses inconsistent casing.
    """
    # Biology data is inconsistent: most slugs are Title-cased (Animalia,
    # Fungi, Plantae) but some are lowercase (bacteria, protozoa). Emit
    # both forms so JOINs hit either variant.
    def _bio_variants(s: str) -> list[str]:
        if not s:
            return []
        title = s[:1].upper() + s[1:]
        lower = s.lower()
        return list(dict.fromkeys([title, lower]))

    # (scheme_root, version_segment, slug_variants_fn_or_None)
    KNOWN_ROOTS: tuple[tuple[str, str, callable | None], ...] = (
        ("https://w3id.org/isample/vocabulary/material/",                 "1.0", None),
        ("https://w3id.org/isample/vocabulary/sampledfeature/",           "1.0", None),
        ("https://w3id.org/isample/vocabulary/materialsampleobjecttype/", "1.0", None),
        ("https://w3id.org/isample/vocabulary/specimentype/",             "1.0", None),
        # OpenContext extension uses /0.1/ rather than /1.0/.
        ("https://w3id.org/isample/opencontext/material/",                "0.1", None),
        ("https://w3id.org/isample/opencontext/materialsampleobjecttype/","0.1", None),
        # Biology extension: /1.0/ + inconsistent slug casing in the data.
        ("https://w3id.org/isample/biology/biosampledfeature/",           "1.0", _bio_variants),
    )
    for root, version, variants in KNOWN_ROOTS:
        if vocab_uri.startswith(root):
            slug = vocab_uri[len(root):]
            # Don't re-version a URI that already has a version segment.
            if slug.split("/", 1)[0].replace(".", "").isdigit():
                return []
            slugs = variants(slug) if variants is not None else [slug]
            return [f"{root}{version}/{s}" for s in slugs]
    return []


def _prefers(ttl_url: str, concept_uri: str) -> int:
    """Return a sort key — lower is more canonical for tie-breaking.
    A TTL whose URL matches the concept URI's expected canonical TTL gets 0;
    everything else gets 1.
    """
    for uri_fragment, ttl_fragment in CANONICAL_TTL_HINTS:
        if uri_fragment in concept_uri and ttl_fragment in ttl_url:
            return 0
    return 1


def _pick_definition(g: rdflib.Graph, c: rdflib.term.Node) -> str | None:
    """Return one definition string, preferring English when present."""
    # Lexical order within each language tier so the choice is a function of
    # the TTL content, not of rdflib's traversal order.
    defs = sorted(g.objects(c, SKOS.definition),
                  key=lambda d: (getattr(d, "language", None) != PREFERRED_LANG, str(d)))
    return str(defs[0]) if defs else None


def _pick_scheme(g: rdflib.Graph, c: rdflib.term.Node) -> str | None:
    """Return the skos:inScheme URI for a concept, if declared."""
    schemes = sorted(str(s) for s in g.objects(c, SKOS.inScheme))
    return schemes[0] if schemes else None


def extract_rows(ttl_url: str, data: bytes | None = None) -> list[dict]:
    """Parse one TTL. `ttl_url` is always the canonical (main) URL recorded as
    `source_ttl`; when `data` is given those exact bytes are parsed instead of
    fetching the network (reproducible builds, --ttl-dir) — the caller hashes
    the same buffer, so the manifest's sha256 is of what was parsed."""
    g = rdflib.Graph()
    if data is not None:
        # publicID keeps the canonical URL as the base IRI, so any relative
        # IRI in the file resolves exactly as it does when fetched from main.
        g.parse(data=data, format="turtle", publicID=ttl_url)
    else:
        g.parse(ttl_url, format="turtle")

    rows: list[dict] = []
    for c in g.subjects(RDF.type, SKOS.Concept):
        uri = str(c)
        scheme = _pick_scheme(g, c)
        definition = _pick_definition(g, c)
        alt_labels = sorted({str(a) for a in g.objects(c, SKOS.altLabel)})
        # skos:broader parent (#281/#282 tree). SKOS permits multiple parents
        # (a DAG); pick the lexicographically-first as the canonical primary so
        # the column is deterministic, and stash the full set for the validator
        # to flag multi-parent concepts. Vocab-form here; aliased to data-form
        # in _emit_data_form_aliases so uri↔broader join within each uri_form.
        broaders = sorted(str(b) for b in g.objects(c, SKOS.broader))
        broader_vocab = broaders[0] if broaders else None
        broader_count = len(broaders)

        # One row per language of skos:prefLabel; fall back to rdfs:label.
        # Sorted by (language, text): a concept with two same-language labels
        # then yields a deterministic winner in _dedupe (see its tiebreak).
        pref_labels = sorted(g.objects(c, SKOS.prefLabel), key=lambda l: (str(getattr(l, "language", None) or ""), str(l)))
        if not pref_labels:
            pref_labels = sorted(g.objects(c, RDFS.label), key=lambda l: (str(getattr(l, "language", None) or ""), str(l)))

        if not pref_labels:
            # Concept with no label at all — emit a row with NULL label so
            # downstream JOINs at least know the URI exists.
            rows.append({
                "uri": uri,
                "uri_form": "vocab",
                "pref_label": None,
                "lang": None,
                "scheme": scheme,
                "definition": definition,
                "alt_labels": alt_labels,
                "broader": broader_vocab,
                "broader_count": broader_count,
                "source_ttl": ttl_url,
            })
            continue

        for lit in pref_labels:
            rows.append({
                "uri": uri,
                "uri_form": "vocab",
                "pref_label": str(lit),
                "lang": getattr(lit, "language", None) or PREFERRED_LANG,
                "scheme": scheme,
                "definition": definition,
                "alt_labels": alt_labels,
                "broader": broader_vocab,
                "broader_count": broader_count,
                "source_ttl": ttl_url,
            })
    return rows


def _dedupe(rows: list[dict]) -> list[dict]:
    """Collapse cross-vocab duplicate (uri, lang) rows.

    Strategy:
      - For each (uri, lang), pick the row whose source TTL is the canonical
        owner of that URI's scheme (see CANONICAL_TTL_HINTS).
      - Move any losing rows' pref_labels into the survivor's alt_labels list
        so we don't lose information.
    """
    from collections import defaultdict
    groups: dict[tuple[str, str | None], list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["uri"], r["lang"])].append(r)

    out: list[dict] = []
    for (uri, lang), candidates in groups.items():
        if len(candidates) == 1:
            out.append(candidates[0])
            continue
        candidates.sort(key=lambda r: (_prefers(r["source_ttl"], r["uri"]), r["source_ttl"], r["pref_label"] or ""))
        keep = dict(candidates[0])
        extra = []
        for loser in candidates[1:]:
            if loser["pref_label"] and loser["pref_label"] != keep["pref_label"]:
                extra.append(loser["pref_label"])
        if extra:
            keep["alt_labels"] = sorted(set((keep.get("alt_labels") or []) + extra))
        out.append(keep)
    return out


def _emit_data_form_aliases(rows: list[dict]) -> list[dict]:
    """For each vocab-form row, emit an alias row at the /1.0/ data-form URI
    so JOINs against iSamples export-derived URIs work without normalization.
    """
    aliases: list[dict] = []
    for r in rows:
        for data_uri in _data_form_uris(r["uri"]):
            clone = dict(r)
            clone["uri"] = data_uri
            clone["uri_form"] = "data_v1"
            # Map the parent to its data form too, so a data_v1 row's `broader`
            # joins to another data_v1 row's `uri` (same alias space). If the
            # parent has no known data-form alias, leave the vocab-form parent
            # (the validator flags any broader that resolves to no node).
            parent = r.get("broader")
            if parent:
                parent_data = _data_form_uris(parent)
                if parent_data:
                    clone["broader"] = parent_data[0]
            aliases.append(clone)
    return aliases


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent,
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        return None


def _git_dirty() -> bool | None:
    try:
        return bool(subprocess.check_output(["git", "status", "--porcelain", "--", str(Path(__file__).resolve())],
                                            cwd=Path(__file__).parent, stderr=subprocess.DEVNULL).decode().strip())
    except Exception:
        return None


def _local_ttl_path(ttl_dir: Path, url: str) -> Path:
    """Archived layout: <ttl_dir>/<repo-name>/<file>.ttl for
    https://raw.githubusercontent.com/isamplesorg/<repo-name>/main/vocabulary/<file>.ttl"""
    parts = url.split("/")
    repo = parts[4]
    return ttl_dir / repo / parts[-1]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument(
        "-o", "--output",
        default="vocab_labels.parquet",
        type=Path,
        help="Output parquet path (default: ./vocab_labels.parquet)",
    )
    ap.add_argument(
        "--also-csv",
        action="store_true",
        help="Also emit a sibling .csv for diff-friendly review.",
    )
    ap.add_argument(
        "--allow-partial",
        action="store_true",
        help=(
            "Continue and emit an artifact even if one or more TTL sources "
            "fail to fetch/parse. Default is to fail-loud, since this "
            "artifact is intended for publishing."
        ),
    )
    ap.add_argument(
        "--ttl-dir",
        type=Path,
        default=None,
        help=(
            "Read the TTLs from this archive directory (layout <dir>/<repo>/<file>.ttl, "
            "as written by the 202609 provenance freeze) instead of fetching main. "
            "source_ttl still records the canonical main URL. Required for a reproducible build."
        ),
    )
    ap.add_argument(
        "--ttl-archive",
        type=Path,
        default=None,
        help="Optional ttl_archive.json (per-file commit + sha256) to copy into the manifest and to VERIFY the archived bytes against.",
    )
    ap.add_argument("--no-manifest", action="store_true", help="skip writing {output}.manifest.json")
    args = ap.parse_args(argv)
    effective_args = list(argv) if argv is not None else sys.argv[1:]

    t_start = time.time()
    # ttl_inputs_pinned = every expected TTL was read from the archive, its bytes
    # verified against ttl_archive.json (sha256) and attributed to a 40-hex git
    # commit. Rows from MANUAL_LABEL_OVERRIDES come from this script, not from a
    # TTL, and are reported separately.
    if (args.ttl_dir is None) != (args.ttl_archive is None):
        print("ERROR: --ttl-dir and --ttl-archive must be given together", file=sys.stderr)
        return 2
    archive_index: dict[str, dict] = {}
    if args.ttl_archive:
        recs = json.loads(args.ttl_archive.read_text())
        for rec in recs:
            if rec["source_ttl"] in archive_index:
                print(f"ERROR: duplicate record in {args.ttl_archive}: {rec['source_ttl']}", file=sys.stderr)
                return 2
            if not (isinstance(rec.get("commit"), str) and re.fullmatch(r"[0-9a-f]{40}", rec["commit"])):
                print(f"ERROR: {args.ttl_archive}: record for {rec['source_ttl']} lacks a 40-hex commit", file=sys.stderr)
                return 2
            if not (isinstance(rec.get("sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", rec["sha256"])):
                print(f"ERROR: {args.ttl_archive}: record for {rec['source_ttl']} lacks a sha256", file=sys.stderr)
                return 2
            archive_index[rec["source_ttl"]] = rec
        missing = [u for u in VOCAB_TTLS if u not in archive_index]
        extra = [u for u in archive_index if u not in VOCAB_TTLS]
        if missing or extra:
            print(f"ERROR: {args.ttl_archive} does not describe exactly the {len(VOCAB_TTLS)} expected TTLs "
                  f"(missing {len(missing)}, unexpected {len(extra)})", file=sys.stderr)
            for u in missing: print(f"  missing: {u}", file=sys.stderr)
            for u in extra: print(f"  unexpected: {u}", file=sys.stderr)
            return 2

    ttl_inputs: list[dict] = []          # only TTLs whose rows are IN the output
    all_rows: list[dict] = []
    failures: list[tuple[str, str]] = []
    for url in VOCAB_TTLS:
        local = None
        data = None
        if args.ttl_dir is not None:
            # Archive integrity is never "partial": a missing or altered file is fatal.
            # Read ONCE; hash and parse the same buffer.
            local = _local_ttl_path(args.ttl_dir, url)
            if not local.exists():
                print(f"ERROR: archived TTL missing: {local}", file=sys.stderr)
                return 2
            data = local.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            rec = archive_index[url]
            if rec["sha256"] != digest:
                print(f"ERROR: archived TTL sha256 {digest[:12]}… != ttl_archive.json {rec['sha256'][:12]}… for {local}",
                      file=sys.stderr)
                return 2
        try:
            n_before = len(all_rows)
            rows = extract_rows(url, data)
            all_rows.extend(rows)
            if data is not None:
                ttl_inputs.append({"source_ttl": url, "local_path": str(local), "bytes": len(data),
                                   "sha256": digest, "commit": archive_index[url]["commit"], "rows": len(rows)})
            else:
                ttl_inputs.append({"source_ttl": url, "local_path": None, "rows": len(rows),
                                   "note": "fetched live from main (NOT pinned)"})
            print(f"  {len(all_rows) - n_before:>4} rows  {url}{'  [archived]' if local else ''}")
        except Exception as e:
            print(f"WARN: failed to parse {url}: {e}", file=sys.stderr)
            failures.append((url, str(e)))

    if failures and not args.allow_partial:
        print(
            f"\nERROR: {len(failures)} TTL source(s) failed; refusing to "
            f"emit a partial artifact. Pass --allow-partial to override.",
            file=sys.stderr,
        )
        for url, err in failures:
            print(f"  - {url}: {err}", file=sys.stderr)
        return 3

    if not all_rows:
        print("ERROR: no rows extracted; aborting.", file=sys.stderr)
        return 2

    # Inject manual overrides for deprecated URIs not present in any live TTL.
    # These are appended before dedupe so _dedupe can merge them if they ever
    # appear in a future TTL revision, and so _emit_data_form_aliases does NOT
    # re-emit them (they already carry the /1.0/ version segment).
    for uri, label, lang, scheme in MANUAL_LABEL_OVERRIDES:
        all_rows.append({
            "uri": uri,
            "uri_form": "data_v1",   # already in the /1.0/ data form
            "pref_label": label,
            "lang": lang,
            "scheme": scheme,
            "definition": None,
            "alt_labels": [],
            "broader": None,          # deprecated leaf concepts; no tree parent
            "broader_count": 0,
            "source_ttl": "manual_override",
        })
    print(f"  {len(MANUAL_LABEL_OVERRIDES):>4} rows  (manual overrides for deprecated URIs)")

    raw_count = len(all_rows)
    all_rows = _dedupe(all_rows)
    deduped_collapsed = raw_count - len(all_rows)
    print(f"\nDedupe: collapsed {deduped_collapsed} cross-vocab duplicate rows.")

    aliases = _emit_data_form_aliases(all_rows)
    print(f"Aliases: emitted {len(aliases)} data-form (/1.0/) rows.")
    all_rows.extend(aliases)

    df = pd.DataFrame(all_rows)
    # Explicit total order: rows by (uri_form, uri, lang, source_ttl) — unique
    # once the duplicate check below passes — and each row's alt_labels sorted.
    # Together with the deterministic selectors above (definition, scheme,
    # prefLabel, broader) the rows are a function of the TTL bytes + this
    # script + the RDF parser (rdflib version recorded; blank-node ids would
    # vary between parses, but these vocabularies use absolute IRIs only);
    # the Parquet BYTES are additionally a function of the pandas/pyarrow
    # writer versions recorded in the manifest.
    df["alt_labels"] = df["alt_labels"].apply(lambda v: sorted(v) if isinstance(v, list) else v)
    df = df.sort_values(["uri_form", "uri", "lang", "source_ttl"], kind="mergesort", na_position="last").reset_index(drop=True)
    # Final sanity check
    dupes = int(df.duplicated(subset=["uri", "lang"], keep=False).sum())
    if dupes:
        # With duplicates the (uri_form, uri, lang, source_ttl) order is no longer
        # total and the artifact would not be a function of its inputs — refuse.
        print(f"ERROR: {dupes} duplicate (uri, lang) rows survived dedupe; refusing to emit", file=sys.stderr)
        return 4

    args.output.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.output, index=False)
    print(f"\nWrote {len(df):,} rows → {args.output}")
    print(f"  by uri_form: {df['uri_form'].value_counts().to_dict()}")
    # Surface the SKOS DAG (#281/#282): concepts with >1 skos:broader parent.
    # We keep the lexicographically-first as the canonical `broader` (a lossy
    # tree projection); flag the count so the hierarchy build/UI can account for it.
    if "broader_count" in df.columns:
        multi = df[(df["uri_form"] == "vocab") & (df["broader_count"].fillna(0) > 1)]["uri"].nunique()
        print(f"  multi-parent (DAG) concepts: {multi} (canonical primary parent kept; lossy projection)")
    print(f"  unique URIs: {df['uri'].nunique():,}")
    print(f"  languages:   {sorted(df['lang'].dropna().unique().tolist())}")
    print(f"  schemes:     {df['scheme'].nunique()} distinct skos:inScheme values")

    if args.also_csv:
        csv_path = args.output.with_suffix(".csv")
        df.to_csv(csv_path, index=False)
        print(f"Also wrote {csv_path}")

    if not args.no_manifest:
        import pyarrow
        manifest = {
            "script": Path(__file__).name,
            "script_sha256": _sha256(Path(__file__).resolve()),
            "args": effective_args,
            "git_sha": _git_sha(),
            "script_dirty_vs_git_sha": _git_dirty(),
            "environment": {"python": platform.python_version(), "platform": platform.platform(),
                            "rdflib": rdflib.__version__, "pandas": pd.__version__, "pyarrow": pyarrow.__version__},
            "policy": ("SKOS prefLabels/altLabels/definitions/broader from the expected vocabulary TTLs; deterministic "
                       "selectors (lexical tiebreaks); cross-vocab dedupe; /1.0/ data-form aliases; rows sorted by "
                       "(uri_form, uri, lang, source_ttl), alt_labels sorted; duplicate (uri, lang) is fatal. "
                       "Rows are a function of the TTL bytes + this script + the recorded rdflib and pandas (final sort); "
                       "Parquet bytes additionally of the recorded pyarrow writer. This manifest itself (args, paths, "
                       "elapsed) is not byte-reproducible."),
            "ttl_inputs_pinned": args.ttl_dir is not None and not failures and len(ttl_inputs) == len(VOCAB_TTLS),
            "archive_verified": args.ttl_dir is not None,
            "complete": not failures,
            "inputs": {"expected_ttls": len(VOCAB_TTLS), "ttls": ttl_inputs,
                       "failed": [{"source_ttl": u, "error": e} for u, e in failures],
                       "script_defined_rows": {"manual_overrides": len(MANUAL_LABEL_OVERRIDES),
                                               "source_ttl_value": "manual_override"}},
            "counts": {"rows": int(len(df)), "unique_uris": int(df["uri"].nunique()),
                       "by_uri_form": {k: int(v) for k, v in df["uri_form"].value_counts().to_dict().items()}},
            "output": {"path": str(args.output), "bytes": args.output.stat().st_size, "sha256": _sha256(args.output)},
            "elapsed_s": round(time.time() - t_start, 1),
        }
        mpath = Path(str(args.output) + ".manifest.json")
        mpath.write_text(json.dumps(manifest, indent=2))
        print(f"manifest -> {mpath}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
