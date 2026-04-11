"""PaperBiblio → Paper reflection runner.

Implements the policy defined in devlog/20260411_P08_PaperBiblio_Reflection_Policy.md.
All Paper updates are atomic (single transaction per paper).

Entry points:

- select_best_biblio(paper)  -> PaperBiblio | None
- evaluate(biblio, paper)    -> Decision
- apply(biblio, paper)       -> bool (True if changes made)
- reflect_all(...)           -> ReflectStats (batch runner)

CLI wrapper lives at scripts/reflect_biblio.py.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Iterable, Literal

from .models import Author, Folder, Paper, PaperBiblio, Source, db


# ── Source ranking (P08 §1) ───────────────────────────────────
# Higher rank = prefer over lower rank. Unknown sources default to rank 0.
SOURCE_RANK = {
    'llm-sonnet-vision': 50,
    'llm-haiku-vision':  40,
    'llm-sonnet':        30,
    'llm-haiku-v2':      22,
    'llm-haiku':         20,
}

CONFIDENCE_RANK = {'high': 30, 'medium': 20, 'low': 10, '': 0}

# doc_types that do not require a `year` value (P08 §2.1)
YEARLESS_DOCTYPES = {'book', 'chapter', 'report'}

# doc_types that are explicitly out-of-scope for auto-commit (P08 §2.2)
NON_AUTOCOMMIT_DOCTYPES = {'journal_issue', 'unknown', ''}


Action = Literal['auto_commit', 'needs_review', 'skip']


@dataclass
class Decision:
    action: Action
    reason: str = ''
    biblio_id: int | None = None

    @property
    def can_apply(self) -> bool:
        return self.action in ('auto_commit', 'needs_review')  # manual override still possible


@dataclass
class ReflectStats:
    scanned: int = 0
    auto_committed: int = 0
    needs_review: int = 0
    skipped: int = 0
    errors: int = 0
    reasons: dict[str, int] = field(default_factory=dict)

    def bump_reason(self, reason: str):
        self.reasons[reason] = self.reasons.get(reason, 0) + 1


# ── Helpers ───────────────────────────────────────────────────

def _parse_authors(authors_json: str) -> list[str]:
    """Accept both [{"name": ...}] and ["Name", ...] shapes."""
    if not authors_json:
        return []
    try:
        data = json.loads(authors_json)
    except Exception:
        return []
    out: list[str] = []
    for entry in data:
        if isinstance(entry, dict):
            name = entry.get('name') or entry.get('full_name') or ''
            if name:
                out.append(name.strip())
        elif isinstance(entry, str):
            if entry.strip():
                out.append(entry.strip())
    return out


def _is_stub_paper(paper: Paper) -> bool:
    """Per P07 Paper identity section.

    Stub = no year AND no authors AND no applied/committed biblio yet.
    The caller may still decide to override based on the biblio evaluation.
    """
    if paper.year is not None:
        return False
    if Author.select().where(Author.paper == paper).count() > 0:
        return False
    return True


def _source_rank(source: str) -> int:
    return SOURCE_RANK.get(source, 0)


# ── Selection (P08 §1) ────────────────────────────────────────

def select_best_biblio(paper: Paper) -> PaperBiblio | None:
    """Return the best candidate PaperBiblio for a Paper.

    Tie-break (descending priority):
      1. status == 'applied'   (highest — already chosen earlier)
      2. source rank           (sonnet-vision > haiku-vision > sonnet > haiku)
      3. confidence rank       (high > medium > low)
      4. extracted_at desc
    """
    candidates: list[PaperBiblio] = list(
        PaperBiblio
        .select()
        .where(PaperBiblio.paper == paper)
        .where(PaperBiblio.status != 'rejected')
    )
    if not candidates:
        return None

    def key(b: PaperBiblio):
        applied_rank = 1 if b.status == 'applied' else 0
        return (
            applied_rank,
            _source_rank(b.source or ''),
            CONFIDENCE_RANK.get(b.confidence or '', 0),
            b.extracted_at or 0,
        )

    candidates.sort(key=key, reverse=True)
    return candidates[0]


# ── Evaluation (P08 §2, §4, §5) ───────────────────────────────

def evaluate(biblio: PaperBiblio, paper: Paper) -> Decision:
    """Decide whether `biblio` can be auto-committed to `paper`."""
    # Already resolved
    if biblio.status == 'auto_committed':
        return Decision('skip', 'already_committed', biblio.id)
    if biblio.status == 'applied':
        return Decision('skip', 'already_applied', biblio.id)
    if biblio.status == 'rejected':
        return Decision('skip', 'rejected', biblio.id)

    # Out-of-scope doc types first (journal_issue is a promote candidate,
    # not a reflection target).
    if biblio.doc_type == 'journal_issue':
        return Decision('skip', 'journal_issue', biblio.id)

    authors = _parse_authors(biblio.authors_json or '')
    title_ok = bool((biblio.title or '').strip())
    year_ok = biblio.year is not None or (biblio.doc_type in YEARLESS_DOCTYPES)
    doctype_ok = biblio.doc_type and biblio.doc_type not in NON_AUTOCOMMIT_DOCTYPES
    confidence_ok = (biblio.confidence or '') == 'high'

    # Field-level failures (P08 §5)
    if not title_ok:
        return Decision('needs_review', 'missing_title', biblio.id)
    if not authors:
        return Decision('needs_review', 'missing_authors', biblio.id)
    if not year_ok:
        return Decision('needs_review', 'missing_year', biblio.id)
    if not doctype_ok:
        return Decision('needs_review', 'unknown_doctype', biblio.id)
    if biblio.needs_visual_review:
        return Decision('needs_review', 'visual_review_flag', biblio.id)
    if not confidence_ok:
        return Decision('needs_review', 'low_confidence', biblio.id)

    # Paper state (P08 §2.3, §4)
    if _is_stub_paper(paper):
        return Decision('auto_commit', '', biblio.id)

    # P08 §4.2.1: curated Paper whose author list is strictly shorter than
    # the biblio's is a strong signal that the curated data is incomplete.
    # Kick the whole decision to needs_review instead of half-filling other
    # slots while leaving authors untouched.
    existing_author_count = Author.select().where(Author.paper == paper).count()
    if existing_author_count > 0 and len(authors) > existing_author_count:
        return Decision('needs_review', 'curated_author_shortfall', biblio.id)

    # curated Paper: only fill empty slots (P08 §4.2)
    any_fill = False
    if not (paper.title or '').strip() and title_ok:
        any_fill = True
    if paper.year is None and biblio.year is not None:
        any_fill = True
    if not (paper.journal or '').strip() and (biblio.journal or '').strip():
        any_fill = True
    if not (paper.doi or '').strip() and (biblio.doi or '').strip():
        any_fill = True
    if Author.select().where(Author.paper == paper).count() == 0 and authors:
        any_fill = True

    if any_fill:
        return Decision('auto_commit', '', biblio.id)
    return Decision('needs_review', 'override_conflict', biblio.id)


# ── Application (P08 §3, §3.5, §6) ────────────────────────────

def apply(
    biblio: PaperBiblio,
    paper: Paper,
    *,
    dry_run: bool = False,
    force_override: bool = False,
) -> bool:
    """Apply `biblio` to `paper` per policy. Returns True if any change happened.

    Branches on `paper.zotero_key` (P08 §3.5):

    - Zotero-sourced  → `zotero_writeback.writeback_biblio()` (PATCH Zotero,
      then refresh local from the authoritative response).
    - filesystem stub → `_local_apply()` (direct local write, current behaviour).

    `force_override` is the escape hatch for `curated_author_shortfall` etc:
    when True, writeback may replace non-empty Zotero fields where the biblio
    has strictly more information (currently only creators).

    PaperBiblio.status is flipped to 'auto_committed' on success in either path.
    The single-paper entry point `apply_single()` later overrides to 'applied'
    when called from manual confirmation contexts (GUI / CLI --paper).
    """
    if paper.zotero_key:
        # Zotero-sourced — write upstream first, then refresh local mirror.
        from . import zotero_writeback
        from .zotero_client import ZoteroClient
        from .preferences import get_pref

        client = ZoteroClient(
            get_pref('zotero_user_id', ''),
            get_pref('zotero_api_key', ''),
        )
        result = zotero_writeback.writeback_biblio(
            biblio, paper, client=client,
            dry_run=dry_run, force_override=force_override,
        )

        if not dry_run:
            # Status transition happens here (not inside writeback) so the
            # two branches share the same policy surface.
            biblio.status = 'auto_committed'
            biblio.review_reason = result.reason
            biblio.save()

        # Even a no-op (action='noop') counts as "successfully reflected" for
        # the caller: Zotero is authoritative and already complete. Only a
        # real API write changes data, so `changed` mirrors that.
        return result.changed

    # filesystem stub (currently 0 rows; future standalone flow)
    return _local_apply(biblio, paper, dry_run=dry_run)


def _local_apply(biblio: PaperBiblio, paper: Paper, *, dry_run: bool = False) -> bool:
    """Local-only apply path (filesystem-sourced Paper with no zotero_key).

    Empty-slot fill for curated Paper, full replacement for stub. This was
    the entire pre-§3.5 `apply()` body; kept intact for the non-Zotero case.
    """
    authors = _parse_authors(biblio.authors_json or '')
    stub = _is_stub_paper(paper)

    changes = False

    def maybe(field_name: str, new_value):
        nonlocal changes
        current = getattr(paper, field_name, None)
        if stub:
            if new_value and new_value != current:
                setattr(paper, field_name, new_value)
                changes = True
        else:
            empty = (current is None) or (isinstance(current, str) and not current.strip())
            if empty and new_value:
                setattr(paper, field_name, new_value)
                changes = True

    def maybe_year():
        nonlocal changes
        if biblio.year is None:
            return
        if stub:
            if paper.year != biblio.year:
                paper.year = biblio.year
                changes = True
        else:
            if paper.year is None:
                paper.year = biblio.year
                changes = True

    if dry_run:
        snapshot = {
            'title': paper.title,
            'year': paper.year,
            'journal': paper.journal,
            'doi': paper.doi,
        }
        maybe('title', (biblio.title or '').strip())
        maybe('journal', (biblio.journal or '').strip())
        maybe('doi', (biblio.doi or '').strip())
        maybe_year()
        for k, v in snapshot.items():
            setattr(paper, k, v)
        return changes or (stub and authors and
                           Author.select().where(Author.paper == paper).count() == 0)

    with db.atomic():
        maybe('title', (biblio.title or '').strip())
        maybe('journal', (biblio.journal or '').strip())
        maybe('doi', (biblio.doi or '').strip())
        maybe_year()

        existing_authors = list(Author.select().where(Author.paper == paper))
        if stub and authors:
            Author.delete().where(Author.paper == paper).execute()
            for i, name in enumerate(authors):
                Author.create(paper=paper, name=name, order=i)
            changes = True
        elif not existing_authors and authors:
            for i, name in enumerate(authors):
                Author.create(paper=paper, name=name, order=i)
            changes = True

        if changes:
            paper.save()

        biblio.status = 'auto_committed'
        biblio.review_reason = ''
        biblio.save()

    return changes


def apply_single(
    paper_id: int,
    *,
    mark_applied: bool = True,
    force_override: bool = False,
) -> tuple[Decision, bool]:
    """GUI / CLI 'Apply Biblio' entry point.

    - Marks biblio as 'applied' on success (manual confirmation beats auto).
    - needs_review decisions still proceed (manual override); use
      force_override=True to additionally replace non-empty Zotero fields
      (e.g. for curated_author_shortfall).
    """
    paper = Paper.get_or_none(Paper.id == paper_id)
    if paper is None:
        return Decision('skip', 'paper_not_found'), False
    biblio = select_best_biblio(paper)
    if biblio is None:
        return Decision('skip', 'no_biblio'), False

    decision = evaluate(biblio, paper)
    if decision.action == 'skip':
        return decision, False

    changed = apply(
        biblio, paper, dry_run=False, force_override=force_override,
    )

    if mark_applied:
        # Flip to 'applied' whether or not the call caused a real write.
        # A no-op (Zotero already complete) after a user click is still
        # "the user confirmed this biblio", which is what 'applied' means.
        fresh = PaperBiblio.get(PaperBiblio.id == biblio.id)
        fresh.status = 'applied'
        fresh.save()
    return decision, changed


# ── Batch runner (P08 §6.2) ───────────────────────────────────

def _iter_papers_in_scope(
    *,
    source_id: int | None,
    folder_id: int | None,
    paper_ids: list[int] | None,
) -> Iterable[Paper]:
    query = Paper.select()
    if paper_ids:
        query = query.where(Paper.id.in_(paper_ids))
    elif folder_id is not None:
        query = query.where(Paper.folder == folder_id)
    elif source_id is not None:
        query = (
            Paper
            .select(Paper)
            .join(Folder, on=(Paper.folder == Folder.id))
            .where(Folder.source == source_id)
        )
    # Only papers that actually have a PaperBiblio row — avoids scanning all.
    biblio_paper_ids = {
        b.paper_id for b in PaperBiblio.select(PaperBiblio.paper).distinct()
    }
    for p in query:
        if p.id in biblio_paper_ids:
            yield p


def reflect_all(
    *,
    source_id: int | None = None,
    folder_id: int | None = None,
    paper_ids: list[int] | None = None,
    dry_run: bool = False,
    progress: callable | None = None,
) -> ReflectStats:
    stats = ReflectStats()
    for paper in _iter_papers_in_scope(
        source_id=source_id, folder_id=folder_id, paper_ids=paper_ids,
    ):
        stats.scanned += 1
        try:
            biblio = select_best_biblio(paper)
            if biblio is None:
                stats.skipped += 1
                stats.bump_reason('no_biblio')
                continue
            decision = evaluate(biblio, paper)
            if decision.action == 'skip':
                stats.skipped += 1
                stats.bump_reason(decision.reason)
                continue
            if decision.action == 'needs_review':
                stats.needs_review += 1
                stats.bump_reason(decision.reason)
                if not dry_run:
                    # stamp the biblio so the UI can filter
                    biblio.status = 'needs_review'
                    biblio.review_reason = decision.reason
                    biblio.save()
                continue
            # auto_commit
            apply(biblio, paper, dry_run=dry_run)
            stats.auto_committed += 1
        except Exception as exc:  # pragma: no cover - defensive
            stats.errors += 1
            if progress:
                progress(f'error on paper {paper.id}: {exc}')
        if progress and stats.scanned % 50 == 0:
            progress(f'scanned {stats.scanned}')
    return stats
