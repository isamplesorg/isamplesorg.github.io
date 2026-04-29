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
import sys
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
    defs = list(g.objects(c, SKOS.definition))
    if not defs:
        return None
    for d in defs:
        if getattr(d, "language", None) == PREFERRED_LANG:
            return str(d)
    return str(defs[0])


def _pick_scheme(g: rdflib.Graph, c: rdflib.term.Node) -> str | None:
    """Return the skos:inScheme URI for a concept, if declared."""
    for s in g.objects(c, SKOS.inScheme):
        return str(s)
    return None


def extract_rows(ttl_url: str) -> list[dict]:
    g = rdflib.Graph()
    g.parse(ttl_url, format="turtle")

    rows: list[dict] = []
    for c in g.subjects(RDF.type, SKOS.Concept):
        uri = str(c)
        scheme = _pick_scheme(g, c)
        definition = _pick_definition(g, c)
        alt_labels = sorted({str(a) for a in g.objects(c, SKOS.altLabel)})

        # One row per language of skos:prefLabel; fall back to rdfs:label.
        pref_labels = list(g.objects(c, SKOS.prefLabel))
        if not pref_labels:
            pref_labels = list(g.objects(c, RDFS.label))

        if not pref_labels:
            # Concept with no label at all — emit a row with NULL label so
            # downstream JOINs at least know the URI exists.
            rows.append({
                "uri": uri,
                "pref_label": None,
                "lang": None,
                "scheme": scheme,
                "definition": definition,
                "alt_labels": alt_labels,
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
        candidates.sort(key=lambda r: (_prefers(r["source_ttl"], r["uri"]), r["source_ttl"]))
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
            aliases.append(clone)
    return aliases


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
    args = ap.parse_args(argv)

    all_rows: list[dict] = []
    failures: list[tuple[str, str]] = []
    for url in VOCAB_TTLS:
        try:
            n_before = len(all_rows)
            all_rows.extend(extract_rows(url))
            print(f"  {len(all_rows) - n_before:>4} rows  {url}")
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

    raw_count = len(all_rows)
    all_rows = _dedupe(all_rows)
    deduped_collapsed = raw_count - len(all_rows)
    print(f"\nDedupe: collapsed {deduped_collapsed} cross-vocab duplicate rows.")

    aliases = _emit_data_form_aliases(all_rows)
    print(f"Aliases: emitted {len(aliases)} data-form (/1.0/) rows.")
    all_rows.extend(aliases)

    df = pd.DataFrame(all_rows)
    # Final sanity check
    dupes = df.duplicated(subset=["uri", "lang"], keep=False).sum()
    if dupes:
        print(f"WARN: {dupes} duplicate (uri, lang) rows survived dedupe", file=sys.stderr)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.output, index=False)
    print(f"\nWrote {len(df):,} rows → {args.output}")
    print(f"  by uri_form: {df['uri_form'].value_counts().to_dict()}")
    print(f"  unique URIs: {df['uri'].nunique():,}")
    print(f"  languages:   {sorted(df['lang'].dropna().unique().tolist())}")
    print(f"  schemes:     {df['scheme'].nunique()} distinct skos:inScheme values")

    if args.also_csv:
        csv_path = args.output.with_suffix(".csv")
        df.to_csv(csv_path, index=False)
        print(f"Also wrote {csv_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
