Developer Guide
===============

Layout
------

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Path
     - Contents
   * - ``papermeister/``
     - Core: models, database, ingestion, OCR, extraction, search, Zotero
   * - ``papermeister/paths.py``
     - Every user-data path. The only module that knows where data lives
   * - ``desktop/``
     - The current app — ``views/``, ``services/``, ``components/``,
       ``workers/``, ``windows/``, ``theme/``
   * - ``papermeister/ui/``
     - The older GUI. Frozen; two dialogs are still reused by the new app
   * - ``scripts/``
     - Operational one-offs (migrations, bulk re-processing, audits)
   * - ``tests/``
     - pytest suite
   * - ``devlog/``
     - Design notes, plans and implementation records

Data model
----------

::

   Source ──> Folder ──> Paper ──> PaperFile   (hash, status)
                          ├──────> Author
                          ├──────> Passage ──> passage_fts
                          ├──────> PaperBiblio   (extracted metadata)
                          └──────> Reference ──> Paper | CitedWork

``Paper`` is one document. ``PaperFile`` is an attachment of it. ``Passage`` is
one page of OCR text. ``PaperBiblio`` holds extracted metadata separately from
the curated fields, tagged by source model. A ``Reference`` resolves to either a
held ``Paper`` or an external ``CitedWork`` — never both, and neither means it
could not be identified.

Full-text search uses two FTS5 indexes: ``passage_fts`` over page text
(external-content, so the text is not duplicated) and ``paper_fts`` over titles
and authors. Both are maintained by triggers — never write to them directly.

Running things
--------------

.. code-block:: bash

   python -m desktop      # the app
   python cli.py --help   # command line
   pytest                 # tests
   ruff check .           # lint
   make lock-check        # verify the lockfiles match requirements

Where data lives
----------------

``papermeister/paths.py`` is the single source of truth. Everything sits under
``~/PaleoBytes/PaperMeister`` — the layout shared with Modan2 and CTHarvester —
and ``PAPERMEISTER_DATA_DIR`` overrides it, which is how the tests exercise path
resolution without touching a real home directory.

An installation predating this still has ``~/.papermeister``. That directory
keeps being used as long as the new one does not exist; nothing is moved
automatically, because a library here is gigabytes and may have a batch running
against it. ``scripts/migrate_data_dir.py`` does the move when asked. Once the
new directory exists it wins — after a migration both can be present, and the
leftover must not pull the app back to the stale copy.

Conventions
-----------

**Scripts that change data take** ``--execute``. Without it they print a dry-run
preview. There is no ``--dry-run`` flag; dry run is the default.

**Every fix gets a regression test.** The test should fail against the old
behaviour — verify that, rather than assuming it.

**devlog files** record the reasoning, not the diff — git already has the diff.
Naming: ``YYYYMMDD_P##_title.md`` for plans, ``YYYYMMDD_R##_title.md`` for
reviews and audits, ``YYYYMMDD_###_title.md`` for implementation records.

**HANDOFF.md** is the state of play between sessions. Read it first; update it
last.

Dependencies
------------

``requirements.txt`` and ``requirements-dev.txt`` declare ranges;
``requirements.lock`` and ``requirements-dev.lock`` pin exact versions with
hashes. CI and release builds install from the locks, so a shipped build
contains exactly what CI tested.

.. code-block:: bash

   make lock          # re-lock after editing requirements*.txt
   make lock-upgrade  # deliberately take newer versions
   make lock-check    # what CI runs

``make lock`` keeps existing pins as preferences and moves only what must move,
so an unrelated upstream release does not churn the lock.

Continuous integration
----------------------

.. list-table::
   :header-rows: 1
   :widths: 26 74

   * - Workflow
     - Purpose
   * - ``test.yml``
     - ruff and mypy, then the suite on Linux and Windows. Coverage is measured
       on Linux with a ratchet floor
   * - ``security.yml``
     - pip-audit against the lockfile, plus the lock-check gate. Also weekly
   * - ``codeql.yml``
     - Static analysis of our own code, on push and weekly
   * - ``build.yml``
     - Manual packaging run for all three platforms
   * - ``release.yml``
     - Tag ``v*.*.*`` → test, build, publish with checksums
   * - ``manual-release.yml``
     - Same, triggered by hand, for pre-releases and re-cuts
   * - ``dependabot-lock-refresh.yml``
     - Regenerates the locks on a Dependabot PR so its checks can pass
   * - ``docs.yml``
     - Builds this manual and deploys it to GitHub Pages

mypy runs against a list of modules that are already clean, and the list grows
as more are cleaned — it is a ratchet, not a blanket check.

Releasing
---------

1. Add a section to ``CHANGELOG.md`` for the version
2. Bump ``version.py``
3. Tag ``vX.Y.Z`` and push

``release.yml`` runs the tests, builds all three platforms, and publishes a
release whose notes are the CHANGELOG section for that version — so the
changelog stays the single source of truth. Build numbers come from the commit
count, which keeps tagged and manual builds consistent.

Building the manual
-------------------

.. code-block:: bash

   pip install -r docs/manual/requirements.txt
   cd docs/manual && make html      # _build/html/index.html

Korean translations live in ``locale/ko/LC_MESSAGES/``. Refresh the catalogs
after changing English text:

.. code-block:: bash

   make gettext
   sphinx-intl update -p _build/gettext -l ko
