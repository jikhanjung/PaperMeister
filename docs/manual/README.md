# docs/manual

Sphinx source for the PaperMeister manual, published to GitHub Pages by
`.github/workflows/docs.yml` on every push to `main` that touches this
directory.

- `.rst` is what gets published. Markdown is pulled in only where a file has to
  live elsewhere — currently just the repository-root `CHANGELOG.md`.
- The version shown in the docs is single-sourced from `version.py`.

Local preview:

```bash
pip install -r requirements.txt
make html          # _build/html/index.html
make livehtml      # auto-rebuilding preview, if sphinx-autobuild is installed
```

After changing English text, refresh the Korean catalogs:

```bash
make gettext
sphinx-intl update -p _build/gettext -l ko
```

Then translate the empty `msgstr` entries in `locale/ko/LC_MESSAGES/*.po` and
compile them:

```bash
sphinx-intl build          # .po -> .mo (committed; docs.yml does not compile)
```

**Korean and RST markup**: a closing `**` or ``` `` ``` must be followed by
whitespace or punctuation, but Korean attaches its particle directly — writing
`**일시정지**한 뒤` silently drops the markup. End such a run with an escaped
space, `**일시정지**\ 한 뒤`, which renders as nothing.

Entries deliberately left untranslated are literals: file paths, workflow
filenames and status codes.
