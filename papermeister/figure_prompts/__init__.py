"""The prompts and reply schemas the figure stages send to ocrserver.

They live here, not on the server, because they are the domain rules — what
counts as a caption, what is a panel, what "do not invent" means — and the
consequences land in this database. Sending them with every request means a
fix here needs no server deploy, and the server never runs a stale copy (fsis
ran four deploys with an old checkout on its lane). The server validates
replies against the schema; the domain checks are the client's
(`figure_link`, `figure_panels`).

`version` is derived from the text, so the same wording always has the same
version and any edit makes every earlier result stale by key.
"""
from __future__ import annotations

import hashlib
import json
import os

KINDS = ('detect', 'link', 'panels')
_HERE = os.path.dirname(os.path.abspath(__file__))


def load(kind: str) -> dict:
    """{'kind', 'version', 'instructions', 'schema'} — the request's prompt block."""
    if kind not in KINDS:
        raise ValueError(f'unknown prompt kind {kind!r}')
    with open(os.path.join(_HERE, f'{kind}.md'), encoding='utf-8') as f:
        instructions = f.read()
    with open(os.path.join(_HERE, f'{kind}.schema.json'), encoding='utf-8') as f:
        schema = json.load(f)
    digest = hashlib.sha256(
        (instructions + json.dumps(schema, sort_keys=True, separators=(',', ':'))).encode('utf-8')).hexdigest()
    return {'kind': kind, 'version': f'{kind}-v1-{digest[:12]}', 'instructions': instructions, 'schema': schema}


def version(kind: str) -> str:
    return load(kind)['version']
