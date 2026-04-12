"""Bridge between the desktop detail panel and papermeister.biblio_reflect."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from papermeister import biblio_reflect
from papermeister.database import db
from papermeister.models import Author, Paper, PaperBiblio


# ── Author name display ─────────────────────────────────────────


def _is_cjk_char(c: str) -> bool:
    cp = ord(c)
    return (
        0x3400 <= cp <= 0x9FFF       # CJK Unified Ideographs
        or 0xAC00 <= cp <= 0xD7AF    # Hangul Syllables
        or 0x3040 <= cp <= 0x30FF    # Hiragana/Katakana
    )


def split_author_name(name: str) -> tuple[str, str]:
    """Split a name into (firstName, lastName).

    Handles "Last, First", space-separated, and CJK unspaced names.
    """
    name = name.strip()
    if ',' in name:
        parts = [p.strip() for p in name.split(',', 1)]
        if len(parts) == 2 and parts[1]:
            return parts[1], parts[0]  # "Last, First" → (First, Last)
        return '', parts[0]

    tokens = name.split()
    if len(tokens) == 1:
        single = tokens[0]
        if all(_is_cjk_char(c) for c in single):
            if len(single) == 4:
                return single[2:], single[:2]
            if len(single) == 3:
                return single[1:], single[:1]
        return '', single
    return ' '.join(tokens[:-1]), tokens[-1]


def format_author_display(name: str) -> str:
    """Format a name as 'Lastname, Firstname' for display."""
    first, last = split_author_name(name)
    if not first:
        return last
    return f'{last}, {first}'


# ── Field comparison ─────────────────────────────────────────────


@dataclass
class FieldDiff:
    """One field comparison between Paper (current) and PaperBiblio (extracted)."""
    field_key: str     # 'title' | 'authors' | 'year' | 'journal' | 'doi'
    label: str
    paper_value: str   # current Paper / Zotero value (display string)
    biblio_value: str  # extracted PaperBiblio value (display string)
    kind: str          # 'match' | 'conflict' | 'fill' (paper empty, biblio has value)


@dataclass
class ApplyPreview:
    has_biblio: bool
    decision_action: str       # auto_commit | needs_review | skip
    decision_reason: str       # empty on auto_commit
    biblio_id: int | None
    biblio_status: str         # extracted | needs_review | auto_committed | applied | rejected
    button_enabled: bool       # True unless skip
    button_label: str          # 'Apply Biblio' or status-aware variant
    tooltip: str
    diffs: list[FieldDiff] = field(default_factory=list)
    source_line: str = ''      # e.g. "llm-haiku · confidence: high · doc_type: article"


_REASON_BLURB = {
    '':                   'All checks passed. Click Apply to reflect into Paper.',
    'missing_title':      'Biblio has no title.',
    'missing_authors':    'Biblio has no authors.',
    'missing_year':       'Biblio has no year (and doc_type is not book/chapter/report).',
    'unknown_doctype':    'doc_type is unknown — cannot classify.',
    'low_confidence':     'Confidence is not "high". Review manually.',
    'visual_review_flag': 'Extractor flagged this for visual review.',
    'override_conflict':  'Paper is already curated and biblio adds nothing new.',
    'curated_author_shortfall': 'Curated Paper has fewer authors than the biblio extraction — review manually.',
    'journal_issue':      'Journal issues go through the promote flow, not reflect.',
    'already_committed':  'Already auto-committed in a previous run.',
    'already_applied':    'Already applied by user.',
    'rejected':           'Previously rejected — apply manually if you changed your mind.',
    'already_complete':   'Paper already matches the biblio extraction — nothing to change.',
    'no_biblio':          'No PaperBiblio extraction for this paper yet.',
}

_FIELDS = [
    ('title',   'Title'),
    ('authors', 'Authors'),
    ('year',    'Year'),
    ('journal', 'Journal'),
    ('doi',     'DOI'),
]


def _authors_display(names: list[str]) -> str:
    """Format a list of author names, one per line, as 'Lastname, Firstname'."""
    if not names:
        return ''
    return '\n'.join(format_author_display(n) for n in names)


def _parse_display_authors(text: str) -> list[str]:
    """Reverse of _authors_display: parse "Lastname, Firstname" lines back to names.

    Each non-empty line is treated as one author. If the line contains a comma,
    it's interpreted as "Last, First" and stored as "First Last". Otherwise
    the line is stored as-is.
    """
    names: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if ',' in line:
            parts = [p.strip() for p in line.split(',', 1)]
            if len(parts) == 2 and parts[1]:
                # "Last, First" → "First Last"
                names.append(f'{parts[1]} {parts[0]}')
            else:
                names.append(parts[0])
        else:
            names.append(line)
    return names


def _parse_biblio_authors(authors_json: str) -> list[str]:
    """Parse authors_json to a list of name strings (handles both formats)."""
    try:
        data = json.loads(authors_json or '[]')
    except Exception:
        return []
    out: list[str] = []
    for entry in data:
        if isinstance(entry, dict):
            name = entry.get('name') or entry.get('full_name') or ''
        elif isinstance(entry, str):
            name = entry
        else:
            continue
        name = name.strip()
        if name:
            out.append(name)
    return out


def _compute_comparisons(paper: Paper, biblio: PaperBiblio) -> list[FieldDiff]:
    """Compare Paper metadata against PaperBiblio extraction for all fields."""
    diffs: list[FieldDiff] = []

    # Title
    pt = (paper.title or '').strip()
    bt = (biblio.title or '').strip()
    diffs.append(FieldDiff('title', 'Title', pt, bt, _kind(pt, bt)))

    # Authors
    paper_authors = [
        a.name for a in
        Author.select(Author.name)
        .where(Author.paper == paper)
        .order_by(Author.order)
    ]
    biblio_authors = _parse_biblio_authors(biblio.authors_json or '')
    pa_display = _authors_display(paper_authors)
    ba_display = _authors_display(biblio_authors)
    diffs.append(FieldDiff('authors', 'Authors', pa_display, ba_display, _kind(pa_display, ba_display)))

    # Year
    py_str = str(paper.year) if paper.year is not None else ''
    by_str = str(biblio.year) if biblio.year is not None else ''
    diffs.append(FieldDiff('year', 'Year', py_str, by_str, _kind(py_str, by_str)))

    # Journal
    pj = (paper.journal or '').strip()
    bj = (biblio.journal or '').strip()
    diffs.append(FieldDiff('journal', 'Journal', pj, bj, _kind(pj, bj)))

    # DOI
    pd = (paper.doi or '').strip()
    bd = (biblio.doi or '').strip()
    diffs.append(FieldDiff('doi', 'DOI', pd, bd, _kind(pd, bd)))

    return diffs


def _kind(paper_val: str, biblio_val: str) -> str:
    if paper_val == biblio_val:
        return 'match'
    if not biblio_val:
        return 'match'  # biblio has nothing — treat as match (nothing to offer)
    if not paper_val:
        return 'fill'
    return 'conflict'


def preview_apply(paper_id: int) -> ApplyPreview:
    paper = Paper.get_or_none(Paper.id == paper_id)
    if paper is None:
        return ApplyPreview(
            has_biblio=False, decision_action='skip', decision_reason='paper_not_found',
            biblio_id=None, biblio_status='', button_enabled=False,
            button_label='Apply Biblio', tooltip='Paper not found',
        )
    biblio = biblio_reflect.select_best_biblio(paper)
    if biblio is None:
        return ApplyPreview(
            has_biblio=False, decision_action='skip', decision_reason='no_biblio',
            biblio_id=None, biblio_status='', button_enabled=False,
            button_label='Apply Biblio',
            tooltip=_REASON_BLURB['no_biblio'],
        )

    decision = biblio_reflect.evaluate(biblio, paper)
    label = 'Apply Biblio'
    if biblio.status == 'applied':
        label = 'Applied'
    elif biblio.status == 'auto_committed':
        label = 'Auto-committed'

    enabled = decision.action != 'skip' and biblio.status not in ('applied', 'auto_committed')
    tooltip = _REASON_BLURB.get(decision.reason, decision.reason or _REASON_BLURB[''])
    if decision.action == 'auto_commit':
        tooltip = _REASON_BLURB['']
    elif decision.action == 'needs_review':
        tooltip = f'Needs review: {tooltip}  (manual apply still possible)'

    comparisons = _compute_comparisons(paper, biblio)

    source_line = (
        f"{biblio.source or '?'}  ·  confidence: {biblio.confidence or '—'}  ·  "
        f"doc_type: {biblio.doc_type or '—'}  ·  status: {biblio.status}"
    )

    return ApplyPreview(
        has_biblio=True,
        decision_action=decision.action,
        decision_reason=decision.reason,
        biblio_id=biblio.id,
        biblio_status=biblio.status,
        button_enabled=enabled,
        button_label=label,
        tooltip=tooltip,
        diffs=comparisons,
        source_line=source_line,
    )


def apply_merged(
    paper_id: int,
    biblio_id: int,
    overrides: dict[str, str | None],
) -> tuple[bool, str]:
    """Apply per-field values from the comparison table.

    overrides maps field_key → new_value (str) or None.
    None means "keep the current Paper value" (paper radio was selected).
    A str value is the (possibly edited) text from the biblio edit widget.
    For authors, the value is newline-separated "Lastname, Firstname" lines
    which are reverse-split back to storage names.
    Returns (changed, message).
    """
    paper = Paper.get_or_none(Paper.id == paper_id)
    if paper is None:
        return False, 'Paper not found'
    biblio = PaperBiblio.get_or_none(PaperBiblio.id == biblio_id)
    if biblio is None:
        return False, 'PaperBiblio not found'

    fields_to_apply = {k: v for k, v in overrides.items() if v is not None}
    if not fields_to_apply:
        biblio.status = 'applied'
        biblio.review_reason = ''
        biblio.save()
        return False, 'No changes (kept current values)'

    changes = False
    with db.atomic():
        if 'title' in fields_to_apply:
            new_title = fields_to_apply['title'].strip()
            if new_title != (paper.title or '').strip():
                paper.title = new_title
                changes = True

        if 'year' in fields_to_apply:
            year_str = fields_to_apply['year'].strip()
            try:
                new_year = int(year_str) if year_str else None
            except ValueError:
                new_year = None
            if new_year != paper.year:
                paper.year = new_year
                changes = True

        if 'journal' in fields_to_apply:
            new_journal = fields_to_apply['journal'].strip()
            if new_journal != (paper.journal or '').strip():
                paper.journal = new_journal
                changes = True

        if 'doi' in fields_to_apply:
            new_doi = fields_to_apply['doi'].strip()
            if new_doi != (paper.doi or '').strip():
                paper.doi = new_doi
                changes = True

        if 'authors' in fields_to_apply:
            raw_lines = fields_to_apply['authors'].strip()
            names = _parse_display_authors(raw_lines) if raw_lines else []
            Author.delete().where(Author.paper == paper).execute()
            for i, name in enumerate(names):
                Author.create(paper=paper, name=name, order=i)
            changes = True

        if changes:
            paper.save()

        biblio.status = 'applied'
        biblio.review_reason = ''
        biblio.save()

    applied_fields = ', '.join(sorted(fields_to_apply))
    return changes, f'Applied: {applied_fields}'


def apply_paper(paper_id: int) -> tuple[str, bool, str]:
    """Execute apply_single. Returns (action, changed, reason)."""
    decision, changed = biblio_reflect.apply_single(paper_id)
    return decision.action, changed, decision.reason
