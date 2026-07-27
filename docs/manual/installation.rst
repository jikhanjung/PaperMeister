Installation
============

Download a release
------------------

Prebuilt packages are published on the `releases page
<https://github.com/jikhanjung/PaperMeister/releases>`_ for every tagged
version, with SHA256 checksums.

Windows
   Download the portable ``.zip`` and run ``PaperMeister.exe`` from the
   extracted folder, or use the installer (``.exe``) for a per-user install.

Linux
   Download the ``.AppImage``, make it executable (``chmod +x``) and run it.

macOS
   Download the ``.dmg`` and drag the app to Applications. The build is **not
   notarized**, so on first launch use Right-click → Open to get past Gatekeeper.

Windows is the best-tested platform; the Linux and macOS builds are produced by
CI but see less use.

Run from source
---------------

.. code-block:: bash

   git clone https://github.com/jikhanjung/PaperMeister.git
   cd PaperMeister
   pip install -r requirements.txt
   python -m desktop

Python 3.12 or newer is required. For a reproducible environment matching CI,
install from the hash-pinned lockfile instead:

.. code-block:: bash

   pip install --require-hashes -r requirements.lock

Two other entry points share the same database:

.. code-block:: bash

   python cli.py     # command line: import / process / search / list / show
   python main.py    # the older GUI (frozen, kept for reference)

First run
---------

Open **Settings** from the left rail and fill in what you need. Nothing is
required to browse, but each feature needs its own credentials.

Zotero
   ``user_id`` and an API key from https://www.zotero.org/settings/keys. A
   read-only key is enough unless you want write-back, which needs write
   permission on the library.

OCR
   The URL (and key, if applicable) of your OCR backend. Three are supported:
   RunPod serverless, a direct vLLM pod, and the wrapper API.

Bibliographic extraction
   Choose the LLM backend — Claude via the ``claude`` CLI, or Qwen on your own
   server. Automatic and manual extraction are separate toggles.

Settings are written to ``~/.papermeister/preferences.json``. It holds API keys
in plain text, so treat it like any other credentials file.
