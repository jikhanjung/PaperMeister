"""What is left to do on a paper's figures, in the five counts that together
mean "done" — and only together (fsis design guide §6-6).

A review list at zero is not completion: figures may still be queued for a
stage, results may be waiting to be applied, some figures never became
candidates, and a person's fixes may not have survived. fsis reported the
review list and found the other four later. So this reports all five, from
the same judgements the lanes use (`link_targets`, `split_targets`, the
reasons on the rows) — a report that used its own rules would disagree with
the lanes the day a rule changed.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from . import figure_link, figure_panels, figures
from .figure_store import PAGE, protection
from .models import Figure, PaperFile

#: Reasons that send a figure to the re-judgement stage (①′) before the
#: caption stage. `no_caption` is not one: the caption stage reads the whole
#: paper and settles most of those itself (099 §5).
DETECT_TRIGGERS = frozenset({
    figures.DUP_NUMBER_REASON, figures.MANY_MARKS_REASON, figures.UNMARKED_PLATE_PAGE,
    figures.TEXT_AS_FIGURE, figures.FRAGMENTED,
    figures.PLATE_WITHOUT_PICTURES, figures.CAPTION_WITHOUT_FIGURE,
    # The caption stage gave several figures on one page the same caption:
    # photographs of one printed figure the parser listed apart (Hahn & Hahn
    # 1988 p.9, Kayser 1884 Tafel IV). Merging is the re-judgement's job;
    # the caption stage then runs again on the merged row.
    figure_link.CAPTION_SHARED,
})
#: Reasons a person reads — everything a stage or the rule left on a row.
HUMAN_REASONS = DETECT_TRIGGERS | {figures.NO_CAPTION} | figure_link._LINK_REASONS | figure_panels._PANEL_REASONS


@dataclass
class Review:
    """One file's five counts."""

    auto_pending: Counter = field(default_factory=Counter)     # stage -> figures waiting for it
    apply_pending: Counter = field(default_factory=Counter)    # results fetched but not applied (needs the server)
    human: Counter = field(default_factory=Counter)            # reason -> figures a person should look at
    outside: Counter = field(default_factory=Counter)          # why a figure is no candidate for the next stage
    preserved: Counter = field(default_factory=Counter)        # what a person has claimed
    figures: int = 0

    def update(self, other: Review) -> None:
        for name in ('auto_pending', 'apply_pending', 'human', 'outside', 'preserved'):
            getattr(self, name).update(getattr(other, name))
        self.figures += other.figures


def review_reasons(row: Figure) -> list[str]:
    """The reasons a person should look at this row, from the row itself."""
    import json
    return [r for r in json.loads(row.uncertain_reasons_json or '[]') if r in HUMAN_REASONS]


def review_file(paper_file: PaperFile, pages: list[str], link_prompt: str, panels_prompt: str) -> Review:
    out = Review()
    digest = figure_link.ocr_digest(pages)
    rows = list(Figure.select().where(Figure.paper_file == paper_file.id))
    out.figures = sum(1 for r in rows if not r.dismissed and r.assembly != PAGE)

    for row in rows:
        if row.dismissed:
            continue
        p = protection(row)
        if row.user_confirmed:
            out.preserved['user_confirmed'] += 1
        for name, on in (('bbox_locked', row.bbox_locked), ('caption_locked', row.caption_locked),
                         ('panels_locked', row.panels_locked)):
            if on:
                out.preserved[name] += 1
        reasons = review_reasons(row)
        for r in reasons:
            out.human[r] += 1
        if row.plate_inferred:
            out.human['plate_inferred (inference, not doubt)'] += 1
        if any(r in DETECT_TRIGGERS for r in reasons) and not row.detect_key and not p.assembly:
            out.auto_pending['detect'] += 1
    for row in rows:
        if row.dismissed and row.dismissed_by == 'user':
            out.preserved['dismissed_by_user'] += 1

    link = figure_link.link_targets(paper_file, digest, link_prompt)
    out.auto_pending['link'] += len(link.due)
    for _, why in link.excluded:
        if why in ('own_caption', 'page_placeholder'):
            out.outside[f'link: {why}'] += 1
        elif why == 'attempts_exhausted':
            out.human['link: attempts_exhausted'] += 1

    split = figure_panels.split_targets(paper_file, panels_prompt)
    out.auto_pending['panels'] += len(split.due)
    out.auto_pending['panels: rematch'] += len(split.rematch)
    for _, why in split.excluded:
        if why in ('no_caption', 'entries_lt_2', 'map', 'page_placeholder'):
            out.outside[f'panels: {why}'] += 1
        elif why == 'attempts_exhausted':
            out.human['panels: attempts_exhausted'] += 1
    return out


def format_review(review: Review, files: int) -> str:
    lines = [f'{files} file(s), {review.figures:,} figures (folded and placeholders not counted)', '']
    for title, counter, note in (
        ('1. Waiting for a stage', review.auto_pending, 'nothing to review yet — the lanes have not run'),
        ('2. Fetched, not applied', review.apply_pending, 'needs the server: GET /figures/jobs'),
        ('3. For a person', review.human, 'the reasons on the rows'),
        ('4. Outside the candidates', review.outside, 'why the next stage will not see them'),
        ('5. Preserved', review.preserved, "a person's claims; re-assembly never touches these"),
    ):
        lines.append(f'{title}   ({note})')
        if not counter:
            lines.append('   —')
        for key, n in counter.most_common():
            lines.append(f'   {key:<40} {n:>7,}')
        lines.append('')
    return '\n'.join(lines)
