"""The panel stage (P16 ③) as the client sees it: which figures to cut, what
to send, what to believe, what to write — and how to keep panels when only
the caption changed.

The model (Astra, run by ocrserver) gets the figure's image, cropped by the
server from the PDF, plus the caption and its entries, and returns panel
boxes in the image's own 0..1000 frame with the entries each panel shows.
This module does not call anything.

Two decisions from the pilot review and fsis shape it:

- **`panel_key` is the image's identity only** — file, page, box, render
  settings, prompt. The entries are *not* in it (D6). fsis put a derived
  value in its key and re-cut 472 plates in five hours when captions moved;
  a caption fix should re-match panels to entries by label, and re-cut only
  when the labels no longer say which is which (`rematch`).
- **Every exclusion is named.** fsis's lane skipped maps silently and a
  person spent a morning on "no error, nothing done" (EC §6-9). Maps are
  skipped only on a re-cut — `kind` comes from this stage, so before the
  first cut nothing is a map.
"""
from __future__ import annotations

import datetime
import hashlib
import json
from dataclasses import dataclass, field

from .figure_store import PAGE, protection
from .models import Figure, FigureEntry, FigurePanel, PaperFile, db

MAX_ATTEMPTS = 3
RENDER_DPI = 216                     # fsis's setting; part of the key because it is part of the image
FIGURE_KINDS = ('fossil_plate', 'map', 'chart', 'diagram', 'photo', 'mixed', 'other')
NON_COMPOUND_REASONS = ('', 'legend_labels', 'image_incomplete', 'single_image_many_captions', 'not_a_figure')
CONFIDENCES = ('high', 'medium', 'low')
#: Panels per entry outside this band is a question for a person, not a rejection (fsis: exact match 115/396).
PANEL_RATIO_MIN, PANEL_RATIO_MAX = 0.5, 2.0

# Review reasons this stage raises.
PANELS_0 = 'panels_0'
PANELS_1_WITH_SIBLINGS = 'panels_1_with_siblings'
PANEL_COUNT_OUT_OF_RANGE = 'panel_count_out_of_range'
#: One entry on several panels — a photograph and its outline drawing, a
#: stereo pair, dorsal and lateral views under one number. Naimark 2006
#: Fig. 2 is exactly that and was rejected as a duplicate; it is a review
#: reason, not a fault in the reply.
ENTRY_ON_SEVERAL_PANELS = 'entry_on_several_panels'
SINGLE_IMAGE_MANY_CAPTIONS = 'single_image_many_captions'
IMAGE_INCOMPLETE = 'image_incomplete'
NOT_A_FIGURE = 'not_a_figure'
ENTRIES_CHANGED_UNMAPPED = 'entries_changed_unmapped'
_PANEL_REASONS = frozenset({PANELS_0, PANELS_1_WITH_SIBLINGS, PANEL_COUNT_OUT_OF_RANGE,
                            SINGLE_IMAGE_MANY_CAPTIONS, IMAGE_INCOMPLETE, NOT_A_FIGURE, ENTRIES_CHANGED_UNMAPPED})


def panel_key(row: Figure, prompt_version: str, dpi: int = RENDER_DPI) -> str:
    return f'{row.file_hash}|{row.page}|{row.bbox_page_1000}|{dpi}|{prompt_version}'


def entries_of(row: Figure) -> list[FigureEntry]:
    return list(row.entries.order_by(FigureEntry.order))


def entries_digest(entries: list[FigureEntry]) -> str:
    body = json.dumps([[e.label, e.description] for e in entries], ensure_ascii=False)
    return hashlib.sha256(body.encode('utf-8')).hexdigest()


# ── which figures ────────────────────────────────────────────────────

@dataclass
class SplitTargets:
    due: list[Figure] = field(default_factory=list)
    rematch: list[Figure] = field(default_factory=list)   # panels exist; only the entries changed
    excluded: list[tuple[Figure, str]] = field(default_factory=list)


def split_targets(paper_file: PaperFile, prompt_version: str, retry_errors: bool = False,
                  include_maps: bool = False) -> SplitTargets:
    out = SplitTargets()
    rows = Figure.select().where(Figure.paper_file == paper_file.id).order_by(Figure.page, Figure.id)
    for row in rows:
        entries = entries_of(row)
        key = panel_key(row, prompt_version)
        if row.dismissed:
            out.excluded.append((row, 'dismissed'))
        elif row.assembly == PAGE:
            out.excluded.append((row, 'page_placeholder'))
        elif not row.caption:
            out.excluded.append((row, 'no_caption'))
        elif len(entries) < 2:
            out.excluded.append((row, 'entries_lt_2'))
        elif protection(row).panels:
            out.excluded.append((row, 'panels_locked'))
        elif row.panel_key == key:
            if row.panel_entries_digest != entries_digest(entries):
                out.rematch.append(row)
            else:
                out.excluded.append((row, 'split'))
        elif row.kind == 'map' and row.panel_key and not include_maps:
            out.excluded.append((row, 'map'))
        elif row.panel_attempts >= MAX_ATTEMPTS and not retry_errors:
            out.excluded.append((row, 'attempts_exhausted'))
        else:
            out.due.append(row)
    return out


# ── what to send ─────────────────────────────────────────────────────

def to_figure_frame(figure_box, block) -> list[int]:
    """A page-frame box (0..1000 of the page) as a figure-frame box (0..1000 of the crop)."""
    fx0, fy0, fx1, fy1 = figure_box
    w, h = max(1, fx1 - fx0), max(1, fy1 - fy0)
    x0, y0, x1, y1 = block
    scale = lambda v, lo, size: max(0, min(1000, round((v - lo) * 1000 / size)))  # noqa: E731
    return [scale(x0, fx0, w), scale(y0, fy0, h), scale(x1, fx0, w), scale(y1, fy0, h)]


def to_page_frame(figure_box, panel_box) -> list[int]:
    """The inverse: a panel's figure-frame box as a page-frame box, for cropping the PDF."""
    fx0, fy0, fx1, fy1 = figure_box
    w, h = fx1 - fx0, fy1 - fy0
    x0, y0, x1, y1 = panel_box
    return [round(fx0 + x0 * w / 1000), round(fy0 + y0 * h / 1000),
            round(fx0 + x1 * w / 1000), round(fy0 + y1 * h / 1000)]


def panel_item(row: Figure, prompt_version: str, dpi: int = RENDER_DPI) -> dict:
    """One figure as the panel request carries it."""
    box = json.loads(row.bbox_page_1000)
    entries = entries_of(row)
    return {
        'key': f'{row.id}@{panel_key(row, prompt_version, dpi)}',   # comes back on the result unchanged
        'page': row.page,                                    # 0-based
        'bbox_page_1000': box,
        'caption': row.caption,
        'entries': [{'label': e.label, 'description': e.description} for e in entries],
        # For a figure the OCR cut into pieces: where the pieces were, in the
        # crop's frame. Hints for the model, not the answer — a piece can hold
        # two specimens, and a label can sit outside its piece.
        'piece_boxes_figure_1000': ([to_figure_frame(box, b) for b in json.loads(row.blocks_json or '[]')]
                                    if row.assembly == 'caption_group_union' else []),
        'label_hints': json.loads(row.label_hints_json or '[]'),
        'dpi': dpi,
    }


# ── what to believe ──────────────────────────────────────────────────

@dataclass
class PanelCheck:
    ok: bool
    why: str = ''                          # rejection, when not ok
    review: list[str] = field(default_factory=list)
    panels: list[dict] = field(default_factory=list)   # normalised: bbox as a 4-list, labels filled in


def _box(value) -> list[float] | None:
    if isinstance(value, dict):
        try:
            value = [value[k] for k in ('x0', 'y0', 'x1', 'y1')]
        except KeyError:
            return None
    if not isinstance(value, list) or len(value) != 4:
        return None
    if any(not isinstance(v, int | float) or v != v or not 0 <= v <= 1000 for v in value):
        return None
    x0, y0, x1, y1 = value
    return None if x0 >= x1 or y0 >= y1 else [float(v) for v in value]


def validate_panel_result(item: dict, result: dict, siblings_on_page: int = 0) -> PanelCheck:
    """Check one figure's reply against its request. Port of fsis's
    `validate_prediction`, plus what the pilot review asked for: reasons a
    person can act on, and the trailing-panel label fill-in (EC §6-1)."""
    if not isinstance(result, dict) or not isinstance(result.get('panels'), list):
        return PanelCheck(False, 'missing_panels')
    if type(result.get('is_compound')) is not bool:
        return PanelCheck(False, 'invalid_is_compound')
    if result.get('figure_kind') not in FIGURE_KINDS:
        return PanelCheck(False, 'invalid_figure_kind')
    reason = result.get('non_compound_reason') or ''
    if reason not in NON_COMPOUND_REASONS:
        return PanelCheck(False, 'invalid_non_compound_reason')
    if not result['is_compound'] and len(result['panels']) > 1:
        return PanelCheck(False, 'single_figure_many_panels')
    entries = item.get('entries') or []
    n = len(entries)
    annotation = result.get('annotation_indices') or []
    if not isinstance(annotation, list) or any(type(i) is not int or not 0 <= i < n for i in annotation):
        return PanelCheck(False, 'invalid_annotation_indices')

    panels: list[dict] = []
    used: set[int] = set()
    shared = False
    for p in result['panels']:
        if not isinstance(p, dict) or not isinstance(p.get('label', ''), str):
            return PanelCheck(False, 'invalid_label')
        box = _box(p.get('bbox_figure_1000', p.get('bbox')))
        if box is None:
            return PanelCheck(False, 'invalid_box')
        indices = p.get('caption_indices') or []
        if not isinstance(indices, list) or any(type(i) is not int or not 0 <= i < n for i in indices):
            return PanelCheck(False, 'invalid_caption_index')
        if len(indices) != len(set(indices)):
            return PanelCheck(False, 'duplicate_caption_index')
        if used & set(indices):
            shared = True
        used |= set(indices)
        if p.get('confidence', 'low') not in CONFIDENCES:
            return PanelCheck(False, 'invalid_confidence')
        label = (p.get('label') or '').strip()
        if not label and indices:
            label = entries[indices[0]].get('label', '')
        panels.append({'label': label, 'bbox_figure_1000': box, 'caption_indices': list(indices),
                       'confidence': p.get('confidence', 'low')})

    # Trailing panels the model neither labelled nor matched: when exactly as
    # many entries are unused, they go together in reading order (fsis EC §6-1).
    orphans = [p for p in panels if not p['label'] and not p['caption_indices']]
    unused = [i for i in range(n) if i not in used and i not in annotation]
    if orphans and len(orphans) == len(unused):
        for p, i in zip(sorted(orphans, key=lambda p: (p['bbox_figure_1000'][1], p['bbox_figure_1000'][0])),
                        unused, strict=True):
            p['caption_indices'] = [i]
            p['label'] = entries[i].get('label', '')

    check = PanelCheck(True, panels=panels)
    if shared:
        check.review.append(ENTRY_ON_SEVERAL_PANELS)
    counted = n - len(annotation)
    if not panels:
        check.review.append(PANELS_0)
    elif len(panels) == 1 and siblings_on_page:
        check.review.append(PANELS_1_WITH_SIBLINGS)
    elif counted and not PANEL_RATIO_MIN * counted <= len(panels) <= PANEL_RATIO_MAX * counted:
        check.review.append(PANEL_COUNT_OUT_OF_RANGE)
    if reason in (SINGLE_IMAGE_MANY_CAPTIONS, IMAGE_INCOMPLETE, NOT_A_FIGURE):
        check.review.append(reason)
    return check


# ── what to write ────────────────────────────────────────────────────

def result_digest(result: dict) -> str:
    return hashlib.sha256(json.dumps(result, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


@dataclass
class PanelsApplied:
    written: int = 0
    unchanged: int = 0
    protected: int = 0
    failed: int = 0
    reviewed: int = 0


def apply_panels(row: Figure, item: dict, result: dict | None, check: PanelCheck | None,
                 prompt_version: str, model: str, dpi: int = RENDER_DPI) -> PanelsApplied:
    """Write one figure's panels. `result is None` or `check.ok is False`
    counts an attempt and leaves the old panels in place."""
    out = PanelsApplied()
    if protection(row).panels:
        out.protected += 1
        return out
    with db.atomic():
        if result is None or check is None or not check.ok:
            row.panel_attempts += 1
            row.save()
            out.failed += 1
            return out
        digest = result_digest(result)
        key = panel_key(row, prompt_version, dpi)
        if row.panel_result_digest == digest and row.panel_key == key:
            out.unchanged += 1
            return out
        entries = entries_of(row)
        FigurePanel.delete().where(FigurePanel.figure == row.id).execute()
        annotation = set(result.get('annotation_indices') or [])
        for order, p in enumerate(check.panels):
            FigurePanel.create(
                figure=row.id, order=order, label=p['label'],
                bbox_figure_1000=json.dumps(p['bbox_figure_1000']),
                entry_orders_json=json.dumps([entries[i].order for i in p['caption_indices']]),
                confidence=p['confidence'],
                annotation=bool(p['caption_indices']) and all(i in annotation for i in p['caption_indices']))
        row.panel_key = key
        row.panel_entries_digest = entries_digest(entries)
        row.panel_result_digest = digest
        row.panel_model = model
        row.panel_prompt_version = prompt_version
        row.is_compound = bool(result['is_compound'])
        row.kind = result['figure_kind']
        row.panel_notes_json = json.dumps(
            {'notes': result.get('notes') or [], 'non_compound_reason': result.get('non_compound_reason') or '',
             'annotation_indices': sorted(annotation), 'image_size': result.get('image_size')}, ensure_ascii=False)
        row.paneled_at = datetime.datetime.now()
        row.panel_attempts = 0
        _store_reasons(row, check.review)
        row.save()
        out.written += 1
        out.reviewed += bool(check.review)
    return out


def _store_reasons(row: Figure, reasons: list[str]) -> None:
    have = json.loads(row.uncertain_reasons_json or '[]')
    kept = [r for r in have if r not in _PANEL_REASONS]
    row.uncertain_reasons_json = json.dumps(kept + [r for r in reasons if r not in kept])


# ── when only the entries changed ────────────────────────────────────

def normalize_label(label: str) -> str:
    return (label or '').strip().lower().replace('(', '').replace(')', '').replace('.', '')


def rematch(row: Figure) -> tuple[bool, str]:
    """Re-attach existing panels to changed entries by label. Returns (done, note).

    The boxes are right; only the words changed. Every labelled panel must find
    exactly one entry with its label — a repeated number or an unlabelled panel
    is not matched by position (fsis DG §6-5). Otherwise the row is flagged and
    a person chooses between re-cutting and fixing the labels.
    """
    entries = entries_of(row)
    by_label: dict[str, list[FigureEntry]] = {}
    for e in entries:
        by_label.setdefault(normalize_label(e.label), []).append(e)
    panels = list(row.panels.order_by(FigurePanel.order))
    mapping: dict[int, list[int]] = {}
    for p in panels:
        if p.annotation:
            continue
        key = normalize_label(p.label)
        found = by_label.get(key, []) if key else []
        if len(found) != 1:
            _store_reasons(row, [ENTRIES_CHANGED_UNMAPPED])
            row.save()
            return False, f'panel {p.order} label {p.label!r} matches {len(found)} entries'
        mapping[p.id] = [found[0].order]
    with db.atomic():
        for p in panels:
            if p.id in mapping:
                p.entry_orders_json = json.dumps(mapping[p.id])
                p.save()
        row.panel_entries_digest = entries_digest(entries)
        _store_reasons(row, [])
        row.save()
    return True, f'{len(mapping)} panel(s) re-attached'
