---
title: isamples.github.io
subtitle: README for the isamples.github.io source
---

# isamplesorg.github.io

This repository provides the source for [SMR fork isamplesorg.github.io](https://smrgeoinfo.github.io/isamplesorg.github.io/). 

The site uses the [Quarto](https://quarto.org/) and is built using GitHub actions.

Sources are in markdown or "quarto markdown" (`.qmd` files), and may include content computed at build time.

Visit the [Quarto site](https://quarto.org/docs/guide/) for documentation on using the Quarto environment and features.

## Tutorials

The `tutorials/` directory contains interactive data analysis tutorials:

- **`isamples_explorer.qmd`** - Interactive search and exploration of 6.7M samples
- **`zenodo_isamples_analysis.qmd`** - Deep-dive DuckDB-WASM analysis tutorial
- **`parquet_cesium_isamples_wide.qmd`** - Cesium-based 3D globe visualization
- **`narrow_vs_wide_performance.qmd`** - Technical schema comparison

All tutorials use browser-based analysis with DuckDB-WASM - no server required.

## Development

For simple editing tasks, the sources may be edited directly on GitHub. A local setup will be beneficial for larger or more complex changes.

To setup a development environment:

1. [Install Quarto](https://quarto.org/docs/get-started/)
2. Create a python virtual environment, e.g. `mkvirtualenv isamples-quarto`
3. `git clone https://github.com/isamplesorg/isamplesorg.github.io.git`
4. `cd isamplesorg.github.io`

Preview the site:
```
quarto preview
```

### Vocabulary page generation

The vocabulary pages under `models/generated/vocabularies/` (e.g. [material_sample_object_type.html](https://isamples.org/models/generated/vocabularies/material_sample_object_type.html)) are produced by a deterministic two-stage pipeline:

1. **TTL → markdown.** `scripts/generate_vocab_docs.sh` fetches each `.ttl` from [isamplesorg/vocabularies](https://github.com/isamplesorg/vocabularies) (and the extension repos) and runs `vocab markdown <ttl-url>` — the `vocab` CLI from [isamplesorg/vocab_tools](https://github.com/isamplesorg/vocab_tools), installed via `pipx` in CI. The output is written as a `.qmd` (core vocabularies) or `.md` (extensions) into `models/generated/`.
2. **Markdown → HTML.** `quarto render` walks the site and applies the theme, navigation, and sidebar defined in `_quarto.yml` to every page, including the generated vocabulary markdown. The site chrome comes from Quarto; the vocabulary content is untouched.

Both stages run in the [`quarto-pages.yml`](.github/workflows/quarto-pages.yml) GitHub Action on every deploy.

To regenerate locally, from the repo root:

```
scripts/generate_vocab_docs.sh
quarto render
```

**Note on `scripts/vocab2md.py`.** An earlier version of this pipeline invoked `vocab2md.py` directly. PR [#48](https://github.com/isamplesorg/isamplesorg.github.io/pull/48) switched to the `vocab markdown` CLI entry point — same tool, same transform. The `vocab2md.py` file is retained for reference but is no longer part of the build.

After editing, push the sources to GitHub. The rendered pages are generated using the `Render using Quarto and push to GH-pages` GitHub action that is currently manually triggered.

Updating dependencies using `pip -U <<package name>>` and regenerate `requirements.txt` with `pip freeze > requirements.txt`.

## Data Sources

All tutorials query parquet files hosted on Cloudflare R2:

```javascript
// Wide format (recommended) - 280 MB, 20M rows
const WIDE_URL = "https://data.isamples.org/isamples_202601_wide.parquet";

// Narrow format (advanced) - 850 MB, 106M rows
const NARROW_URL = "https://data.isamples.org/isamples_202512_narrow.parquet";
```

## Related Repositories

| Repo | Purpose | Start Here |
|------|---------|------------|
| [isamplesorg-metadata](https://github.com/isamplesorg/metadata) | Schema definition (8 types, 14 predicates) | `src/schemas/isamples_core.yaml` |
| [isamples-python](https://github.com/isamplesorg/examples) | Jupyter examples (DuckDB + Lonboard) | `examples/basic/isamples_explorer.ipynb` |
| [vocabularies](https://github.com/isamplesorg/vocabularies) | SKOS vocabulary terms | Material types, context categories |
