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
_CLOSING = 'Return only JSON conforming to the schema.'

#: The link answer's format. 'full' asks for `caption` + `entries`; 'segs'
#: asks for the caption once, as pieces (`link.segs.md`), and
#: `figure_segs` rebuilds the full shape on the way in — about half the
#: answer, which is what stalls a session (ocrserver P03).
LINK_FORMAT = 'segs'

#: Earlier versions whose results still count as done. A new wording makes
#: every earlier result stale by key; a version listed here is one whose
#: results are as good as a new run would give, so the rows it linked are not
#: sent again. Keyed by kind.
ACCEPTED_VERSIONS: dict[str, frozenset[str]] = {
    'link': frozenset({'link-v1-533479a75b9f'}),   # full format, 2026-09-22 .. 09-30
}


def load(kind: str, fmt: str | None = None) -> dict:
    """{'kind', 'version', 'instructions', 'schema'} — the request's prompt block.
    `fmt` picks the link answer's format (default `LINK_FORMAT`)."""
    if kind not in KINDS:
        raise ValueError(f'unknown prompt kind {kind!r}')
    with open(os.path.join(_HERE, f'{kind}.md'), encoding='utf-8') as f:
        instructions = f.read()
    with open(os.path.join(_HERE, f'{kind}.schema.json'), encoding='utf-8') as f:
        schema = json.load(f)
    fmt = fmt or (LINK_FORMAT if kind == 'link' else 'full')
    if fmt == 'segs':
        if kind != 'link':
            raise ValueError(f'no segment format for {kind!r}')
        with open(os.path.join(_HERE, 'link.segs.md'), encoding='utf-8') as f:
            appendix = f.read()
        head = instructions.rstrip().removesuffix(_CLOSING).rstrip()
        instructions = f'{head}\n\n{appendix.rstrip()}\n\n{_CLOSING}\n'
        schema = segs_schema(schema)
    elif fmt != 'full':
        raise ValueError(f'unknown format {fmt!r}')
    digest = hashlib.sha256(
        (instructions + json.dumps(schema, sort_keys=True, separators=(',', ':'))).encode('utf-8')).hexdigest()
    return {'kind': kind, 'version': f'{kind}-v1-{digest[:12]}', 'instructions': instructions, 'schema': schema}


def segs_schema(schema: dict) -> dict:
    """The link schema with a figure's `caption` and `entries` replaced by one `segs` string."""
    out = json.loads(json.dumps(schema))
    figure = out['properties']['figures']['items']
    for name in ('caption', 'entries'):
        figure['properties'].pop(name)
        figure['required'].remove(name)
    figure['properties']['segs'] = {'type': 'string', 'description': 'caption pieces, one per line: <kind> :: <text>'}
    figure['required'].append('segs')
    return out


def version(kind: str, fmt: str | None = None) -> str:
    return load(kind, fmt)['version']


def accepted(kind: str, current: str) -> frozenset[str]:
    """The versions whose results count as done: the current one and the listed earlier ones."""
    return ACCEPTED_VERSIONS.get(kind, frozenset()) | {current}
