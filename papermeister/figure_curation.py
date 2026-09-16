"""Recording a person's decision about a figure — and being able to replay it.

The review sheets (`figure_sheet`) let a person see what assembly did; this
is how they say it is wrong. Every operation sets `user_confirmed` on the rows
it touches, because that flag is the one thing every automatic path checks
before overwriting (`figure_store` leaves such rows alone; the caption and
panel stages will too). Dismissing sets `dismissed_by='user'`, which
re-assembly never revives — fsis had a rule resurrect a page a person had
folded, and the unique-key clash it caused stopped a nightly chain.

Every applied operation is appended to a JSON record with the rows' identities
(PDF hash, page, box, assembly — the same key `figure_store` matches on) and
their values before the change. Re-OCR or a rule change re-creates rows from
the cache, and the record is how the same decisions land on the new rows
(`replay`). fsis kept its fixes as `scripts/curation/<date>.json` plus an
applier for the same reason: a fix that lives only in the database is lost
the first time the database is rebuilt.

Nothing is deleted. Merging folds the other rows; the survivor keeps the union
of their boxes and blocks, so re-assembly can tell its pieces are spoken for.
"""
from __future__ import annotations

import datetime
import json
import os
from dataclasses import dataclass, field

from .models import Figure, db

USER = 'user'
OPERATIONS = ('confirm', 'dismiss', 'restore', 'rename', 'set-bbox', 'merge')

#: What a record keeps of a row, enough to find it again and to undo by hand.
_SNAPSHOT = ('name', 'bbox_page_1000', 'blocks_json', 'assembly', 'user_confirmed',
             'dismissed', 'dismissed_by')


class CurationError(ValueError):
    pass


def row_key(row: Figure) -> dict:
    return {'file_hash': row.file_hash, 'page': row.page,
            'bbox': json.loads(row.bbox_page_1000), 'assembly': row.assembly}


def parse_key(text: str) -> tuple[int, int, list[int]]:
    """`file_id:page:x0,y0,x1,y1` as the review sheet prints it."""
    try:
        file_id, page, box = text.split(':')
        bbox = [int(v) for v in box.split(',')]
        if len(bbox) != 4:
            raise ValueError
        return int(file_id), int(page), bbox
    except ValueError:
        raise CurationError(f'not a figure key: {text!r} (want file:page:x0,y0,x1,y1)') from None


def find_rows(ids: list[int] = (), keys: list[str] = ()) -> list[Figure]:
    rows: list[Figure] = []
    for id_ in ids:
        row = Figure.get_or_none(Figure.id == id_)
        if row is None:
            raise CurationError(f'no figure #{id_}')
        rows.append(row)
    for text in keys:
        file_id, page, bbox = parse_key(text)
        found = list(Figure.select().where(
            (Figure.paper_file == file_id) & (Figure.page == page)
            & (Figure.bbox_page_1000 == json.dumps(bbox))))
        if not found:
            raise CurationError(f'no figure at {text}')
        if len(found) > 1:
            raise CurationError(f'{len(found)} figures at {text}: use --figure-ids '
                                + ','.join(str(r.id) for r in found))
        rows.extend(found)
    return rows


@dataclass
class Change:
    row: Figure
    after: dict


@dataclass
class CurationPlan:
    op: str
    reason: str
    args: dict
    changes: list[Change] = field(default_factory=list)

    def describe(self) -> list[str]:
        lines = []
        for change in self.changes:
            diffs = ', '.join(f'{k}: {getattr(change.row, k)!r} → {v!r}'
                              for k, v in change.after.items() if getattr(change.row, k) != v)
            lines.append(f'  #{change.row.id}  p.{change.row.page}  {change.row.name or "(no name)"}: '
                         f'{diffs or "no change"}')
        return lines


def _union(boxes):
    return [min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes)]


def plan(op: str, rows: list[Figure], reason: str, name: str = '', bbox: list[int] | None = None) -> CurationPlan:
    """What the operation would change. Raises CurationError when it cannot apply."""
    if op not in OPERATIONS:
        raise CurationError(f'unknown operation {op!r}')
    if not rows:
        raise CurationError('no figures given')
    if not reason.strip():
        raise CurationError('--reason is required: the record must say why')
    out = CurationPlan(op=op, reason=reason, args={})

    if op == 'confirm':
        for row in rows:
            out.changes.append(Change(row, {'user_confirmed': True}))
    elif op == 'dismiss':
        for row in rows:
            out.changes.append(Change(row, {'dismissed': True, 'dismissed_by': USER, 'user_confirmed': True}))
    elif op == 'restore':
        for row in rows:
            out.changes.append(Change(row, {'dismissed': False, 'dismissed_by': '', 'user_confirmed': True}))
    elif op == 'rename':
        if len(rows) != 1:
            raise CurationError('rename takes exactly one figure')
        out.args['name'] = name
        out.changes.append(Change(rows[0], {'name': name, 'user_confirmed': True}))
    elif op == 'set-bbox':
        if len(rows) != 1:
            raise CurationError('set-bbox takes exactly one figure')
        if not bbox or len(bbox) != 4 or not all(0 <= v <= 1000 for v in bbox) \
                or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
            raise CurationError('--bbox must be x0,y0,x1,y1 in 0..1000 with x0<x1, y0<y1')
        out.args['bbox'] = bbox
        out.changes.append(Change(rows[0], {'bbox_page_1000': json.dumps(bbox), 'user_confirmed': True}))
    elif op == 'merge':
        if len(rows) < 2:
            raise CurationError('merge takes two or more figures')
        if len({(r.paper_file_id, r.page) for r in rows}) != 1:
            raise CurationError('merge: the figures must be on one page of one file')
        survivor, *others = rows
        boxes = [json.loads(r.bbox_page_1000) for r in rows]
        blocks = [b for r in rows for b in json.loads(r.blocks_json)]
        out.changes.append(Change(survivor, {
            'bbox_page_1000': json.dumps(_union(boxes)),
            'blocks_json': json.dumps(blocks), 'user_confirmed': True}))
        for row in others:
            out.changes.append(Change(row, {'dismissed': True, 'dismissed_by': USER, 'user_confirmed': True}))
    return out


def _snapshot(row: Figure) -> dict:
    return {name: getattr(row, name) for name in _SNAPSHOT}


def apply(plan_: CurationPlan, record_path: str) -> dict:
    """Write the plan in one transaction and append it to the record. Returns the entry."""
    entry = {
        'at': datetime.datetime.now().isoformat(timespec='seconds'),
        'op': plan_.op, 'reason': plan_.reason, 'args': plan_.args,
        'targets': [{'id': c.row.id, 'key': row_key(c.row), 'before': _snapshot(c.row)}
                    for c in plan_.changes],
    }
    with db.atomic():
        for change in plan_.changes:
            for name, value in change.after.items():
                setattr(change.row, name, value)
            change.row.save()
    os.makedirs(os.path.dirname(record_path) or '.', exist_ok=True)
    entries = load_record(record_path)
    entries.append(entry)
    with open(record_path, 'w', encoding='utf-8') as f:
        json.dump(entries, f, ensure_ascii=False, indent=1)
    return entry


def load_record(path: str) -> list[dict]:
    if not os.path.isfile(path):
        return []
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _row_for_key(key: dict) -> Figure | None:
    return Figure.get_or_none(
        (Figure.file_hash == key['file_hash']) & (Figure.page == key['page'])
        & (Figure.bbox_page_1000 == json.dumps(key['bbox'])) & (Figure.assembly == key['assembly']))


def replay(entries: list[dict], record_path: str | None, execute: bool) -> list[str]:
    """Land recorded decisions on the rows that now carry the same identities.

    Rows are found by key, not id: after re-assembly the ids are new and the
    keys are not. An entry whose rows are not all found is reported and skipped —
    half a merge is worse than none. Returns one line per entry.
    """
    lines = []
    for entry in entries:
        rows = [_row_for_key(t['key']) for t in entry['targets']]
        missing = [t['key'] for t, r in zip(entry['targets'], rows, strict=True) if r is None]
        label = f"{entry['at']} {entry['op']} ({len(entry['targets'])} figure(s))"
        if missing:
            lines.append(f'  skip  {label}: {len(missing)} row(s) not found, e.g. page {missing[0]["page"]} '
                         f'box {missing[0]["bbox"]}')
            continue
        args = entry.get('args', {})
        try:
            plan_ = plan(entry['op'], rows, entry['reason'], name=args.get('name', ''), bbox=args.get('bbox'))
        except CurationError as exc:
            lines.append(f'  skip  {label}: {exc}')
            continue
        changed = sum(1 for c in plan_.changes
                      if any(getattr(c.row, k) != v for k, v in c.after.items()))
        if execute and changed and record_path:
            apply(plan_, record_path)
        lines.append(f'  {"apply" if execute else "would"} {label}: {changed} row(s) change')
    return lines
