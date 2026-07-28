Frequently Asked Questions
==========================

Does PaperMeister change my Zotero library?
-------------------------------------------

Only if you turn on write-back, which is off by default. With it off, everything
stays in the local database. Note the trade-off: local-only changes can be
overwritten the next time Zotero is pulled, since Zotero remains the source of
truth for items it owns.

Why OCR a PDF that already has a text layer?
--------------------------------------------

Consistency. Embedded text layers vary enormously in quality and layout
fidelity, especially for scanned journals and multi-column articles. Running
everything through the same pipeline makes the corpus uniform, and page-level
text comparable across papers. The cost is paid once — results are cached.

Where is my data?
-----------------

The library — the SQLite database, the OCR cache and the logs — is under
``~/PaleoBytes/PaperMeister/``. PDFs are not copied there; they stay in Zotero or
in the folder you imported.

Settings are the exception, and live wherever your OS keeps configuration:
``%LOCALAPPDATA%\PaleoBytes\PaperMeister`` on Windows, ``~/.config/…`` on Linux,
``~/Library/Application Support/…`` on macOS. They are specific to the machine
and hold your API keys, so they stay put if you ever move or copy the library.

Can I re-run extraction with a different model?
-----------------------------------------------

Yes. Results are stored per model, so a new run is added rather than replacing
the old one. This is deliberate — it lets you compare models on the same paper
without losing the earlier answer.

What happens if a batch is interrupted?
---------------------------------------

Nothing is lost. Every stage records what it completed, and re-running the same
action resumes from there. Closing the window mid-batch is a safe way to stop.

A paper shows "no references section" — is that wrong?
------------------------------------------------------

Not necessarily. Letters, abstracts, plates, obituaries and front matter
genuinely have no bibliography, and that is recorded as a completed check rather
than a failure. A paper that *does* have references but returns nothing is
treated differently: it stays unchecked so a later run retries it.

Are non-English papers supported?
---------------------------------

Yes. OCR and extraction handle Korean, Japanese, Chinese, Russian and European
languages. Author-name splitting understands CJK conventions. Reference-section
headings are recognised in many languages and scripts.

Which platform should I use?
----------------------------

Windows is the best-tested. Linux and macOS builds are produced and smoke-tested
by CI but see far less real use. The macOS build is not notarized.
