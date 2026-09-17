"""The re-judgement stage (P16 ①′) as the client sees it: which pages to send,
what the reply means, what to write.

The rule (`figures.suspect`) marks where it does not trust its own assembly;
a model shown the paper says what the figures on that page really are. One
item per page: the parser's boxes as hints, the reply as boxes with `from`
(which parser figures each replaces) and `dismiss`. The verdict is derived
here, not asked for — kept, adjusted, merged, split, new, dismissed — so the
model only ever describes the page and never has to name our categories.

What it writes is protected the same way as everything else
(`figure_store.protection`): a row a person claimed is never moved, merged or
folded by this stage; a reply that would is recorded as a conflict for the
person to see. Rows this stage makes are locked (`bbox_locked`,
`bbox_source='detect'`) and carry their sources' OCR blocks, so re-assembly
neither folds them nor raises the pieces again.
"""
from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, field

from . import figures
from .figure_review import DETECT_TRIGGERS
from .figure_store import PAGE, protection
from .models import Figure, PaperFile, db

DETECT = 'detect'
MAX_ATTEMPTS = 3
KINDS = ('plate', 'captioned_plate', 'body', 'table', 'text', 'other')
NOT_FIGURES = ('table', 'text')
DETECT_CONFLICTS_USER = 'detect_conflicts_user'
_PAGE_KIND = {'plate': figures.PLATE_KIND, 'captioned_plate': figures.CAPTIONED_PLATE}


def detect_key(paper_file: PaperFile, page: int, digest: str, prompt_version: str) -> str:
    return f'{paper_file.hash[:12]}|{page}|{digest[:12]}|{prompt_version}'


def triggers(row: Figure) -> list[str]:
    return [r for r in json.loads(row.uncertain_reasons_json or '[]') if r in DETECT_TRIGGERS]


# ── which pages ──────────────────────────────────────────────────────

@dataclass
class DetectTargets:
    items: list[dict] = field(default_factory=list)
    rows_by_item: dict[str, list[Figure]] = field(default_factory=dict)
    excluded: list[tuple[Figure, str]] = field(default_factory=list)


def detect_items(paper_file: PaperFile, pages: list[str], digest: str, prompt_version: str,
                 retry_errors: bool = False) -> DetectTargets:
    """One item per doubted page. Placeholders (page-level doubts) ride along
    without a hint box; the worker draws boxes, the model reads the rest."""
    out = DetectTargets()
    by_page: dict[int, list[Figure]] = {}
    for row in Figure.select().where(Figure.paper_file == paper_file.id).order_by(Figure.page, Figure.id):
        if row.dismissed:
            out.excluded.append((row, 'dismissed'))
        elif not triggers(row):
            out.excluded.append((row, 'no_trigger'))
        elif protection(row).assembly:
            out.excluded.append((row, 'locked'))
        elif row.detect_key == detect_key(paper_file, row.page, digest, prompt_version):
            out.excluded.append((row, 'detected'))
        elif row.detect_attempts >= MAX_ATTEMPTS and not retry_errors:
            out.excluded.append((row, 'attempts_exhausted'))
        else:
            by_page.setdefault(row.page, []).append(row)
    facts = {i: figures.read_page(i, t or '') for i, t in enumerate(pages)}
    plate_pages = [p for p, f in facts.items() if f.printed]
    explanation_pages = [p for p, f in facts.items() if f.explained]
    for page, rows in sorted(by_page.items()):
        key = detect_key(paper_file, page, digest, prompt_version)
        boxed = [r for r in rows if r.assembly != PAGE]
        item = {
            'key': key,
            'page': page,
            'hint_boxes': [json.loads(r.bbox_page_1000) for r in boxed],
            'figure_keys': [str(r.id) for r in boxed],
            'reasons': sorted({t for r in rows for t in triggers(r)}),
            'figures': [{
                'figure_id': str(r.id), 'bbox_page_1000': json.loads(r.bbox_page_1000),
                'assembly': r.assembly, 'page_kind': r.page_kind, 'name_hint': r.name,
                'caption_hint': r.caption_hint, 'reasons': triggers(r),
                'placeholder': r.assembly == PAGE,
            } for r in rows],
            'hints': {'plate_pages': plate_pages, 'explanation_pages': explanation_pages,
                      'pages_nearby': [p for p in (page - 1, page + 1) if 0 <= p < len(pages)]},
        }
        out.items.append(item)
        out.rows_by_item[key] = rows
    return out


def detect_payload(paper_file: PaperFile, digest: str, targets: DetectTargets, client_id: str,
                   prompt: dict) -> dict:
    return {'client_id': client_id, 'file_hash': paper_file.hash, 'ocr_digest': digest,
            'items': targets.items, 'prompt': prompt,
            'options': {'model': 'gpt-6-astra', 'effort': 'high'}}


# ── what the reply means ─────────────────────────────────────────────

def _box(value) -> list[int] | None:
    if not isinstance(value, list) or len(value) != 4:
        return None
    try:
        b = [int(round(float(v))) for v in value]
    except (TypeError, ValueError):
        return None
    if any(not 0 <= v <= 1000 for v in b) or b[0] >= b[2] or b[1] >= b[3]:
        return None
    return b


@dataclass
class DetectApplied:
    kept: int = 0
    adjusted: int = 0
    merged: int = 0          # rows folded into a merge
    split: int = 0           # rows folded into several
    new: int = 0             # rows created
    dismissed: int = 0
    conflicts: int = 0       # replies that touched a person's row — recorded, not applied
    invalid: int = 0         # reply figures with a bad box or kind
    failed: int = 0          # items with no usable reply: attempts counted


def apply_detect(paper_file: PaperFile, item: dict, rows: list[Figure], result: dict | None,
                 digest: str, prompt_version: str, model: str) -> DetectApplied:
    """Write one page's reply. `result is None` counts an attempt on its rows."""
    out = DetectApplied()
    now = datetime.datetime.now()
    key = item['key']
    by_id = {str(r.id): r for r in rows}

    with db.atomic():
        if not isinstance(result, dict) or not isinstance(result.get('figures'), list):
            for r in rows:
                r.detect_attempts += 1
                r.save()
            out.failed += 1
            return out

        dismiss = {str(i) for i in (result.get('dismiss') or []) if str(i) in by_id}
        replies = []
        for f in result['figures']:
            box = _box(f.get('bbox_page_1000'))
            if box is None or f.get('kind') not in KINDS:
                out.invalid += 1
                continue
            from_ids = [str(i) for i in (f.get('from') or []) if str(i) in by_id and by_id[str(i)].assembly != PAGE]
            if f['kind'] in NOT_FIGURES:
                dismiss |= set(from_ids)
                continue
            replies.append((f, box, from_ids))
        occurrences: dict[str, int] = {}
        for _, _, from_ids in replies:
            for i in from_ids:
                occurrences[i] = occurrences.get(i, 0) + 1

        touched: set[str] = set()
        made_new = False
        for f, box, from_ids in replies:
            claimed = [i for i in from_ids if protection(by_id[i]).assembly]
            if claimed:
                for i in claimed:
                    _add_reason(by_id[i], DETECT_CONFLICTS_USER)
                    by_id[i].save()
                out.conflicts += 1
                touched |= set(from_ids)
                continue
            if len(from_ids) == 1 and occurrences[from_ids[0]] == 1:
                row = by_id[from_ids[0]]
                moved = json.loads(row.bbox_page_1000) != box
                if moved:
                    row.bbox_page_1000 = json.dumps(box)
                    row.bbox_source = DETECT
                    row.bbox_locked = True
                    out.adjusted += 1
                else:
                    out.kept += 1
                _describe(row, f)
                _settle(row, key, now, prompt_version, model)
                row.save()
            else:
                sources = [by_id[i] for i in from_ids]
                blocks = [b for r in sources for b in json.loads(r.blocks_json or '[]')]
                new = Figure(paper=paper_file.paper_id, paper_file=paper_file.id, file_hash=paper_file.hash,
                             page=item['page'], bbox_page_1000=json.dumps(box), blocks_json=json.dumps(blocks),
                             assembly=DETECT, bbox_source=DETECT, bbox_locked=True, assembled_at=now)
                _describe(new, f)
                _settle(new, key, now, prompt_version, model)
                new.save()
                made_new = True
                out.new += 1
                for r in sources:
                    if not r.dismissed:
                        r.dismissed, r.dismissed_by = True, DETECT
                        if occurrences[str(r.id)] > 1:
                            out.split += 1
                        else:
                            out.merged += 1
                    _settle(r, key, now, prompt_version, model)
                    r.save()
            touched |= set(from_ids)

        for i in dismiss - touched:
            row = by_id[i]
            if protection(row).assembly:
                _add_reason(row, DETECT_CONFLICTS_USER)
                out.conflicts += 1
            elif not row.dismissed:
                row.dismissed, row.dismissed_by = True, DETECT
                out.dismissed += 1
            _settle(row, key, now, prompt_version, model)
            row.save()
            touched.add(i)

        # Rows the reply did not mention are kept as they were; placeholders
        # fold once the page has real figures.
        for i, row in by_id.items():
            if i in touched:
                continue
            if row.assembly == PAGE and (made_new or replies):
                row.dismissed, row.dismissed_by = True, DETECT
            _settle(row, key, now, prompt_version, model)
            row.save()
            if row.assembly != PAGE and not row.dismissed:
                out.kept += 1
    return out


def _describe(row: Figure, f: dict) -> None:
    """What the reply says about a figure — name, kind, caption hint."""
    name = (f.get('name') or '').strip()
    if name and row.linked_at is None:
        row.name = name
        hits = figures._plate_hits([figures.Region('Page-Header', (0, 0, 1000, 20), name)], figures.MARK_LABELS)
        row.plate = hits[0][0] if hits else row.plate
        row.plate_inferred = bool(f.get('name_inferred'))
    row.page_kind = _PAGE_KIND.get(f.get('kind'), figures.BODY)
    if f.get('caption'):
        row.detect_caption_json = json.dumps({'caption': f['caption'], 'caption_pages': f.get('caption_pages') or [],
                                              'caption_kind': f.get('caption_kind') or ''}, ensure_ascii=False)


def _settle(row: Figure, key: str, now, prompt_version: str, model: str) -> None:
    row.detect_key = key
    row.detected_at = now
    row.detect_attempts = 0
    have = json.loads(row.uncertain_reasons_json or '[]')
    row.uncertain_reasons_json = json.dumps([r for r in have if r not in DETECT_TRIGGERS])


def _add_reason(row: Figure, reason: str) -> None:
    have = json.loads(row.uncertain_reasons_json or '[]')
    if reason not in have:
        row.uncertain_reasons_json = json.dumps([*have, reason])



