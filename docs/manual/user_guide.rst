User Guide
==========

The window
----------

Four regions, left to right.

**Rail** (icon bar)
   Mode buttons — *Library* and *Search* — plus one-shot actions: *Sync*,
   *Process*, *Import folder*, *Cited Works*, *Settings*.

**Sources**
   One tab per source. Zotero appears as *My Library*; each imported local
   folder gets its own tab. Inside a tab: library-wide filters at the top
   (All Papers, Needs Review, Recent, Trash) and the collection tree below.

**Paper list**
   Status, authors, year and title. Click a column header to sort. Ctrl+click a
   row to reveal which collection it lives in. Right-click for the actions that
   apply to that paper's current state.

**Detail panel**
   Four tabs — *Metadata*, *PDF*, *Text*, *References*. Each keeps its own
   scroll position, and the tab you were on is restored when you switch papers.

Sources
-------

Zotero
~~~~~~

Sync is incremental: only what changed since the last run is fetched. Right-click
the *My Library* tab for a **Full Sync** when you want everything re-read.

Sync mirrors Zotero in both directions of removal — items you move to the trash
are hidden, items you delete permanently are removed locally too. Collection
membership is currently additive: a paper removed from a collection in Zotero
keeps its old link here until a full sync.

Local folders
~~~~~~~~~~~~~

Rail → **Import folder** scans a directory tree for PDFs and creates a source
tab for it. Files are identified by SHA256, so a PDF already in your Zotero
library is linked rather than duplicated — the same paper simply appears under
both tabs.

Right-click a local folder tab → **Remove** to detach it. Papers that exist only
in that folder are deleted from the database; papers shared with Zotero just
lose the folder link. Files on disk and the OCR cache are never touched.

Processing
----------

OCR runs against one of three backends, chosen in Settings: RunPod serverless, a
direct vLLM pod, or the wrapper API. The wrapper mode keeps the server's queue
filled rather than sending one file at a time, and follows the server's own
recommendation for how deep to keep that queue.

Every PDF is OCR'd, even those with a text layer, so that the corpus is uniform
and the results are directly comparable.

Files that are not PDFs — supplementary material, link-only attachments — are
marked ``skip`` rather than failing.

If the OCR server becomes unreachable mid-batch, processing pauses rather than
failing every remaining file, polls until the server returns, and resumes. The
same applies to the extraction batches.

Bibliographic data
------------------

Extraction never overwrites your curated metadata in place. Results live in
their own table, tagged with the model that produced them, so you can re-run
with a different model and compare.

What happens after extraction depends on how the result compares with Zotero:

* **Fills gaps only** — applied automatically
* **Agrees with what is there** — recorded as confirmed, no change
* **Disagrees** — the paper is flagged ``rev`` and waits for review

The review UI is the **Metadata** tab: differing fields get a radio button per
side and an editable box, so you can take Zotero's value, take the extracted
one, or type a third. Authors are one per line, ``Lastname, Firstname``.

If Zotero write-back is enabled, applying pushes the result to Zotero. With it
off, changes stay local — and may be overwritten by a later pull sync.

References and the citation network
-----------------------------------

Reference extraction locates the bibliography, splits it into entries, and parses
each into fields. Entries are then resolved:

* an entry matching a paper you hold becomes a **held** link
* everything else is canonicalised into a **cited work** node, so the same
  external paper cited by ten of your papers is one node, not ten rows

The **References** tab shows outgoing references and incoming citations
together. Held references are clickable and navigate to the paper. External ones
carry a badge showing how many of your papers cite the same work.

Rail → **Cited Works** ranks external works by citation count, with the citing
papers listed for each. Right-click a paper → **Show in citation network** for
the interactive ego graph: node fill shows direction relative to the focused
paper, the border shows whether it is held with a PDF, held without one, or
external.

Search
------

Search runs over the OCR text of every page, and separately over titles and
author names, then merges the two. Papers whose *title* matches all your terms
rank above papers that merely mention them often — a search for a taxon name
finds the monograph about it, not the hundred papers that cite it in passing.

Both plain terms and phrases in quotes work.

Settings
--------

Four tabs.

OCR
   Backend selection and credentials; queue depth; whether to wait when another
   machine is already using the server.

Biblio
   Automatic and manual extraction toggles (independent), and the LLM backend.

Zotero
   Credentials; write-back on/off; OCR JSON upload on/off; automatic parent-item
   creation for standalone PDFs.

About
   Version and the per-install client ID used to identify your OCR jobs.
