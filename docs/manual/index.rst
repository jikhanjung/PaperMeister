PaperMeister Documentation
==========================

PaperMeister turns a collection of academic PDFs into a searchable, linked
knowledge base. It reads your papers with OCR, extracts their bibliographic
metadata and reference lists, and connects them into a citation network — while
keeping Zotero as the library you already curate.

The guiding principle is **store first, understand later**: the OCR full text is
the source of truth, and everything else — metadata, references, citation
links — is a derived layer that can be regenerated at any time.

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   installation
   quick_start
   user_guide
   faq
   troubleshooting
   developer_guide
   changelog

Features
--------

* **Zotero as the library** — collections, items and attachments sync both ways;
  extracted metadata can be written back to Zotero, or kept local
* **OCR everything** — every PDF goes through OCR regardless of whether it has a
  text layer, so the corpus is uniform. Raw OCR JSON is cached and reusable
* **Bibliographic extraction** — an LLM reads the first pages and proposes
  title, authors, year, journal, volume/issue/pages and DOI, stored separately
  from your curated data so nothing is overwritten silently
* **Reference lists and a citation network** — reference sections are parsed
  into structured entries, matched against papers you hold, and de-duplicated
  into canonical nodes for the works you don't
* **Full-text search** — SQLite FTS5 over every page, with title/author boosting
  and match highlighting
* **Local folders too** — a directory of PDFs can be imported alongside Zotero

Where things live
-----------------

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Path
     - Contents
   * - ``~/.papermeister/papermeister.db``
     - SQLite database (papers, authors, passages, references)
   * - ``~/.papermeister/ocr_json/``
     - Cached OCR output, one file per PDF
   * - ``~/.papermeister/preferences.json``
     - Credentials and settings
   * - ``~/.papermeister/logs/``
     - OCR, sync and extraction logs

Indices and tables
==================

* :ref:`genindex`
* :ref:`search`
