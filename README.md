# isamplesorg.github.io

This repository provides the [iSamples web site](https://isamplesorg.github.io/). 

It is a [Sphinx]() project configured to used the
sphinx-book-theme and supports both Markdown and 
reStructuredText formats.

The pages are built automatically using github actions
after a commit to the main branch.

## Development 

Dependencies are managed using [Poetry](https://python-poetry.org/). To setup a local
work environment:

```
git clone
cd isamplesorg.github.io
poetry install
```

Building the docs:

```
cd docs
make html
```

or to start a webserver locally and and automatically
refresh pages on edit:

```
cd docs
make livehtml
```



