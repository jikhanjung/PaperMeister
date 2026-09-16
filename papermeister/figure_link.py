"""The caption stage (P16 ②) as the client sees it: what to send, what to
believe, what to write.

The model (Astra, run by ocrserver) gets a paper's figures and browses the
paper's text itself; it returns, per figure, the printed caption, where it
read it, the entries the caption lists, and the figure's printed name. This
module does not call anything. It builds the request, checks the reply
against the request before a byte is written — fsis learned to verify on
both the writing and the reading side (design guide §0-5) — and applies what
survives, leaving alone what a person has claimed.

Three rules from fsis that shape every function here:

- **Only printed text goes into `caption` and entries.** A model describing
  the picture ("fossil specimen in lateral view") is not a caption, and once
  stored, nothing can tell the two apart. So a reply's caption must occur in
  the pages it says it read it from, and entry descriptions must be made of
  the caption's words.
- **A figure the model skipped keeps what it had.** fsis's sync wrote `[]`
  over 714 rows a day because "not found" and "empty" were the same value.
- **Fewer entries than before is a question, not an update** — unless the
  old entries had no source (they may be an earlier model's invention).

Identity of the input is `link_key`: the figure, the OCR text it was read
against, and the prompt. Change any of these and the row is due again;
nothing else re-runs it.
"""
from __future__ import annotations

import datetime
import hashlib
import html as html_mod
import json
import re
from dataclasses import dataclass, field

from . import figures
from .figure_store import PAGE, protection
from .models import Figure, FigureEntry, PaperFile, db

#: How many times the stage may fail on a figure before it needs `--retry-errors`.
MAX_ATTEMPTS = 3
#: A caption prefix this long that two figures on one page share is the same caption.
SHARED_CAPTION_CHARS = 80
#: Share of an entry description's words that must be in the caption's pages.
PRINTED_WORD_SHARE = 0.7
#: Share of the caption's words that must be on the pages it claims.
CAPTION_WORD_SHARE = 0.8

# Review reasons the stage raises (P17 §3.10). They go on the row; a person reads them.
CAPTION_NOT_PRINTED = 'caption_not_printed'
DESCRIPTION_NOT_PRINTED = 'description_not_printed'
CAPTION_SHARED = 'caption_shared'
PLATE_NO_ENTRIES = 'plate_no_entries'
ENTRIES_SHRANK = 'entries_shrank'

_WORD = re.compile(r'\w{4,}', re.UNICODE)
_TAG = re.compile(r'<[^>]+>')
_SPACE = re.compile(r'\s+')


def ocr_digest(pages: list[str]) -> str:
    """The identity of the OCR text the model reads — the cache, page by page."""
    h = hashlib.sha256()
    for text in pages:
        h.update((text or '').encode('utf-8'))
        h.update(b'\x00')
    return h.hexdigest()


def link_key(row: Figure, digest: str, prompt_version: str) -> str:
    return f'{row.file_hash}|{row.page}|{row.bbox_page_1000}|{digest}|{prompt_version}'


# ── what to send ─────────────────────────────────────────────────────

@dataclass
class LinkTargets:
    due: list[Figure] = field(default_factory=list)        # need linking
    context: list[Figure] = field(default_factory=list)    # settled rows the model must see, not touch
    excluded: list[tuple[Figure, str]] = field(default_factory=list)


def link_targets(paper_file: PaperFile, digest: str, prompt_version: str,
                 retry_errors: bool = False) -> LinkTargets:
    """Which of a file's figures the caption stage is due on, and why the rest are not.

    Every exclusion is named (fsis: a lane that "did nothing, no error" cost a
    morning). Captioned-plate photographs carry their own caption and are left
    out of the input altogether — given the plate's explanation too, the model
    poured it into them (fsis ref 2360). Rows a person locked are sent as
    context: left out, the model attaches their explanation to a neighbour.
    """
    out = LinkTargets()
    rows = (Figure.select().where(Figure.paper_file == paper_file.id).order_by(Figure.page, Figure.id))
    for row in rows:
        if row.dismissed:
            out.excluded.append((row, 'dismissed'))
        elif row.assembly == PAGE:
            out.excluded.append((row, 'page_placeholder'))
        elif row.page_kind == figures.CAPTIONED_PLATE:
            out.excluded.append((row, 'own_caption'))
        elif protection(row).caption:
            out.context.append(row)
        elif row.link_key == link_key(row, digest, prompt_version):
            out.excluded.append((row, 'linked'))
        elif row.link_attempts >= MAX_ATTEMPTS and not retry_errors:
            out.excluded.append((row, 'attempts_exhausted'))
        else:
            out.due.append(row)
    return out


def _figure_item(row: Figure, locked: bool) -> dict:
    item = {
        'figure_id': str(row.id),
        'page': row.page,                                   # 0-based, as the OCR cache and the workspace
        'bbox_page_1000': json.loads(row.bbox_page_1000),
        'assembly': row.assembly,
        'page_kind': row.page_kind,
        'name_hint': row.name,
        'plate': row.plate,
        'plate_inferred': row.plate_inferred,
        'caption_hint': row.caption_hint,                   # the rule's guess; may be wrong
        'label_hints': json.loads(row.label_hints_json or '[]'),
        'reasons': json.loads(row.uncertain_reasons_json or '[]'),
        'locked': locked,
    }
    detect = json.loads(row.detect_caption_json or '{}')
    if detect:
        item['detect_caption'] = detect
    if locked:
        item['caption'] = row.caption
        item['entries'] = [{'label': e.label, 'description': e.description}
                           for e in row.entries.order_by(FigureEntry.order)]
    return item


def link_item(paper_file: PaperFile, pages: list[str], targets: LinkTargets, digest: str,
              prompt_version: str) -> dict:
    """The one item of a paper's link job (wrapper API: `POST /figures/link`).

    Page texts are not in here: the server holds them as the paper's
    workspace, keyed by the same `ocr_digest` (client plan §10.1). What is
    here is every figure the model must consider and the pages the rule
    thinks talk about plates — hints, not instructions. `key` comes back on
    the result unchanged.
    """
    facts = [figures.read_page(i, t or '') for i, t in enumerate(pages)]
    return {
        'key': f'{paper_file.hash[:12]}@{digest[:12]}@{prompt_version}',
        'page_count': len(pages),
        'figures': ([_figure_item(r, locked=False) for r in targets.due]
                    + [_figure_item(r, locked=True) for r in targets.context]),
        'hints': {
            'plate_pages': [f.page for f in facts if f.printed],
            'explanation_pages': [f.page for f in facts if f.explained],
            'caption_pages': [f.page for f in facts
                              if any(r.label == 'Caption' and r.is_numbered_caption for r in f.regs)],
        },
    }


def link_payload(paper_file: PaperFile, pages: list[str], targets: LinkTargets,
                 digest: str, client_id: str, prompt: dict | None = None) -> dict:
    """The request body of `POST /figures/link`: one item, plus the prompt block."""
    version = (prompt or {}).get('version', '')
    body = {
        'client_id': client_id,
        'file_hash': paper_file.hash,
        'ocr_digest': digest,
        'items': [link_item(paper_file, pages, targets, digest, version)],
        'options': {'model': 'gpt-6-astra', 'effort': 'high'},
    }
    if prompt:
        body['prompt'] = prompt
    return body


def workspace_payload(paper_file: PaperFile, pages: list[str]) -> dict:
    """What the server builds the paper's workspace from — the client's cache, verbatim."""
    return {'file_hash': paper_file.hash, 'ocr_digest': ocr_digest(pages),
            'pages': [{'page': i, 'markdown': t or ''} for i, t in enumerate(pages)]}


# ── what to believe ──────────────────────────────────────────────────

@dataclass
class LinkCheck:
    accepted: dict[str, dict] = field(default_factory=dict)    # figure_id -> the model's figure result
    rejected: list[tuple[str, str]] = field(default_factory=list)
    review: dict[str, list[str]] = field(default_factory=dict)  # figure_id -> reasons for a person
    skipped: list[str] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)            # ids the reply names that we never sent

    def flag(self, figure_id: str, reason: str) -> None:
        self.review.setdefault(figure_id, [])
        if reason not in self.review[figure_id]:
            self.review[figure_id].append(reason)


def _words(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text or '')}


def _page_words(pages: list[str], page_numbers) -> set[str]:
    words: set[str] = set()
    for p in page_numbers:
        if 0 <= p < len(pages):
            words |= _words(html_mod.unescape(_TAG.sub(' ', pages[p] or '')))
    return words


def _share(words: set[str], within: set[str]) -> float:
    return 1.0 if not words else len(words & within) / len(words)


def validate_link_result(payload: dict, result: dict, pages: list[str],
                         existing: dict[str, Figure] | None = None) -> LinkCheck:
    """Check a reply against the request and the paper before anything is written.

    Rejections are the reply's fault (an id we did not send, a page the paper
    does not have, a shape that is not a caption). Review reasons are for a
    person: the reply may be right, and the rule cannot tell.
    """
    check = LinkCheck()
    item = payload['items'][0] if 'items' in payload else payload
    sent = {f['figure_id']: f for f in item['figures']}
    page_count = item.get('page_count', len(pages))
    seen_captions: dict[tuple[int, str], str] = {}
    existing = existing or {}

    for item in result.get('skipped', []) or []:
        fid = str(item.get('figure_id', ''))
        (check.skipped if fid in sent else check.unknown).append(fid)

    for item in result.get('figures', []) or []:
        fid = str(item.get('figure_id', ''))
        if fid not in sent:
            check.unknown.append(fid)
            continue
        if sent[fid].get('locked'):
            check.rejected.append((fid, 'locked'))
            continue
        caption = _SPACE.sub(' ', str(item.get('caption') or '')).strip()
        caption_pages = item.get('caption_pages')
        if caption_pages is None and item.get('caption_page') is not None:
            caption_pages = [item['caption_page']]
        caption_pages = [int(p) for p in (caption_pages or [])]
        if not caption:
            check.rejected.append((fid, 'empty_caption'))
            continue
        if not caption_pages or any(p < 0 or p >= page_count for p in caption_pages):
            check.rejected.append((fid, 'caption_pages_outside_paper'))
            continue
        entries = item.get('entries') or []
        if not isinstance(entries, list) or any(
                not isinstance(e, dict) or not isinstance(e.get('label', ''), str) for e in entries):
            check.rejected.append((fid, 'malformed_entries'))
            continue
        cont = item.get('continuation_of')
        if cont is not None and str(cont) not in sent:
            check.rejected.append((fid, 'continuation_of_unknown'))
            continue

        # Printed, not invented: the caption's words are on the pages it names,
        # and the entries are made of the caption's (and those pages') words.
        printed = _page_words(pages, caption_pages)
        if _share(_words(caption), printed) < CAPTION_WORD_SHARE:
            check.flag(fid, CAPTION_NOT_PRINTED)
        allowed = printed | _words(caption)
        for e in entries:
            if _share(_words(e.get('description', '')), allowed) < PRINTED_WORD_SHARE:
                check.flag(fid, DESCRIPTION_NOT_PRINTED)
                break

        # The same caption on two figures of one page (fsis EC §3-3: 190 rows).
        key = (sent[fid]['page'], caption[:SHARED_CAPTION_CHARS].lower())
        other = seen_captions.get(key)
        if other is not None and other != fid:
            check.flag(fid, CAPTION_SHARED)
            check.flag(other, CAPTION_SHARED)
        seen_captions.setdefault(key, fid)

        # A plate with a caption but no entries: the explanation was found but
        # not read, or a batch dropped it (fsis DG §4-3).
        if sent[fid].get('page_kind') == figures.PLATE_KIND and not entries:
            check.flag(fid, PLATE_NO_ENTRIES)

        # Fewer entries than a sourced earlier result: ask, do not overwrite.
        row = existing.get(fid)
        if row is not None and row.caption_source and row.caption_source != 'none':
            had = row.entries.count()
            if entries and had > len(entries):
                check.flag(fid, ENTRIES_SHRANK)
                check.rejected.append((fid, ENTRIES_SHRANK))
                continue

        check.accepted[fid] = {**item, 'caption': caption, 'caption_pages': caption_pages, 'entries': entries}
    return check


# ── what to write ────────────────────────────────────────────────────

@dataclass
class LinkApplied:
    written: int = 0
    unchanged: int = 0
    protected: int = 0
    failed: int = 0          # attempts counted on figures that were due but got nothing usable
    reviewed: int = 0


def result_digest(item: dict) -> str:
    return hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def apply_link(targets: LinkTargets, check: LinkCheck, result: dict, digest: str,
               prompt_version: str, model: str) -> LinkApplied:
    """Write what the check accepted, in one transaction per file.

    Skipped and rejected figures keep what they had and count an attempt.
    A figure whose result is byte-for-byte what it already has is unchanged —
    the same file name with new content is what fsis missed on 157 plates,
    so it is the content that is compared.
    """
    out = LinkApplied()
    now = datetime.datetime.now()
    by_id = {str(r.id): r for r in targets.due}
    with db.atomic():
        for fid, row in by_id.items():
            if protection(row).caption:
                out.protected += 1
                continue
            reasons = check.review.get(fid, [])
            item = check.accepted.get(fid)
            if item is None:
                row.link_attempts += 1
                if reasons:
                    _store_reasons(row, reasons)
                    out.reviewed += 1
                row.save()
                out.failed += 1
                continue
            new_digest = result_digest(item)
            if row.link_result_digest == new_digest and row.link_key == link_key(row, digest, prompt_version):
                out.unchanged += 1
                continue
            row.caption = item['caption']
            row.caption_source = item.get('caption_source') or 'explanation_page'
            row.caption_page = item['caption_pages'][0]
            row.caption_pages_json = json.dumps(item['caption_pages'])
            if item.get('name'):
                row.name = str(item['name']).strip()
            cont = item.get('continuation_of')
            row.continuation_of = int(cont) if cont is not None else None
            row.link_key = link_key(row, digest, prompt_version)
            row.link_result_digest = new_digest
            row.link_model = model
            row.link_prompt_version = prompt_version
            row.linked_at = now
            row.link_attempts = 0
            _store_reasons(row, reasons)
            row.save()
            FigureEntry.delete().where(FigureEntry.figure == row.id).execute()
            for order, e in enumerate(item['entries']):
                FigureEntry.create(
                    figure=row.id, order=order,
                    label=str(e.get('label', '')).strip(),
                    printed_label=str(e.get('printed_label') or e.get('label', '')).strip(),
                    label_status='printed',
                    specimen_number=str(e.get('specimen_number') or '').strip(),
                    description=_SPACE.sub(' ', str(e.get('description', ''))).strip())
            out.written += 1
            if reasons:
                out.reviewed += 1
    return out


def _store_reasons(row: Figure, reasons: list[str]) -> None:
    """Keep the rule's own doubts; add the stage's, without repeating."""
    have = json.loads(row.uncertain_reasons_json or '[]')
    rule = [r for r in have if r not in _LINK_REASONS]
    row.uncertain_reasons_json = json.dumps(rule + [r for r in reasons if r not in rule])


_LINK_REASONS = frozenset({CAPTION_NOT_PRINTED, DESCRIPTION_NOT_PRINTED, CAPTION_SHARED,
                           PLATE_NO_ENTRIES, ENTRIES_SHRANK})
