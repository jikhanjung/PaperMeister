Quick Start
===========

This walks a Zotero library from nothing to searchable full text and a citation
network. Each step is resumable — interrupting a batch and re-running it picks
up where it stopped.

1. Connect Zotero
-----------------

Settings → **Zotero** tab → enter ``user_id`` and API key → OK.

The app syncs on startup and whenever you press **Sync** in the left rail.
Collections appear as a tree under the *My Library* tab; papers show in the
middle list.

The first sync only fetches metadata. PDFs stay in Zotero until they are needed.

2. Run OCR
----------

Right-click a collection → **Process Folder (OCR → Biblio)**, or right-click
*My Library* → **Process All** for the whole library.

The Process window shows progress per file. Each PDF is downloaded, sent to the
OCR backend, and its text stored page by page. Results are cached in
``~/.papermeister/ocr_json/``, so re-processing a paper is free.

Watch the status pill in the paper list:

.. list-table::
   :header-rows: 1
   :widths: 12 88

   * - Pill
     - Meaning
   * - ``wait``
     - PDF present, not processed yet
   * - ``OCR``
     - text extracted, no bibliographic data yet
   * - ``done``
     - metadata extracted and applied
   * - ``rev``
     - extracted metadata disagrees with Zotero — needs your review
   * - ``err``
     - processing failed
   * - ``skip``
     - not a PDF (supplementary file, link attachment)
   * - ``—``
     - no PDF attached

3. Extract bibliographic data
-----------------------------

If automatic extraction is on, this follows OCR without any action. Otherwise
right-click a paper → **Extract Biblio**.

The result is stored in a separate table, never written over your Zotero data
directly. When the extraction agrees with what Zotero already has, or fills
empty fields only, it is applied automatically. When it conflicts, the paper is
marked ``rev`` and waits for you.

To review: select the paper, open the **Metadata** tab, and compare the two
columns field by field. Pick a side per row, edit the value if neither is right,
then **Apply**.

4. Parse reference lists
------------------------

Right-click a paper, a collection, or *My Library* → **Extract References**.

Each paper's bibliography is located, split into entries, and parsed into
structured fields. Entries are then matched against papers you already hold — by
DOI first, then by title with author and year as corroboration. Everything else
becomes an external *cited work*.

The **References** tab of a paper shows both directions: works it cites, and
papers in your library that cite it.

5. Search
---------

Type in the search box and press Enter. Search covers the full OCR text of every
page, plus titles and author names, so a paper is findable by a term that never
appears in its body.

Results show a snippet with the matched words in bold; opening a result
highlights the matches inside the **Text** tab.

6. See the citation network
---------------------------

Right-click a paper → **Show in citation network** for an interactive graph
centred on it: what it cites, what cites it, and the external works it cites.
Click any node to re-centre.

The rail's **Cited Works** view lists external works by how often your library
cites them — a direct answer to "what do I keep citing but not own?"
