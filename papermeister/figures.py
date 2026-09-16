"""Turning OCR blocks into figures — stage one of P16.

Chandra2 marks every picture on a page as its own block, and a block is not a
figure. On an ordinary page one picture block usually is one figure. The pages
where it is not are where the work is, and fsis2026 has catalogued them from a
live library (`docs/figure_edge_cases.md` there):

- A **plate page**. The OCR cuts the plate into a block per photograph, while a
  plate is one printed page with one explanation covering all of it. fsis built
  figure rows block by block and paid for it — the caption for seven specimens
  attached to one photo, the panel splitter answering "one panel", and a width
  filter meant for logos throwing away 766 of 1,198 plate photographs (fsis P41).
  Its number is not always printed where a rule looks: the running line may be
  labelled body text, the first plate may have no header, a one-plate paper may
  print a bare "PLATE", or the only clue is "Explanation of Plate 3" at the foot
  of the page before.
- A **captioned plate page** — a `PLATE 2` header over photographs that each
  carry their own "Fig. 1", "Fig. 2". Each photograph is a figure, named
  `Plate 2, Fig. 1` (without the plate the names repeat on every plate), and its
  caption is already there: the linking stage must not pour the plate's other
  captions into it (fsis ref 2360).
- A **figure the OCR cut into pieces** — four vertebra photographs lettered A–D
  over one "Figure 2", a grid of zircon images over one "그림 3-1-22". In a
  200-paper sample of this library that was 146 picture blocks making 46
  figures; assembled separately, each piece takes a sub-label as its caption.

Merged figures keep their blocks: for a cut-up figure they are panel boxes the
OCR has already found.

Nothing here calls a model or touches the database. It decides what a figure
is, in one place, so that assembly, re-assembly and review agree. fsis had the
same judgement living in two code paths twice in one round, and each time the
second path quietly undid the first. When a case is ambiguous — two plate
numbers in one scheme, a piece two captions both claim — nothing is merged:
a wrong merge costs more to undo than a missed one.

The caption found for a figure is a *hint*. The caption stage receives it and
decides; a rule and a model each writing captions is the other thing fsis
learned not to do.
"""
import html as html_mod
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

from . import ocr_layout

#: Blocks whose text can say which plate a page is. Body text is not among them:
#: "see Pl. 3" inside a paragraph names a plate without being on it.
MARK_LABELS = frozenset({'Page-Header', 'Section-Header', 'Caption'})
#: For captioned plate pages only headers count: their captions cross-cite other
#: plates ("arrow B in Figure 1 of Plate 1", fsis ref 2360).
HEADER_LABELS = frozenset({'Page-Header', 'Section-Header'})
#: Blocks that, lying between a picture and a caption in the same column, show
#: that the caption belongs to something else.
BODY_LABELS = frozenset({'Text', 'Section-Header', 'Table', 'Equation-Block',
                         'List-Group', 'Code-Block', 'Form'})
_NOT_LOOSE_TEXT = frozenset({'Page-Header', 'Page-Footer'})

# How a figure was put together.
SINGLE = 'single'
PLATE_UNION = 'plate_page_union'
CAPTION_GROUP = 'caption_group_union'

# What kind of page a figure is on.
BODY = 'body'
PLATE_KIND = 'plate'
CAPTIONED_PLATE = 'captioned_plate'

# Verdicts for a page that has pictures on it.
PLATE = 'plate'
FEW_PICTURES = 'few_pictures'      # one picture without exactly one plate number
NO_MARK = 'no_mark'                # no plate number in a header, heading or caption
MANY_MARKS = 'many_marks'          # two plate numbers: possibly two plates on one page
TEXT_FIGURE = 'text_figure'        # a picture carries a "Fig. N" caption: a body figure page
DUP_NUMBER = 'dup_number'          # a one-photo page whose plate number another page also has

# Why a picture block was left out.
TINY = 'tiny'
CHROME = 'chrome'

#: Stand-alone pictures smaller than this share of the page are dropped (0.4% of
#: the 1000 x 1000 page). Plate photographs and the pieces of a cut-up figure are
#: exempt: they are small by nature, which is exactly what fsis's filter got wrong.
TINY_AREA = 4_000
#: A small picture is still a figure when its own numbered caption sits right
#: under it — Billings 1865's woodcuts, Kobayashi 1935's text-figures, a 1 mm
#: protaspis (Westergård 1936 Fig. 10) are all under TINY_AREA. But a caption
#: also sits under specks: scale bars and stray marks at a plate's foot, 22 x 12
#: permille. The shortest side tells them apart (whole cache: 34 real figures
#: with a side of 25 or more, 70 specks under it).
SMALL_FIGURE_MIN_SIDE = 25
SMALL_FIGURE_MIN_AREA = 1_000
#: In the running-head and running-foot bands, anything smaller than this is a
#: journal logo or ornament, on any page — including plate pages, where letting a
#: header logo into the union would stretch the plate up into the page chrome.
CHROME_BAND = 80
CHROME_AREA = 30_000

#: How far below a figure its caption may begin, in permille of page height.
CAPTION_GAP = 150
#: A caption box may start this far above the picture's bottom edge and still
#: be under it: the OCR's boxes overlap by a few permille on tight layouts.
CAPTION_OVERLAP = 20
#: A figure caption this close above a picture is that picture's own caption.
CAPTION_ABOVE_GAP = 40
#: A caption is a picture's own only if it covers this share of the narrower of the two.
MIN_CAPTION_SHARE = 0.5
#: Pieces of one figure: vertical gap, wider when a panel label sits in it
#: (fsis ref 3856: `A. Photograph` between photo and sketch, gaps 84–128).
PIECE_GAP = 80
PIECE_GAP_WITH_LABEL = 160
MIN_PIECE_SHARE = 0.7
#: A caption this short without a figure number is a label — `A. Photograph`,
#: `(B) Sketch`, `8.1 246 Ma` — not a figure's caption.
LABEL_MAX_CHARS = 60
#: How far outside a cut-up figure's pictures a label's centre may sit.
LABEL_REACH = 25

#: A "plate number" above this is a misread, not a plate.
MAX_PLATE = 300

#: A plate page's running line the OCR labelled as body text: short, one line,
#: at the top or bottom edge, no figure citation (fsis ref 2407 · 3817 · 2263).
RUNNING_LINE_MAX_CHARS = 160
RUNNING_LINE_MAX_HEIGHT = 45
RUNNING_LINE_TOP = 160
RUNNING_LINE_BOTTOM = 880
#: Inferring an unprinted plate number needs a page of photographs with little else:
#: photo numbers only (after an explanation page), or a running head (before a plate).
PREVIOUS_EXPLANATION_MAX_TEXT = 40
NEXT_PLATE_MAX_TEXT = 160
#: When two pages claim a plate number and one has a single photograph, that page
#: is the plate only if its photograph is this many times larger (fsis ref 4051:
#: the explanation page's thumbnail 0.07, the plate 0.48).
DOMINANT_AREA_RATIO = 3

_ROMAN = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}

# The keyword is case-insensitive; the numeral is not. Printed plate numerals are
# capitals, and letting them match lowercase reads "Plate mix" as plate 1009.
# `pl` needs a period or a space before the numeral — "PLM" (polarized light
# microscopy) read as Plate M in fsis ref 2648.
_PLATE_NO = re.compile(
    r'(?i:\b(pl\.|pl(?=\s)|plates?|planche|tafel|taf\.|табл(?:ица)?\.?)|(도판|圖版|図版|图版))'
    r'\s*\.?\s*([IVXLCDM]+|\d{1,3})\b')
#: Numbering schemes, so that a journal's "Tafel 13" beside the author's "Plate 2"
#: reads as one plate numbered twice rather than as two plates.
_SCHEME = {'pl': 'plate', 'plate': 'plate', 'plates': 'plate', 'planche': 'planche',
           'tafel': 'tafel', 'taf': 'tafel'}
_BARE_PLATE = re.compile(r'^\s*(plates?|planche|tafel|도판|圖版|図版|图版)\s*\.?\s*$', re.I)
_EXPLANATION_TITLE = re.compile(
    r'(?i:\bexplanation\s+of\s+(?:the\s+)?plates?)\s*\.?\s*([IVXLCDM]+|\d{1,3})\b'
    r'|(?:도판|圖版|図版|图版)\s*([IVXLCDM]+|\d{1,3})\s*(?:설명|說明|説明|说明)')
_CITES_FIGURE = re.compile(r'\bfig|그림', re.I)

_FIG_WORD = (r'(?:text[-\s]?fig(?:ure)?s?|fig(?:ure)?s?|abb(?:ildung)?|рис(?:унок)?'
             r'|그림|圖|図|图)')
_PHOTO_WORD = r'(?:photo(?:graph)?s?|사진|写真|照片)'
#: A figure caption — what makes a page with pictures a body figure page.
_FIG_CAPTION = re.compile(r'^\s*' + _FIG_WORD + r'\s*\.?\s*\d', re.I)
#: Any numbered caption that can own pictures. `Photo 1` and `사진 9` own pictures
#: too (fsis ref 2162 · 3716) but do not make a plate page a body page.
_NUMBERED_CAPTION = re.compile(r'^\s*(?:' + _FIG_WORD + '|' + _PHOTO_WORD + r')\s*\.?\s*\d', re.I)
_FIG_NAME = re.compile(
    r'^\s*((?:' + _FIG_WORD + '|' + _PHOTO_WORD + r')\s*\.?\s*\d+(?:[-.]\d+)*[a-zA-Z]?)', re.I)
_FIG_NUMBER = re.compile(r'^\s*' + _FIG_WORD + r'\s*\.?\s*(\d+[a-zA-Z]?)', re.I)

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
    label_hints: tuple[str, ...] = ()   # labels printed among the pieces of a cut-up figure
    page_kind: str = BODY               # BODY | PLATE_KIND | CAPTIONED_PLATE
    plate_inferred: bool = False        # the plate number is not printed on this page


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

    @property
    def is_numbered_caption(self) -> bool:
        return self.label == 'Caption' and bool(_NUMBERED_CAPTION.search(self.text))

    @property
    def is_label_caption(self) -> bool:
        return (self.label == 'Caption' and len(self.text) <= LABEL_MAX_CHARS
                and not _NUMBERED_CAPTION.search(self.text))


@dataclass(frozen=True)
class PlateMark:
    number: int
    token: str                          # the numeral as printed; '' for a bare "PLATE"
    name: str                           # 'Plate IV', 'Plate', '도판'
    inferred: bool = False


@dataclass
class PageFacts:
    """What one page says about itself, before other pages are consulted."""

    page: int
    regs: list[Region] = field(default_factory=list)
    pictures: list[Region] = field(default_factory=list)
    verdict: str = ''
    mark: PlateMark | None = None
    printed: set[int] = field(default_factory=set)     # plate numbers in this page's marks
    loose_chars: int = 0                                # text outside running heads and pictures
    explained: set[tuple[int, str]] = field(default_factory=set)
    bare_name: str = ''
    fig_captioned: bool = False


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


def _roman(number: int) -> str:
    out = ''
    for value, digits in ((1000, 'M'), (900, 'CM'), (500, 'D'), (400, 'CD'), (100, 'C'), (90, 'XC'),
                          (50, 'L'), (40, 'XL'), (10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')):
        while number >= value:
            out += digits
            number -= value
    return out


def _numeral(token: str) -> int | None:
    return int(token) if token.isdigit() else roman_number(token)


def block_text(block: ocr_layout.Block | None) -> str:
    if block is None:
        return ''
    return _SPACE.sub(' ', html_mod.unescape(_TAG.sub(' ', block.html))).strip()


def regions(blocks: list[ocr_layout.Block]) -> list[Region]:
    """The blocks that can be placed on the page; a block without a box cannot."""
    return [Region(b.label, b.bbox, block_text(b)) for b in blocks if b.bbox is not None]


# ── plate numbers ────────────────────────────────────────────────────

def is_running_line(reg: Region) -> bool:
    """A plate page's running line that the OCR labelled as body text."""
    if reg.label != 'Text' or len(reg.text) > RUNNING_LINE_MAX_CHARS:
        return False
    if reg.box[3] - reg.box[1] > RUNNING_LINE_MAX_HEIGHT:
        return False
    if not (reg.box[1] <= RUNNING_LINE_TOP or reg.box[3] >= RUNNING_LINE_BOTTOM):
        return False
    return bool(_PLATE_NO.search(reg.text)) and not _CITES_FIGURE.search(reg.text)


def _scheme(m: re.Match) -> str:
    if m.group(2):
        return 'cjk'
    word = m.group(1).lower().rstrip('.')
    return 'табл' if word.startswith('табл') else _SCHEME[word]


def _plate_hits(regs: Iterable[Region], labels: frozenset[str],
                citing_captions: bool = True) -> list[tuple[int, str, str]]:
    """(number, numeral as printed, numbering scheme) for each distinct plate mark.

    `citing_captions=False` ignores captions that also cite a figure — "… (Pl. II,
    fig. 2)" under a photograph names where something else is figured.
    """
    hits: list[tuple[int, str, str]] = []
    seen = set()
    for reg in regs:
        if reg.label not in labels and not is_running_line(reg):
            continue
        if not citing_captions and reg.label == 'Caption' and _CITES_FIGURE.search(reg.text):
            continue
        for m in _PLATE_NO.finditer(reg.text):
            token = m.group(3)
            number = _numeral(token)
            key = (number, _scheme(m))
            if number and number <= MAX_PLATE and key not in seen:
                seen.add(key)
                hits.append((number, token, key[1]))
    return hits


def plate_marks(blocks: list[ocr_layout.Block]) -> dict[int, str]:
    """{plate number: numeral as printed}, from headers, headings, captions and running lines."""
    marks: dict[int, str] = {}
    for number, token, _scheme_name in _plate_hits(regions(blocks), MARK_LABELS):
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


def _explanation_titles(regs: list[Region]) -> set[tuple[int, str]]:
    out = set()
    for reg in regs:
        for m in _EXPLANATION_TITLE.finditer(reg.text):
            token = m.group(1) or m.group(2)
            number = _numeral(token)
            if number and number <= MAX_PLATE:
                out.add((number, token))
    return out


def _bare_plate_name(regs: list[Region]) -> str:
    for reg in regs:
        if reg.label in MARK_LABELS:
            m = _BARE_PLATE.match(reg.text)
            if m:
                word = m.group(1)
                return word if not word.isascii() else 'Plate'
    return ''


# ── geometry ─────────────────────────────────────────────────────────

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


def _v_overlap(a: Box, b: Box) -> int:
    return min(a[3], b[3]) - max(a[1], b[1])


def _share(a: Box, b: Box) -> float:
    """Horizontal overlap as a share of the narrower box."""
    return max(0, _overlap(a, b)) / max(1, min(a[2] - a[0], b[2] - b[0]))


def _area(box: Box) -> int:
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def _centre_inside(box: Box, area: Box) -> bool:
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return area[0] <= cx <= area[2] and area[1] <= cy <= area[3]


def _union(boxes: Iterable[Box]) -> Box:
    boxes = list(boxes)
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


# ── captions ─────────────────────────────────────────────────────────

def _owned_elsewhere(box: Box, caption: Region, pictures: list[Region]) -> bool:
    """A caption just under this picture that another picture, directly above it
    and covering more of it, has a better claim to (fsis ref 2100 p.10: the right
    column's figure took the left column's `Fig. 5`)."""
    mine = _share(box, caption.box)
    return any(p.box != box and p.box[3] <= caption.box[1] + 5
               and caption.box[1] - p.box[3] < CAPTION_GAP and _share(p.box, caption.box) > mine
               for p in pictures)


def _nearest_caption_below(box: Box, captions: list[Region], pictures: list[Region],
                           lenient: bool = False) -> Region | None:
    """`lenient` lets a numbered caption overlap the picture by CAPTION_OVERLAP.

    That is for finding a figure's own caption once the page is judged. The
    page judgement itself stays strict: on a plate page the photographs' labels
    overlap the photographs, and a lenient reading turns the plate into a body
    page of 23 unnamed figures (Hughes et al. 1975 p.32).
    """
    best: Region | None = None
    for cap in captions:
        top = cap.box[1]
        overlap = CAPTION_OVERLAP if lenient and cap.is_numbered_caption else 5
        if top < box[3] - overlap or top - box[3] >= CAPTION_GAP or _overlap(box, cap.box) <= 0:
            continue
        if _owned_elsewhere(box, cap, pictures):
            continue
        if best is None or top < best.box[1]:
            best = cap
    return best


def caption_below(box: Box, regs: list[Region], lenient: bool = False) -> Region | None:
    """The nearest Caption starting just under this region, in its column."""
    return _nearest_caption_below(box, [r for r in regs if r.label == 'Caption'],
                                  [r for r in regs if r.is_picture], lenient)


def _own_numbered_caption(box: Box, regs: list[Region], pictures: list[Region]) -> Region | None:
    """The numbered caption right under this picture, looking past labels like `B. Sketch`."""
    near = [r for r in regs if r.label == 'Caption' and not r.is_label_caption
            and _share(box, r.box) >= MIN_CAPTION_SHARE]
    cap = _nearest_caption_below(box, near, pictures, lenient=True)
    return cap if cap is not None and cap.is_numbered_caption else None


def small_captioned_figure(box: Box, regs: list[Region], pictures: list[Region]) -> bool:
    """A picture under TINY_AREA that is a figure all the same: its own numbered
    caption is right under it and it is not a speck."""
    x0, y0, x1, y1 = box
    if min(x1 - x0, y1 - y0) < SMALL_FIGURE_MIN_SIDE or (x1 - x0) * (y1 - y0) < SMALL_FIGURE_MIN_AREA:
        return False
    return _own_numbered_caption(box, regs, pictures) is not None


def _name_from_caption(caption: str) -> str:
    m = _FIG_NAME.match(caption or '')
    return _SPACE.sub(' ', m.group(1)) if m else ''


def looks_compound(caption: str) -> bool:
    """Whether a caption appears to describe several panels. Sizing only."""
    if not caption:
        return False
    labels = {m.group(1).lower() for m in _PAREN_LABEL.finditer(caption)}
    if len(labels) >= 2:
        return True
    return bool(_LETTER_RANGE.search(caption) or _FIG_RANGE.search(caption))


# ── cut-up figures ───────────────────────────────────────────────────

def _caption_above(box: Box, numbered: list[Region]) -> bool:
    return any(c.box[3] <= box[1] + 5 and box[1] - c.box[3] < CAPTION_ABOVE_GAP and _overlap(box, c.box) > 0
               for c in numbered)


def _side_captioned(box: Box, numbered: list[Region]) -> bool:
    """A numbered caption level with this picture and beside it: a separate figure (fsis ref 2378)."""
    return any(_v_overlap(box, c.box) > 0 and (c.box[0] >= box[2] - 5 or c.box[2] <= box[0] + 5)
               for c in numbered)


def _in_gap(reg: Region, upper: Box, lower: Box) -> bool:
    return upper[3] - 5 <= reg.box[1] <= lower[1] + 5 and _overlap(upper, reg.box) > 0


def _gap_limit(upper: Box, lower: Box, labels: list[Region]) -> int:
    return PIECE_GAP_WITH_LABEL if any(_in_gap(r, upper, lower) for r in labels) else PIECE_GAP


def _blocked(upper: Box, lower: Box, regs: list[Region]) -> bool:
    """Something between two pictures that makes them two figures: a caption that
    is not a label, or body text."""
    for reg in regs:
        if reg.label == 'Caption' and not reg.is_label_caption and _in_gap(reg, upper, lower):
            return True
        if (reg.label in BODY_LABELS and reg.box[1] >= upper[3] - 5
                and reg.box[3] <= lower[1] + 5 and _overlap(upper, reg.box) > 0):
            return True
    return False


def _caption_groups(candidates: list[Region], regs: list[Region]) -> dict[Region, list[Region]]:
    """Numbered captions that own two or more pictures.

    A caption owns the pictures it sits right under, then the uncaptioned pieces
    stacked above them or level beside them. A piece two captions both reach is
    ambiguous, and then neither caption merges anything — otherwise the two
    merges fold each other's rows (fsis ref 2117 · 3281).
    """
    pictures = [r for r in regs if r.is_picture]
    numbered = [r for r in regs if r.is_numbered_caption]
    labels = [r for r in regs if r.is_label_caption]
    owner = {p: _own_numbered_caption(p.box, regs, pictures) for p in candidates}

    groups: dict[Region, list[Region]] = {}
    for cap in numbered:
        members = [p for p in candidates if owner[p] is cap]
        if not members:
            continue
        changed = True
        while changed:
            changed = False
            top = min(m.box[1] for m in members)
            for piece in candidates:
                if piece in members or owner[piece] is not None:
                    continue
                if _side_captioned(piece.box, numbered) or _caption_above(piece.box, numbered):
                    continue
                below = [m for m in members
                         if 0 <= m.box[1] - piece.box[3] <= _gap_limit(piece.box, m.box, labels)
                         and _share(piece.box, m.box) >= MIN_PIECE_SHARE]
                beside = [m for m in members
                          if _v_overlap(piece.box, m.box) > 0.5 * (piece.box[3] - piece.box[1])
                          and piece.box[1] >= top - 5 and _overlap(piece.box, cap.box) > 0]
                if not below and not beside:
                    continue
                if below and _blocked(piece.box, below[0].box, regs):
                    continue
                members.append(piece)
                changed = True
        if len(members) >= 2:
            groups[cap] = members

    claims = Counter(p for members in groups.values() for p in members)
    return {cap: members for cap, members in groups.items() if all(claims[p] == 1 for p in members)}


def _caption_group(page: int, members: list[Region], owner: Region,
                   regs: list[Region]) -> AssembledFigure:
    """One figure from the pieces over a caption, with the labels printed among them."""
    x0, y0, x1, y1 = _union(m.box for m in members)
    reach = (x0 - LABEL_REACH, y0 - LABEL_REACH, x1 + LABEL_REACH, y1 + LABEL_REACH)
    labels = sorted((r for r in regs if r.is_label_caption and _centre_inside(r.box, reach)),
                    key=lambda r: (r.box[1], r.box[0]))
    return AssembledFigure(
        page=page, bbox=_union([m.box for m in members] + [r.box for r in labels]),
        blocks=tuple(m.box for m in members), assembly=CAPTION_GROUP,
        name_hint=_name_from_caption(owner.text), caption_hint=owner.text,
        label_hints=tuple(r.text for r in labels))


# ── captioned plate pages ────────────────────────────────────────────

def _captioned_plate(facts: PageFacts, candidates: list[Region]):
    """(plate number, token, {picture: figure number}) when this is a captioned plate page."""
    mark = one_plate(_plate_hits(facts.regs, HEADER_LABELS))
    if mark is None:
        return None
    numbers = {}
    for picture in candidates:
        caption = caption_below(picture.box, facts.regs)
        m = _FIG_NUMBER.match(caption.text) if caption is not None else None
        if m:
            numbers[picture] = m.group(1)
    if len(numbers) < 2 or len({n.lower() for n in numbers.values()}) != len(numbers):
        return None      # repeated figure numbers: not one plate's own sequence
    return mark[0], mark[1], numbers


# ── pages and documents ──────────────────────────────────────────────

def read_page(page: int, text: str) -> PageFacts:
    """What a page says about its own figures, without looking at other pages."""
    facts = PageFacts(page=page)
    if not ocr_layout.is_structured(text):
        return facts
    regs = regions(ocr_layout.parse_blocks(text))
    facts.regs = regs
    facts.pictures = [r for r in regs if r.is_picture]
    hits = _plate_hits(regs, MARK_LABELS)
    facts.printed = {number for number, _, _ in hits}
    facts.loose_chars = sum(len(r.text) for r in regs
                            if r.label not in _NOT_LOOSE_TEXT and not r.is_picture)
    facts.explained = _explanation_titles(regs)
    facts.bare_name = _bare_plate_name(regs)
    facts.fig_captioned = any(
        (cap := caption_below(p.box, regs)) is not None and cap.is_figure_caption
        for p in facts.pictures)
    if not facts.pictures:
        return facts

    if len(facts.pictures) == 1:
        # One photograph is weak evidence of a plate; a citation in its caption is
        # none (Šnajdr 1981 p.5: a pygidium on a text page, "… (Pl. II, fig. 2)").
        hits = _plate_hits(regs, MARK_LABELS, citing_captions=False)
    mark = one_plate(hits)
    if len(facts.pictures) == 1 and mark is None:
        facts.verdict = FEW_PICTURES
    elif not hits:
        facts.verdict = NO_MARK
    elif mark is None:
        facts.verdict = MANY_MARKS
    elif facts.fig_captioned:
        facts.verdict = TEXT_FIGURE
    else:
        facts.verdict = PLATE
        facts.mark = PlateMark(mark[0], mark[1], f'Plate {mark[1]}')
    return facts


def _infer_from_previous(facts: PageFacts, previous: PageFacts | None, taken: set[int]) -> PlateMark | None:
    """Photographs after a page ending in "Explanation of Plate N" (fsis ref 3359)."""
    if previous is None or facts.loose_chars > PREVIOUS_EXPLANATION_MAX_TEXT:
        return None
    if len({number for number, _ in previous.explained}) != 1:
        return None
    number, token = next(iter(previous.explained))
    if number in taken:
        return None
    return PlateMark(number, token, f'Plate {token}', inferred=True)


def _infer_from_next(facts: PageFacts, following: PageFacts | None, taken: set[int]) -> PlateMark | None:
    """Photographs before a printed `PLATE N`: the first plate without its header (fsis ref 2100)."""
    if (following is None or following.verdict != PLATE or following.mark is None
            or following.mark.inferred or len(following.pictures) < 2 or following.mark.number < 2):
        return None
    number = following.mark.number - 1
    if number in taken or len(facts.pictures) < 2 or facts.loose_chars > NEXT_PLATE_MAX_TEXT:
        return None
    token = str(number) if following.mark.token.isdigit() else _roman(number)
    return PlateMark(number, token, f'Plate {token}', inferred=True)


def _decide_plates(pages: list[PageFacts]) -> None:
    """The plate decisions one page cannot make alone."""
    by_page = {f.page: f for f in pages}

    # A one-photo page's number is weak evidence: an OCR misread can give it the
    # number of another page (fsis ref 3011: Pl. XLI read as Pl. XII).
    claims: dict[int, list[PageFacts]] = {}
    for f in pages:
        if f.verdict == PLATE and f.mark is not None:
            claims.setdefault(f.mark.number, []).append(f)
    for f in pages:
        if f.verdict != PLATE or f.mark is None or len(f.pictures) != 1 or len(claims[f.mark.number]) < 2:
            continue
        if (f.loose_chars <= NEXT_PLATE_MAX_TEXT
                and all(abs(o.page - f.page) == 1 for o in claims[f.mark.number] if o is not f)):
            # One plate over facing pages — "Tafel 16: 1" and "Tafel 16: 2" (Henningsmoen
            # et al., this library). A misread number lands far away; an explanation
            # page beside its plate has text, which this page does not.
            continue
        mine = _area(f.pictures[0].box)
        others = [_area(_union(p.box for p in o.pictures)) for o in claims[f.mark.number] if o is not f]
        if not all(mine >= DOMINANT_AREA_RATIO * area for area in others):
            f.verdict, f.mark = DUP_NUMBER, None

    marked = {f.mark.number for f in pages if f.verdict == PLATE and f.mark is not None}
    numbered_anywhere = bool(marked) or any(f.printed for f in pages)
    # A number printed on a page with pictures belongs to that page even if it
    # became a body figure page (fsis ref 3075 p.102).
    image_marked = {n for f in pages if f.pictures for n in f.printed}
    for f in pages:
        if f.verdict != NO_MARK or f.fig_captioned:
            continue
        mark = (_infer_from_previous(f, by_page.get(f.page - 1), marked)
                or _infer_from_next(f, by_page.get(f.page + 1), marked | image_marked))
        if mark is None and not numbered_anywhere and f.bare_name:
            mark = PlateMark(1, '', f.bare_name, inferred=True)
        if mark is not None:
            f.verdict, f.mark = PLATE, mark
            marked.add(mark.number)

    # A bare "PLATE" names the plate only if the paper has one such page.
    bare = [f for f in pages if f.verdict == PLATE and f.mark is not None and not f.mark.token]
    if len(bare) > 1:
        for f in bare:
            f.verdict, f.mark = NO_MARK, None


def _drop(result: PageAssembly, why: str) -> None:
    result.dropped[why] = result.dropped.get(why, 0) + 1


def _build(facts: PageFacts) -> PageAssembly:
    result = PageAssembly(page=facts.page, picture_blocks=len(facts.pictures), verdict=facts.verdict)
    if not facts.pictures:
        return result

    if facts.verdict == PLATE and facts.mark is not None:
        kept = []
        for picture in facts.pictures:
            why = decoration(picture.box, small_ok=len(facts.pictures) > 1)
            if why:
                _drop(result, why)
            else:
                kept.append(picture)
        if kept:
            union = _union(p.box for p in kept)
            caption = caption_below(union, facts.regs, lenient=True)
            result.figures.append(AssembledFigure(
                page=facts.page, bbox=union, blocks=tuple(p.box for p in kept),
                assembly=PLATE_UNION if len(kept) > 1 else SINGLE,
                plate=facts.mark.number, name_hint=facts.mark.name,
                caption_hint=caption.text if caption else '',
                page_kind=PLATE_KIND, plate_inferred=facts.mark.inferred))
        return result

    candidates = []
    for picture in facts.pictures:
        if decoration(picture.box, small_ok=True) == CHROME:
            _drop(result, CHROME)
        else:
            candidates.append(picture)

    captioned = _captioned_plate(facts, candidates)
    groups = {} if captioned else _caption_groups(candidates, facts.regs)
    member_of = {p: cap for cap, members in groups.items() for p in members}
    emitted: set[Region] = set()
    for picture in candidates:
        cap = member_of.get(picture)
        if cap is not None:
            if cap not in emitted:
                emitted.add(cap)
                result.figures.append(_caption_group(facts.page, groups[cap], cap, facts.regs))
            continue
        if decoration(picture.box, small_ok=False) and not small_captioned_figure(
                picture.box, facts.regs, candidates):
            _drop(result, TINY)
            continue
        caption = caption_below(picture.box, facts.regs, lenient=True)
        caption_text = caption.text if caption else ''
        if captioned and picture in captioned[2]:
            number, token, numbers = captioned
            result.figures.append(AssembledFigure(
                page=facts.page, bbox=picture.box, blocks=(picture.box,), assembly=SINGLE,
                plate=number, name_hint=f'Plate {token}, Fig. {numbers[picture]}',
                caption_hint=caption_text, page_kind=CAPTIONED_PLATE))
            continue
        result.figures.append(AssembledFigure(
            page=facts.page, bbox=picture.box, blocks=(picture.box,), assembly=SINGLE,
            name_hint=_name_from_caption(caption_text), caption_hint=caption_text))
    return result


def assemble_page(page: int, text: str) -> PageAssembly:
    """The figures on one OCR page, judged from that page alone."""
    return _build(read_page(page, text))


def assemble_document(pages: list[str]) -> list[PageAssembly]:
    """Every page of one paper, in page order (0-based, as in the OCR cache).

    Some plate decisions need the neighbouring pages — an unprinted number, a
    number two pages claim — so a paper is assembled as a whole.
    """
    facts = [read_page(index, text or '') for index, text in enumerate(pages)]
    _decide_plates(facts)
    return [_build(f) for f in facts]
