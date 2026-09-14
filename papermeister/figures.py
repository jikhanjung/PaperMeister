"""Turning OCR blocks into figures — stage one of P16.

Chandra2 marks every picture on a page as its own block, and a block is not a
figure. On an ordinary page one picture block usually is one figure. Two kinds
of page break that:

- A **plate page**. The OCR cuts the plate into a block per photograph, while a
  plate is one printed page with one explanation covering all of it. fsis2026
  built its figure rows block by block and paid for it — the caption for seven
  specimens got attached to the region of one photo, the panel splitter answered
  "one panel", and a width filter meant for logos threw away 766 of 1,198 plate
  photographs (fsis P41).
- A **figure the OCR cut into pieces** — four vertebra photographs lettered A–D
  over one "Figure 2" caption, a grid of zircon images over one "그림 3-1-22".
  In a 200-paper sample of this library that was 146 picture blocks making 46
  figures. fsis never met it at this scale; here, assembling them as separate
  figures would hand each piece a sub-label ("L Caradoc") as its caption.

So both are recognised first and merged, and the merged figure keeps its
blocks: for a cut-up figure they are panel boxes the OCR has already found.

Nothing here calls a model or touches the database. It decides what a figure
is, in one place, so that assembly, re-assembly and review agree. fsis had the
same judgement living in two code paths twice in one round, and each time the
second path quietly undid the first.

The caption found for a figure is a *hint*. The caption stage receives it and
decides; a rule and a model each writing captions is the other thing fsis
learned not to do.
"""
import html as html_mod
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from . import ocr_layout

#: Blocks whose text can say which plate a page is. Body text is not among them:
#: "see Pl. 3" inside a paragraph names a plate without being on it.
MARK_LABELS = frozenset({'Page-Header', 'Section-Header', 'Caption'})

#: Blocks that, lying between a picture and a caption in the same column, show
#: that the caption belongs to something else.
BODY_LABELS = frozenset({'Text', 'Section-Header', 'Table', 'Equation-Block',
                         'List-Group', 'Code-Block', 'Form'})

# How a figure was put together.
SINGLE = 'single'
PLATE_UNION = 'plate_page_union'
CAPTION_GROUP = 'caption_group_union'

# Verdicts for a page that has pictures on it.
PLATE = 'plate'
FEW_PICTURES = 'few_pictures'      # fewer than two picture blocks
NO_MARK = 'no_mark'                # no plate number in a header, heading or caption
MANY_MARKS = 'many_marks'          # two plate numbers: possibly two plates on one page
TEXT_FIGURE = 'text_figure'        # a picture carries a "Fig. N" caption: a body figure page

# Why a picture block was left out.
TINY = 'tiny'
CHROME = 'chrome'

#: Stand-alone pictures smaller than this share of the page are dropped (0.4% of
#: the 1000 x 1000 page). Plate photographs and the pieces of a cut-up figure are
#: exempt: they are small by nature, which is exactly what fsis's filter got wrong.
TINY_AREA = 4_000
#: In the running-head and running-foot bands, anything smaller than this is a
#: journal logo or ornament, on any page — including plate pages, where letting a
#: header logo into the union would stretch the plate up into the page chrome.
CHROME_BAND = 80
CHROME_AREA = 30_000

#: How far below a lone figure its caption may begin, in permille of page height.
CAPTION_GAP = 150
#: A figure caption this close above a picture is that picture's own caption.
CAPTION_ABOVE_GAP = 40
#: A caption owns a picture only if it spans at least this share of the picture's
#: width — otherwise it is the caption of the neighbouring column.
COLUMN_OVERLAP = 0.5
#: How far outside a cut-up figure's pictures a panel label's centre may sit.
#: Labels are printed beside the pieces and often run wider than them.
LABEL_REACH = 25

#: A "plate number" above this is a misread, not a plate.
MAX_PLATE = 300

_ROMAN = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}

# The keyword is case-insensitive; the numeral is not. Printed plate numerals are
# capitals, and letting them match lowercase reads "Plate mix" as plate 1009.
# German Tafel and Russian Таблица sit beside the forms fsis already needed
# (도판 · 圖版 · 図版): this library is heavy on both.
_PLATE_NO = re.compile(
    r'(?i:\b(pl\.?|plates?|planche|tafel|taf\.|табл(?:ица)?\.?)|(도판|圖版|図版|图版))'
    r'\s*\.?\s*([IVXLCDM]+|\d{1,3})\b')
#: Numbering schemes, so that a journal's "Tafel 13" beside the author's "Plate 2"
#: reads as one plate numbered twice rather than as two plates.
_SCHEME = {'pl': 'plate', 'plate': 'plate', 'plates': 'plate', 'planche': 'planche',
           'tafel': 'tafel', 'taf': 'tafel'}

_FIG_WORD = (r'(?:text[-\s]?fig(?:ure)?s?|fig(?:ure)?s?|abb(?:ildung)?|рис(?:унок)?'
             r'|그림|圖|図|图)')
_FIG_CAPTION = re.compile(r'^\s*' + _FIG_WORD + r'\s*\.?\s*\d', re.I)
_FIG_NAME = re.compile(r'^\s*(' + _FIG_WORD + r'\s*\.?\s*\d+(?:[-.]\d+)*[a-zA-Z]?)', re.I)

_TAG = re.compile(r'<[^>]+>')
_SPACE = re.compile(r'\s+')

# Signs that a caption describes more than one panel. An estimate for sizing, not
# a gate: whether a figure is split is decided by the caption stage returning two
# or more entries. Genus abbreviations ("A. gigas") are deliberately not a sign.
_PAREN_LABEL = re.compile(r'\(\s*([a-zA-Z]|\d{1,2})\s*\)')
_LETTER_RANGE = re.compile(r'(?<![A-Za-z-])[A-Za-z]\s*[–—-]\s*[A-Za-z](?![\w-])')
_FIG_RANGE = re.compile(r'\bfigs?\.?\s*\d{1,2}\s*[–—-]\s*\d{1,2}\b', re.I)

Box = tuple[int, int, int, int]


@dataclass(frozen=True)
class AssembledFigure:
    """One figure as assembly sees it. Coordinates are page-relative 0..1000."""

    page: int
    bbox: Box
    blocks: tuple[Box, ...]             # the picture blocks merged into it
    assembly: str                       # SINGLE | PLATE_UNION | CAPTION_GROUP
    plate: int | None = None
    name_hint: str = ''
    caption_hint: str = ''
    label_hints: tuple[str, ...] = ()   # panel labels printed inside a cut-up figure


@dataclass
class PageAssembly:
    """What assembly decided for one page, including what it left out and why."""

    page: int
    picture_blocks: int = 0
    verdict: str = ''                   # set only when the page has pictures
    figures: list[AssembledFigure] = field(default_factory=list)
    dropped: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, eq=False)
class Region:
    """A block that has a place on the page, with its text read once.

    Compared by identity: two identical captions on a page are still two captions.
    """

    label: str
    box: Box
    text: str

    @property
    def is_picture(self) -> bool:
        return self.label in ocr_layout.PICTURE_LABELS

    @property
    def is_figure_caption(self) -> bool:
        return self.label == 'Caption' and bool(_FIG_CAPTION.search(self.text))


def roman_number(token: str) -> int | None:
    """Roman numeral to integer, or None.

    Computed rather than looked up: fsis started with a table of I..XXX and lost
    every plate after the thirtieth in a 44-plate monograph.
    """
    if not token or any(c not in _ROMAN for c in token):
        return None
    total = previous = 0
    for char in reversed(token):
        value = _ROMAN[char]
        total += -value if value < previous else value
        previous = max(previous, value)
    return total or None


def block_text(block: ocr_layout.Block | None) -> str:
    if block is None:
        return ''
    return _SPACE.sub(' ', html_mod.unescape(_TAG.sub(' ', block.html))).strip()


def regions(blocks: list[ocr_layout.Block]) -> list[Region]:
    """The blocks that can be placed on the page; a block without a box cannot."""
    return [Region(b.label, b.bbox, block_text(b)) for b in blocks if b.bbox is not None]


def _scheme(m: re.Match) -> str:
    if m.group(2):
        return 'cjk'
    word = m.group(1).lower().rstrip('.')
    return 'табл' if word.startswith('табл') else _SCHEME[word]


def _plate_hits(labelled: Iterable[tuple[str, str]]) -> list[tuple[int, str, str]]:
    """(number, numeral as printed, numbering scheme) for each distinct plate mark."""
    hits: list[tuple[int, str, str]] = []
    seen = set()
    for label, text in labelled:
        if label not in MARK_LABELS:
            continue
        for m in _PLATE_NO.finditer(text):
            token = m.group(3)
            number = int(token) if token.isdigit() else roman_number(token)
            key = (number, _scheme(m))
            if number and number <= MAX_PLATE and key not in seen:
                seen.add(key)
                hits.append((number, token, key[1]))
    return hits


def plate_marks(blocks: list[ocr_layout.Block]) -> dict[int, str]:
    """{plate number: numeral as printed}, from headers, headings and captions."""
    marks: dict[int, str] = {}
    for number, token, _scheme_name in _plate_hits((b.label, block_text(b)) for b in blocks):
        marks.setdefault(number, token)
    return marks


def one_plate(hits: list[tuple[int, str, str]]) -> tuple[int, str] | None:
    """The plate a page's marks name, or None when they name more than one.

    A page can carry two numbers for one plate: Palaeontographica prints its own
    "Tafel 13" in the running head beside the authors' "Plate 2". Different
    schemes holding one number each are that case. Two numbers in one scheme are
    two plates — "图版 58" and "图版 59" on one atlas page.
    """
    if not hits:
        return None
    if len({number for number, _, _ in hits}) == 1:
        return hits[0][0], hits[0][1]
    by_scheme: dict[str, set[int]] = {}
    for number, _, scheme in hits:
        by_scheme.setdefault(scheme, set()).add(number)
    if any(len(numbers) > 1 for numbers in by_scheme.values()):
        return None
    number, token, _ = next((h for h in hits if h[2] == 'plate'), hits[0])
    return number, token


def decoration(box: Box, small_ok: bool) -> str | None:
    """Why this picture is not a figure, or None if it may be one."""
    x0, y0, x1, y1 = box
    area = (x1 - x0) * (y1 - y0)
    in_band = y1 <= CHROME_BAND or y0 >= ocr_layout.BBOX_SCALE - CHROME_BAND
    if in_band and area < CHROME_AREA:
        return CHROME
    if not small_ok and area < TINY_AREA:
        return TINY
    return None


def _overlap(a: Box, b: Box) -> int:
    return min(a[2], b[2]) - max(a[0], b[0])


def _centre_inside(box: Box, area: Box) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return area[0] <= cx <= area[2] and area[1] <= cy <= area[3]


def caption_below(box: Box, regs: list[Region]) -> Region | None:
    """The nearest Caption starting just under this region, in its column.

    fsis matched on vertical distance alone. Here the caption must also overlap
    the figure horizontally, or a two-column page hands one column's caption to
    the figure in the other.
    """
    best: Region | None = None
    for reg in regs:
        if reg.label != 'Caption' or reg.box[1] < box[3] - 5:
            continue                    # not a caption, or above / overlapping the figure
        if reg.box[1] - box[3] >= CAPTION_GAP or _overlap(box, reg.box) <= 0:
            continue
        if best is None or reg.box[1] < best.box[1]:
            best = reg
    return best


def owning_caption(box: Box, fig_captions: list[Region], regs: list[Region]) -> Region | None:
    """The "Fig. N" caption this picture is a piece of, if any.

    It is the nearest one below the picture in the picture's column, provided no
    body text comes between them and the picture has no figure caption of its
    own sitting directly above it (the caption-above style, where the caption
    below belongs to the next figure down).
    """
    x0, y0, x1, y1 = box
    for caption in fig_captions:
        bottom = caption.box[3]
        if bottom <= y0 + 5 and y0 - bottom < CAPTION_ABOVE_GAP and _overlap(box, caption.box) > 0:
            return None
    below = [c for c in fig_captions
             if c.box[1] >= y1 - 5 and _overlap(box, c.box) >= COLUMN_OVERLAP * (x1 - x0)]
    if not below:
        return None
    owner = min(below, key=lambda c: c.box[1])
    for reg in regs:
        if (reg.label in BODY_LABELS and reg.box[1] >= y1 - 5
                and reg.box[3] <= owner.box[1] + 5 and _overlap(box, reg.box) > 0):
            return None
    return owner


def looks_compound(caption: str) -> bool:
    """Whether a caption appears to describe several panels. Sizing only."""
    if not caption:
        return False
    labels = {m.group(1).lower() for m in _PAREN_LABEL.finditer(caption)}
    if len(labels) >= 2:
        return True
    return bool(_LETTER_RANGE.search(caption) or _FIG_RANGE.search(caption))


def _plate_verdict(pictures: list[Region],
                   regs: list[Region]) -> tuple[str, tuple[int, str] | None]:
    """P41's three conditions, in the order that makes the report readable."""
    if len(pictures) < 2:
        return FEW_PICTURES, None
    hits = _plate_hits((r.label, r.text) for r in regs)
    if not hits:
        return NO_MARK, None
    mark = one_plate(hits)
    if mark is None:
        return MANY_MARKS, None
    for picture in pictures:
        below = caption_below(picture.box, regs)
        if below is not None and below.is_figure_caption:
            return TEXT_FIGURE, mark
    return PLATE, mark


def _union(boxes: Iterable[Box]) -> Box:
    boxes = list(boxes)
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _name_from_caption(caption: str) -> str:
    m = _FIG_NAME.match(caption or '')
    return _SPACE.sub(' ', m.group(1)) if m else ''


def _drop(result: PageAssembly, why: str) -> None:
    result.dropped[why] = result.dropped.get(why, 0) + 1


def _caption_group(page: int, members: list[Region], owner: Region,
                   regs: list[Region]) -> AssembledFigure:
    """One figure from the pieces over a caption, with the labels printed among them."""
    x0, y0, x1, y1 = _union(m.box for m in members)
    reach = (x0 - LABEL_REACH, y0 - LABEL_REACH, x1 + LABEL_REACH, y1 + LABEL_REACH)
    labels = [r for r in regs
              if r.label == 'Caption' and r is not owner and not r.is_figure_caption
              and _centre_inside(r.box, reach)]
    return AssembledFigure(
        page=page, bbox=_union([m.box for m in members] + [r.box for r in labels]),
        blocks=tuple(m.box for m in members), assembly=CAPTION_GROUP,
        name_hint=_name_from_caption(owner.text), caption_hint=owner.text,
        label_hints=tuple(r.text for r in labels))


def assemble_page(page: int, text: str) -> PageAssembly:
    """The figures on one OCR page."""
    result = PageAssembly(page=page)
    if not ocr_layout.is_structured(text):
        return result
    regs = regions(ocr_layout.parse_blocks(text))
    pictures = [r for r in regs if r.is_picture]
    result.picture_blocks = len(pictures)
    if not pictures:
        return result

    verdict, mark = _plate_verdict(pictures, regs)
    result.verdict = verdict

    if verdict == PLATE and mark is not None:
        kept = []
        for picture in pictures:
            why = decoration(picture.box, small_ok=True)
            if why:
                _drop(result, why)
            else:
                kept.append(picture)
        if kept:
            number, token = mark
            union = _union(p.box for p in kept)
            caption = caption_below(union, regs)
            result.figures.append(AssembledFigure(
                page=page, bbox=union, blocks=tuple(p.box for p in kept),
                assembly=PLATE_UNION, plate=number, name_hint=f'Plate {token}',
                caption_hint=caption.text if caption else ''))
        return result

    candidates = []
    for picture in pictures:
        if decoration(picture.box, small_ok=True) == CHROME:
            _drop(result, CHROME)
        else:
            candidates.append(picture)

    fig_captions = [r for r in regs if r.is_figure_caption]
    owners = {p: owning_caption(p.box, fig_captions, regs) for p in candidates}
    members: dict[Region, list[Region]] = {}
    for picture, owner in owners.items():
        if owner is not None:
            members.setdefault(owner, []).append(picture)

    emitted: set[Region] = set()
    for picture in candidates:
        owner = owners[picture]
        if owner is not None and len(members[owner]) >= 2:
            if owner not in emitted:
                emitted.add(owner)
                result.figures.append(_caption_group(page, members[owner], owner, regs))
            continue
        if decoration(picture.box, small_ok=False):
            _drop(result, TINY)
            continue
        caption = caption_below(picture.box, regs)
        caption_text = caption.text if caption else ''
        result.figures.append(AssembledFigure(
            page=page, bbox=picture.box, blocks=(picture.box,), assembly=SINGLE,
            name_hint=_name_from_caption(caption_text), caption_hint=caption_text))
    return result


def assemble_document(pages: list[str]) -> list[PageAssembly]:
    """Every page of one paper, in page order (0-based, as in the OCR cache)."""
    return [assemble_page(index, text or '') for index, text in enumerate(pages)]
