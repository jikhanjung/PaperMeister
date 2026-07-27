Troubleshooting
===============

Each entry below describes something that has actually happened, and how it
presents.

OCR or extraction stops making progress
---------------------------------------

**Symptom** — the progress window sits still, or the log fills with
``502 upstream: All connection attempts failed`` and
``500 EngineCore encountered an issue``.

**Cause** — the 502 is a symptom, not the fault: the front proxy is answering,
but the model worker behind it died and is restarting. The 500 is that worker on
its way out. Repeating in a cycle means it is crash-looping, usually out of GPU
memory.

**What the app does** — brief outages are absorbed by a short retry. A sustained
one pauses the batch, polls the server, and resumes automatically when it comes
back, keeping the queue intact.

**What to check** — the server's own log for the actual crash (out of memory, a
CUDA fault). Running OCR and the language model on the same GPU makes this more
likely.

A paper comes back "PARTIAL"
----------------------------

Part of the bibliography was parsed and the rest was not. The parsed entries are
saved; the paper stays unchecked so a later run replaces them. Nothing is lost,
and re-running is safe — references are written per source, replacing the
previous set rather than accumulating.

The progress line names the reason:

``bad JSON``
   The model's answer was cut off. The batch is retried with a larger budget,
   then split, before being given up on.

``no array``
   The model answered in prose rather than data — usually because the text it
   was handed is not a bibliography.

``timeout``
   No answer within the time limit. The batch is split and retried.

Details, including the offending response, go to
``~/.papermeister/logs/biblio_YYYYMMDD.log``.

Zotero write-back fails with 403
--------------------------------

The API key is read-only. Either issue a key with write permission on the
library, or turn write-back off in Settings → Zotero and keep changes local.

Zotero rejects an update with 400
---------------------------------

Usually a field that does not exist on that item type — for example a journal
name on a ``bookSection``. The app maps journal-like fields per item type and
will say which field was refused. For a standalone PDF with no parent item,
promote it to a real item first.

A PDF will not download
-----------------------

If the attachment record exists but the file is not in Zotero's storage, the
download returns 404 and the paper is marked failed. Check whether the file
opens in Zotero itself; if it only exists on your local disk, it needs to be
uploaded to Zotero first.

The frozen app fails to start on Windows
----------------------------------------

If you built it yourself: build in a clean virtual environment with conda **off**
the PATH. Building inside a conda shell mixes conda's Qt libraries into the
bundle, and the frozen app then dies with a missing-procedure error.
``build_desktop_clean.bat`` does this correctly.

The database is damaged
-----------------------

Do not run scripts against the live database from WSL while the Windows app is
writing to it — the two disagree about file locking and can desynchronise an
index.

Recovery is usually cheap, because index damage does not lose rows: copy the
database somewhere local, ``REINDEX`` the affected index, and confirm with
``PRAGMA integrity_check``. Take a backup with ``VACUUM INTO`` before any bulk
operation.

Search finds nothing for a word I can see
-----------------------------------------

Check the **Text** tab: if the page is blank there, OCR did not capture it and
the paper needs reprocessing. Search reads the stored text, not the PDF.
