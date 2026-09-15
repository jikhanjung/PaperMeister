"""Assembled figures in the database — P16 Phase 1.

`figures.py` decides what a figure is; this keeps the decision. Re-running
assembly has to be safe at any time, because the rules will change — Phase 0
changed them twice in a day, and fsis changed its own nine times in the next —
and by then a row may carry a caption from the linking stage or panels someone
has looked at. So a stored figure is matched by what it is (same PDF, page, box
and assembly), and then:

- **produced again** — its hints are refreshed; if a re-assembly had folded it, it comes back;
- **produced again with its box a little moved** (a re-OCR draws the block a few
  permille differently) — the row moves with it, keeping its caption. Folding it
  and creating a new row would throw that work away; fsis found such rows among
  its "stale" ones and chose to keep them;
- **no longer produced** — folded (`dismissed_by='reassembly'`), never deleted;
- **touched by a person** (`user_confirmed`, or dismissed by a person) — left exactly as it is.

Planning is separate from writing so a dry run shows precisely what `--execute`
would do.
"""
import datetime
import json
from dataclasses import dataclass, field

from . import figures
from .models import Figure, PaperFile, db

REASSEMBLY = 'reassembly'
#: A new box overlapping an unmatched stored one this much is the same figure, moved.
MOVED_MIN_IOU = 0.5


def _key(file_hash: str, page: int, bbox, assembly: str):
    return file_hash, page, tuple(bbox), assembly


def _row_key(row: Figure):
    return _key(row.file_hash, row.page, json.loads(row.bbox_page_1000), row.assembly)


def iou(a, b) -> float:
    x0, y0, x1, y1 = max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    if not inter:
        return 0.0
    area_a = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    area_b = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    return inter / (area_a + area_b - inter)


def _hints(fig: figures.AssembledFigure) -> dict:
    return {
        'blocks_json': json.dumps([list(b) for b in fig.blocks]),
        'plate': fig.plate,
        'plate_inferred': fig.plate_inferred,
        'page_kind': fig.page_kind,
        'caption_hint': fig.caption_hint,
        'label_hints_json': json.dumps(list(fig.label_hints), ensure_ascii=False),
    }


def _stale(row: Figure, fig: figures.AssembledFigure) -> bool:
    if row.linked_at is None and row.name != fig.name_hint:
        return True
    return any(getattr(row, name) != value for name, value in _hints(fig).items())


@dataclass
class StorePlan:
    """What storing one file's assembly would change."""

    paper_file: PaperFile
    create: list[figures.AssembledFigure] = field(default_factory=list)
    refresh: list[tuple[Figure, figures.AssembledFigure]] = field(default_factory=list)
    move: list[tuple[Figure, figures.AssembledFigure]] = field(default_factory=list)
    restore: list[tuple[Figure, figures.AssembledFigure]] = field(default_factory=list)
    dismiss: list[Figure] = field(default_factory=list)
    untouched_by_rule: int = 0          # rows a person confirmed or dismissed

    @property
    def changes(self) -> int:
        return (len(self.create) + len(self.refresh) + len(self.move)
                + len(self.restore) + len(self.dismiss))


def plan_store(paper_file: PaperFile, assembled: list[figures.AssembledFigure]) -> StorePlan:
    """Compare a fresh assembly with what is stored for this file. Writes nothing."""
    plan = StorePlan(paper_file)
    existing = (list(Figure.select().where(Figure.paper_file == paper_file.id).order_by(Figure.id))
                if Figure.table_exists() else [])
    by_key: dict = {}
    for row in existing:
        by_key.setdefault(_row_key(row), row)

    matched = set()
    for fig in assembled:
        stored: Figure | None = by_key.get(_key(paper_file.hash, fig.page, fig.bbox, fig.assembly))
        if stored is None or stored.id in matched:
            plan.create.append(fig)
            continue
        matched.add(stored.id)
        if stored.user_confirmed or (stored.dismissed and stored.dismissed_by != REASSEMBLY):
            plan.untouched_by_rule += 1
        elif stored.dismissed:
            plan.restore.append((stored, fig))
        elif _stale(stored, fig):
            plan.refresh.append((stored, fig))

    # Figures whose box moved a little: same PDF edition, page and assembly.
    movable = [row for row in existing if row.id not in matched and not row.dismissed
               and not row.user_confirmed and row.file_hash == paper_file.hash]
    for fig in list(plan.create):
        best, best_iou = None, MOVED_MIN_IOU
        for row in movable:
            if row.id in matched or row.page != fig.page or row.assembly != fig.assembly:
                continue
            score = iou(json.loads(row.bbox_page_1000), fig.bbox)
            if score >= best_iou:
                best, best_iou = row, score
        if best is not None:
            plan.create.remove(fig)
            plan.move.append((best, fig))
            matched.add(best.id)

    for row in existing:
        if row.id in matched or row.dismissed:
            continue
        if row.user_confirmed:
            plan.untouched_by_rule += 1
        else:
            # Includes figures of an earlier edition of the PDF: a changed hash
            # means the boxes point into a document that is no longer this one.
            plan.dismiss.append(row)
    return plan


def _update(row: Figure, fig: figures.AssembledFigure, now) -> None:
    for name, value in _hints(fig).items():
        setattr(row, name, value)
    if row.linked_at is None:
        # Once the linking stage has named a figure, its name is the model's
        # reading of the page, not this rule's guess.
        row.name = fig.name_hint
    row.dismissed = False
    row.dismissed_by = ''
    row.assembled_at = now


def apply_plan(plan: StorePlan) -> None:
    """Write a plan in one transaction."""
    pf = plan.paper_file
    now = datetime.datetime.now()
    with db.atomic():
        for fig in plan.create:
            Figure.create(
                paper=pf.paper_id, paper_file=pf.id, file_hash=pf.hash, page=fig.page,
                bbox_page_1000=json.dumps(list(fig.bbox)), assembly=fig.assembly,
                name=fig.name_hint, assembled_at=now, **_hints(fig))
        for row, fig in plan.refresh + plan.restore:
            _update(row, fig, now)
            row.save()
        for row, fig in plan.move:
            _update(row, fig, now)
            # A new box is a new panel input: `panel_key` includes the box, so
            # panels cut from the old one become stale by themselves.
            row.bbox_page_1000 = json.dumps(list(fig.bbox))
            row.save()
        for row in plan.dismiss:
            row.dismissed = True
            row.dismissed_by = REASSEMBLY
            row.save()


def figures_for_paper(paper_id: int) -> list[Figure]:
    """A paper's figures in reading order, without folded ones."""
    return list(Figure.select()
                .where((Figure.paper == paper_id) & (Figure.dismissed == False))  # noqa: E712 (peewee)
                .order_by(Figure.page, Figure.id))
