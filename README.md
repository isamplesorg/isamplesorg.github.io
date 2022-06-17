---
title: isamples.github.io
subtitle: README for the isamples.github.io source
---

# isamplesorg.github.io

This repository provides the source for [isamplesorg.github.io](https://isamplesorg.github.io). 

The site uses the [Quarto](https://quarto.org/) and is built using GitHub actions.

Sources are in markdown or "quarto markdown" (`.qmd` files), and may include content computed at build time.

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

Vocabulary documentation is generated from the vocabulary source ttl files using a python script, `scripts/vocab2md.py` and a convenience shell script wrapper, `scripts/generate_vocab_docs.sh`. To regenerate the vocabulary documentation, first `cd` to the root folder of the documentation, then:

```
scripts/generate_vocab_docs.sh
```

The output is placed under `models/generated/vocabularies`

After editing, push the sources to GitHub. The rendered pages are generated using the `Render using Quarto and push to GH-pages` GitHub action that is currently manually triggered.

