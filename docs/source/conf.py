# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#
# import os
# import sys
# sys.path.insert(0, os.path.abspath('.'))


# -- Project information -----------------------------------------------------

project = "iSamples"
copyright = "2020, iSamples Project"
author = "iSamples Project"

# The full version, including alpha/beta/rc tags
release = "0.1"


# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    "myst_nb",
    "sphinx.ext.autodoc",
    "sphinx.ext.doctest",
    "sphinx.ext.extlinks",
    "sphinx.ext.intersphinx",
    "sphinx.ext.todo",
    "sphinx.ext.coverage",
    "sphinx.ext.mathjax",
    "sphinx.ext.ifconfig",
    "sphinx.ext.viewcode",
    "sphinx.ext.autosummary",
    "sphinxcontrib.bibtex",
    "sphinxcontrib.plantuml",
    "sphinxcontrib.drawio",
    "sphinx_copybutton",
    "sphinx_togglebutton",
    "jupyter_sphinx",
]

# Add any paths that contain templates here, relative to this directory.
templates_path = ["_templates"]

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = []

intersphinx_mapping = {
    "python": ("https://docs.python.org/3.9", None),
}

# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = "sphinx_book_theme"
html_title = "iSamples Project"

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ["_static"]

jupyter_execute_notebooks = "cache"

html_theme_options = {
    "theme_dev_mode": True,
    "path_to_docs": "docs",
    "repository_url": "https://github.com/isamplesorg/isamplesorg.github.io",
    # "repository_branch": "gh-pages",  # For testing
    "use_edit_page_button": True,
    "use_issues_button": True,
    "use_repository_button": True,
    "expand_sections": ["reference/index"],
    # For testing
    # "home_page_in_toc": True,
    # "single_page": True,
    "extra_footer": """<small>This material is based upon work supported by the 
National Science Foundation under Grant Numbers <a href='https://nsf.gov/awardsearch/showAward?AWD_ID=2004839'>2004839</a>,
<a href='https://nsf.gov/awardsearch/showAward?AWD_ID=2004562'>2004562</a>, 
<a href='https://nsf.gov/awardsearch/showAward?AWD_ID=2004642'>2004642</a>,
and <a href='https://nsf.gov/awardsearch/showAward?AWD_ID=2004815'>2004815</a>. Any opinions, findings, and conclusions 
 or recommendations expressed in this material are those of the author(s) and do not necessarily 
 reflect the views of the National Science Foundation.</small>""",
    # "extra_navbar": "<a href='https://google.com'>Test</a>",
}
