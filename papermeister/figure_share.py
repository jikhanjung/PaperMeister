"""Figure results travel with the OCR JSON — into the cache file's `figures`
key and, when the user opted in, back to the paper's Zotero sibling
attachment. The same road `papermeister_meta` takes for the bibliography.

Why: the figure stages need a wrapper server the user's institution runs.
A second machine, or a user outside that network, cannot run them — but it
can read what was found. Boxes, captions, entries and panel coordinates are
a few tens of kilobytes per paper (no images), so they ride in the JSON.

What rides: every row of the file (folded and placeholder rows included —
a person's dismissal is a decision), its stage results, and a person's
claims (`user_confirmed`, the locks). Rows refer to each other by identity
(page, box, assembly), never by id: ids differ per library.

What guards the import: the export names the OCR text it was made against
(`ocr_digest`). If the JSON's pages were re-OCR'd since, the boxes no
longer point at this text and the export is ignored — the rule re-assembles.
A row a person claimed locally is never overwritten by an import.
"""
from __future__ import annotations

import datetime
import json
import os

from . import figure_link, figure_store
from .figure_store import protection
from .models import Figure, FigureEntry, FigurePanel, PaperFile, db
from .paths import OCR_JSON_DIR

SCHEMA_VERSION = 1

_ROW_FIELDS = (
    'page', 'bbox_page_1000', 'blocks_json', 'assembly', 'plate', 'plate_inferred', 'page_kind', 'name', 'kind',
    'caption_hint', 'label_hints_json', 'uncertain_reasons_json', 'bbox_source',
    'detect_key', 'detect_attempts', 'detect_caption_json',
    'caption', 'caption_source', 'caption_page', 'caption_pages_json',
    'link_key', 'link_result_digest', 'link_model', 'link_prompt_version', 'link_attempts',
    'panel_key', 'panel_entries_digest', 'panel_result_digest', 'panel_model', 'panel_prompt_version',
    'is_compound', 'panel_notes_json', 'panel_attempts',
    'user_confirmed', 'bbox_locked', 'caption_locked', 'panels_locked', 'dismissed', 'dismissed_by',
)
_TIMES = ('assembled_at', 'detected_at', 'linked_at', 'paneled_at')
_ENTRY_FIELDS = ('order', 'label', 'printed_label', 'label_status', 'specimen_number', 'description')
_PANEL_FIELDS = ('order', 'label', 'bbox_figure_1000', 'entry_orders_json', 'confidence', 'annotation')


def _identity(row: Figure) -> list:
    return [row.page, json.loads(row.bbox_page_1000), row.assembly]


def _iso(value) -> str | None:
    return value.isoformat(timespec='seconds') if value else None


def export_figures(paper_file: PaperFile, pages: list[str]) -> dict:
    """The file's figure rows as a JSON-ready dict, keyed to the OCR text."""
    rows = list(Figure.select().where(Figure.paper_file == paper_file.id).order_by(Figure.page, Figure.id))
    by_id = {r.id: r for r in rows}
    out = []
    for r in rows:
        item = {name: getattr(r, name) for name in _ROW_FIELDS}
        item.update({name: _iso(getattr(r, name)) for name in _TIMES})
        item['continuation_of'] = _identity(by_id[r.continuation_of_id]) if r.continuation_of_id in by_id else None
        item['entries'] = [{k: getattr(e, k) for k in _ENTRY_FIELDS}
                           for e in r.entries.order_by(FigureEntry.order)]
        item['panels'] = [{k: getattr(p, k) for k in _PANEL_FIELDS}
                          for p in r.panels.order_by(FigurePanel.order)]
        out.append(item)
    return {
        'schema_version': SCHEMA_VERSION,
        'exported_at': datetime.datetime.now(datetime.UTC).isoformat(timespec='seconds'),
        'file_hash': paper_file.hash,
        'ocr_digest': figure_link.ocr_digest(pages),
        'rows': out,
    }


def cache_path(paper_file: PaperFile) -> str:
    from .text_extract import ocr_json_filename
    return os.path.join(OCR_JSON_DIR, ocr_json_filename(paper_file))


def write_to_cache(paper_file: PaperFile, push: bool = True) -> str | None:
    """Put the file's figures into its cache JSON and, if opted in, the
    Zotero sibling. Returns the sibling outcome, or None when not pushed."""
    from .text_extract import ocr_json_filename, push_sibling_json, write_ocr_json
    path = cache_path(paper_file)
    if not os.path.isfile(path):
        return None
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    pages = [(p.get('markdown') or '') for p in sorted(data.get('pages') or [], key=lambda p: p.get('page', 0))]
    data['figures'] = export_figures(paper_file, pages)
    write_ocr_json(path, data)
    if not push:
        return None
    return push_sibling_json(paper_file.paper, ocr_json_filename(paper_file), path)


class ImportReport:
    def __init__(self):
        self.created = self.updated = self.unchanged = self.protected = 0
        self.skipped_reason = ''

    def __str__(self):
        if self.skipped_reason:
            return f'skipped: {self.skipped_reason}'
        return (f'created {self.created}, updated {self.updated}, unchanged {self.unchanged}, '
                f'left alone (person\'s) {self.protected}')


def _newer(theirs: str | None, mine) -> bool:
    return bool(theirs) and (mine is None or theirs > _iso(mine))


def import_figures(paper_file: PaperFile, data: dict, pages: list[str]) -> ImportReport:
    """Land an exported `figures` block on this library's rows.

    A row is matched by identity. Missing rows are created whole. An existing
    row takes the export's stage results where the export is newer (by the
    stage's timestamp) and the local row is not a person's. A person's claims
    in the export land on rows nobody here has claimed.
    """
    report = ImportReport()
    block = (data or {}).get('figures') or {}
    if block.get('schema_version') != SCHEMA_VERSION or not block.get('rows'):
        report.skipped_reason = 'no figures in the JSON'
        return report
    if block.get('file_hash') != paper_file.hash:
        report.skipped_reason = 'the export is for another PDF'
        return report
    if block.get('ocr_digest') != figure_link.ocr_digest(pages):
        report.skipped_reason = 'the export was made against other OCR text (re-OCR since)'
        return report

    local = {json.dumps(_identity(r)): r for r in Figure.select().where(Figure.paper_file == paper_file.id)}
    now = datetime.datetime.now()
    pending_continuations: list[tuple[Figure, list]] = []
    with db.atomic():
        for item in block['rows']:
            key = json.dumps([item['page'], json.loads(item['bbox_page_1000']), item['assembly']])
            row = local.get(key)
            if row is None:
                row = Figure(paper=paper_file.paper_id, paper_file=paper_file.id, file_hash=paper_file.hash,
                             assembled_at=now)
                _assign(row, item, all_fields=True)
                row.save()
                _replace_children(row, item)
                local[key] = row
                report.created += 1
            elif protection(row).any:
                report.protected += 1
            else:
                changed = _assign(row, item, all_fields=False)
                if changed:
                    row.save()
                    _replace_children(row, item)
                    report.updated += 1
                else:
                    report.unchanged += 1
            if item.get('continuation_of'):
                pending_continuations.append((row, item['continuation_of']))
        for row, ident in pending_continuations:
            first = local.get(json.dumps(ident))
            if first is not None and row.continuation_of_id != first.id:
                row.continuation_of = first.id
                row.save()
    return report


def _assign(row: Figure, item: dict, all_fields: bool) -> bool:
    """Copy the export onto a row. For an existing row, only stage results
    that are newer and a person's claims. Returns whether anything changed."""
    changed = False
    if all_fields:
        for name in _ROW_FIELDS:
            setattr(row, name, item.get(name, getattr(row, name)))
        for name in _TIMES:
            if item.get(name):
                setattr(row, name, datetime.datetime.fromisoformat(item[name]))
        return True
    stages = (
        ('detected_at', ('detect_key', 'detect_attempts', 'detect_caption_json', 'bbox_page_1000', 'bbox_source',
                         'name', 'plate', 'plate_inferred', 'page_kind', 'uncertain_reasons_json')),
        ('linked_at', ('caption', 'caption_source', 'caption_page', 'caption_pages_json', 'name',
                       'link_key', 'link_result_digest', 'link_model', 'link_prompt_version', 'link_attempts',
                       'uncertain_reasons_json')),
        ('paneled_at', ('panel_key', 'panel_entries_digest', 'panel_result_digest', 'panel_model',
                        'panel_prompt_version', 'is_compound', 'kind', 'panel_notes_json', 'panel_attempts',
                        'uncertain_reasons_json')),
    )
    for stamp, names in stages:
        if _newer(item.get(stamp), getattr(row, stamp)):
            for name in names:
                setattr(row, name, item.get(name, getattr(row, name)))
            setattr(row, stamp, datetime.datetime.fromisoformat(item[stamp]))
            changed = True
    for name in ('user_confirmed', 'bbox_locked', 'caption_locked', 'panels_locked'):
        if item.get(name) and not getattr(row, name):
            setattr(row, name, True)
            changed = True
    if item.get('dismissed') and not row.dismissed and item.get('dismissed_by') in (figure_store.USER, 'detect'):
        row.dismissed, row.dismissed_by = True, item['dismissed_by']
        changed = True
    return changed


def _replace_children(row: Figure, item: dict) -> None:
    FigureEntry.delete().where(FigureEntry.figure == row.id).execute()
    for e in item.get('entries') or []:
        FigureEntry.create(figure=row.id, **{k: e.get(k, '') for k in _ENTRY_FIELDS})
    FigurePanel.delete().where(FigurePanel.figure == row.id).execute()
    for p in item.get('panels') or []:
        FigurePanel.create(figure=row.id, **{k: p.get(k, '' if k != 'annotation' else False) for k in _PANEL_FIELDS})


def import_from_cache(paper_file: PaperFile) -> ImportReport:
    """Land the cache JSON's `figures` block, if it has one."""
    path = cache_path(paper_file)
    report = ImportReport()
    if not os.path.isfile(path):
        report.skipped_reason = 'no cache JSON'
        return report
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    pages = [(p.get('markdown') or '') for p in sorted(data.get('pages') or [], key=lambda p: p.get('page', 0))]
    return import_figures(paper_file, data, pages)
