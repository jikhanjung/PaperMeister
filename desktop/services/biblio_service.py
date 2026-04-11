"""Bridge between the desktop detail panel and papermeister.biblio_reflect."""
from dataclasses import dataclass

from papermeister import biblio_reflect
from papermeister.models import Paper, PaperBiblio


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


_REASON_BLURB = {
    '':                   'All checks passed. Click Apply to reflect into Paper.',
    'missing_title':      'Biblio has no title.',
    'missing_authors':    'Biblio has no authors.',
    'missing_year':       'Biblio has no year (and doc_type is not book/chapter/report).',
    'unknown_doctype':    'doc_type is unknown — cannot classify.',
    'low_confidence':     'Confidence is not "high". Review manually.',
    'visual_review_flag': 'Extractor flagged this for visual review.',
    'override_conflict':  'Paper is already curated and biblio adds nothing new.',
    'journal_issue':      'Journal issues go through the promote flow, not reflect.',
    'already_committed':  'Already auto-committed in a previous run.',
    'already_applied':    'Already applied by user.',
    'rejected':           'Previously rejected — apply manually if you changed your mind.',
    'no_biblio':          'No PaperBiblio extraction for this paper yet.',
}


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
    return ApplyPreview(
        has_biblio=True,
        decision_action=decision.action,
        decision_reason=decision.reason,
        biblio_id=biblio.id,
        biblio_status=biblio.status,
        button_enabled=enabled,
        button_label=label,
        tooltip=tooltip,
    )


def apply_paper(paper_id: int) -> tuple[str, bool, str]:
    """Execute apply_single. Returns (action, changed, reason)."""
    decision, changed = biblio_reflect.apply_single(paper_id)
    return decision.action, changed, decision.reason
