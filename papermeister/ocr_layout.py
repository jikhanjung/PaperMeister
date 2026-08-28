"""Turning an OCR page back into something that reads like the paper.

Chandra2 does not return markdown. It returns HTML in which every block of the
page is a div carrying what the block *is* and where it sat::

    <div data-bbox="107 80 653 487" data-label="Figure">
      <img alt="Geographical overview of Morocco …"/>
    </div>

That is a layout, and the Text tab used to throw it away: the whole page went
to `QTextDocument.setMarkdown`, which renders the div soup as flat prose with
the headings, captions and figures all looking the same. This module reads the
labels instead, so a section header can be a heading, a caption can look like a
caption, and a figure can be the figure.

**Figures are cropped from the PDF, not taken from the OCR.** The model does
not return image data — an `<img>` here has only an `alt` description, and for
some figures Chandra instead emits an HTML *impression* of the drawing (divs
with borders and absolute positioning) that renders as nonsense. The bbox is
the useful part: it says which rectangle of the page to cut out.

Coordinates are normalised to 0..1000 on each axis independently, so mapping
them onto a rendered page is per-axis fractions of that page's own width and
height — confirmed against the live library by cropping and looking.

Not every cached OCR result is in this form; older ones are plain markdown, and
`is_structured` is how a caller tells which document it has.
"""

import html as html_mod
import re
from dataclasses import dataclass

#: Both bbox axes are normalised to this, independently of page proportions.
BBOX_SCALE = 1000

#: Blocks whose content is a picture: the OCR text for these is either a bare
#: alt description or an HTML pastiche of the artwork, so both are dropped in
#: favour of a crop of the page itself.
PICTURE_LABELS = frozenset({'Figure', 'Image', 'Diagram'})

#: Running heads and page numbers. They belong to the page, not to the text,
#: and repeating them every page is what makes a continuous read feel shredded.
CHROME_LABELS = frozenset({'Page-Header', 'Page-Footer'})

#: Labels rendered as a heading, whatever heading level the OCR chose — the
#: model picks h1 for one section and h4 for the next, which reads as random
#: font sizes rather than structure.
HEADING_LABELS = frozenset({'Section-Header', 'Title'})

_BLOCK_TAG = re.compile(r'<div\b[^>]*>|</div>', re.I)
_ATTRS = re.compile(r'data-bbox="([^"]*)"|data-label="([^"]*)"', re.I)
_HEADING_TAG = re.compile(r'</?h[1-6]\b[^>]*>', re.I)
_MATH_TAG = re.compile(r'</?math\b[^>]*>', re.I)


@dataclass(frozen=True)
class Block:
    """One labelled region of a page."""

    label: str
    bbox: tuple[int, int, int, int] | None
    html: str

    @property
    def is_picture(self) -> bool:
        return self.label in PICTURE_LABELS and self.bbox is not None


def is_structured(text: str) -> bool:
    """True when this page carries Chandra's layout labels."""
    return 'data-label=' in (text or '')


def parse_blocks(text: str) -> list[Block]:
    """Split a page into its labelled blocks, outermost only.

    Depth is tracked rather than matched with a non-greedy regex because a
    figure's HTML pastiche nests divs inside the block div; stopping at the
    first `</div>` would cut the block in half and spill its tail into the
    document as loose markup.
    """
    blocks: list[Block] = []
    depth = 0
    start = None
    label = ''
    bbox: tuple[int, int, int, int] | None = None
    cursor = 0

    for m in _BLOCK_TAG.finditer(text):
        tag = m.group(0)
        if tag.startswith('</'):
            if depth == 0:
                continue        # stray close tag; nothing open to end
            depth -= 1
            if depth == 0 and start is not None:
                blocks.append(Block(label, bbox, text[start:m.start()]))
                cursor = m.end()
                start = None
            continue

        if depth == 0:
            loose = text[cursor:m.start()].strip()
            if loose:
                blocks.append(Block('', None, loose))
            label, bbox = _read_attrs(tag)
            start = m.end()
        depth += 1

    tail = text[cursor:].strip()
    if start is not None:                       # unclosed block: keep the rest
        blocks.append(Block(label, bbox, text[start:]))
    elif tail:
        blocks.append(Block('', None, tail))
    return blocks


def _read_attrs(tag: str) -> tuple[str, tuple[int, int, int, int] | None]:
    label, bbox = '', None
    for m in _ATTRS.finditer(tag):
        if m.group(1) is not None:
            parts = m.group(1).split()
            if len(parts) == 4:
                try:
                    x0, y0, x1, y1 = (int(float(p)) for p in parts)
                except ValueError:
                    continue
                if x1 > x0 and y1 > y0:
                    bbox = (x0, y0, x1, y1)
        elif m.group(2) is not None:
            label = m.group(2)
    return label, bbox


def crop_box(
    bbox: tuple[int, int, int, int],
    width: int,
    height: int,
    pad: float = 0.005,
) -> tuple[int, int, int, int]:
    """Map a normalised bbox onto a rendered page of `width` x `height` pixels.

    A little padding is added because the model's boxes sit tight against the
    artwork, and a tight crop shaves the outermost rule or tick label off a
    figure. Clamped to the page, so padding never runs off the edge.
    """
    x0, y0, x1, y1 = bbox
    px, py = pad * BBOX_SCALE, pad * BBOX_SCALE
    left = max(0.0, x0 - px) / BBOX_SCALE * width
    top = max(0.0, y0 - py) / BBOX_SCALE * height
    right = min(float(BBOX_SCALE), x1 + px) / BBOX_SCALE * width
    bottom = min(float(BBOX_SCALE), y1 + py) / BBOX_SCALE * height
    return (round(left), round(top), round(right), round(bottom))


#: A figure this wide (as a fraction of the page) is treated as full-bleed and
#: fills the panel; narrower ones keep their proportion relative to it. Page
#: width includes margins, so a full-column figure lands near this, not at 1.0.
FULL_WIDTH_FRACTION = 0.85


def display_size(
    bbox: tuple[int, int, int, int],
    page_width: float,
    page_height: float,
    available: int,
) -> tuple[int, int]:
    """On-screen (width, height) for a figure, in device-independent pixels.

    Sized off the panel rather than the page so figures do not overflow, and
    proportionally to how much of the page they occupied so a small inset stays
    a small inset instead of being blown up to match a full-page plate.
    """
    x0, y0, x1, y1 = bbox
    frac_w = (x1 - x0) / BBOX_SCALE
    frac_h = (y1 - y0) / BBOX_SCALE
    shown_w = max(1, round(available * min(1.0, frac_w / FULL_WIDTH_FRACTION)))
    aspect = (frac_h * page_height) / (frac_w * page_width)
    return shown_w, max(1, round(shown_w * aspect))


def figure_uri(page: int, bbox: tuple[int, int, int, int]) -> str:
    """Stable URI for one figure, resolved by the view's resource loader."""
    return 'pmfig:{}/{}/{}/{}/{}'.format(page, *bbox)


def parse_figure_uri(uri: str) -> tuple[int, tuple[int, int, int, int]] | None:
    """Inverse of `figure_uri`. None if this is not one of ours."""
    if not uri.startswith('pmfig:'):
        return None
    try:
        page, x0, y0, x1, y1 = (int(p) for p in uri[len('pmfig:'):].split('/'))
    except ValueError:
        return None
    return page, (x0, y0, x1, y1)


def picture_pages(pages: list[str]) -> list[int]:
    """Indices of the pages that hold at least one croppable picture."""
    return [
        i for i, text in enumerate(pages)
        if is_structured(text) and any(b.is_picture for b in parse_blocks(text))
    ]


def page_html(
    text: str,
    page: int,
    sizer=None,
    keep_chrome: bool = False,
) -> str:
    """One page as display HTML.

    `sizer` is called with (page, bbox) and returns (width, height) in pixels,
    or None when the figure cannot be shown — no PDF to crop from, say. The
    size has to be settled here rather than left to the image itself: figures
    arrive later, and without reserved space the text would reflow under the
    reader as each one lands.
    """
    out: list[str] = []
    for block in parse_blocks(text):
        if block.label in CHROME_LABELS and not keep_chrome:
            continue
        if block.is_picture:
            out.append(_picture_html(block, page, sizer))
        elif block.label in HEADING_LABELS:
            inner = _HEADING_TAG.sub('', block.html).strip()
            out.append(f'<h2 class="pm-section">{inner}</h2>')
        elif block.label == 'Caption':
            out.append(f'<div class="pm-caption">{block.html}</div>')
        elif block.label == 'Equation-Block':
            out.append(f'<div class="pm-equation">{_MATH_TAG.sub("", block.html)}</div>')
        else:
            out.append(_MATH_TAG.sub('', block.html))
    return '\n'.join(part for part in out if part.strip())


def _picture_html(block: Block, page: int, sizer) -> str:
    bbox = block.bbox
    if bbox is None:             # only is_picture blocks reach here, which have one
        return ''
    size = sizer(page, bbox) if sizer else None
    if size is None:
        alt = _alt_text(block.html)
        if not alt:
            return ''
        return f'<div class="pm-missing-figure">[figure] {html_mod.escape(alt)}</div>'
    width, height = size
    uri = figure_uri(page, bbox)
    alt = html_mod.escape(_alt_text(block.html), quote=True)
    return (
        f'<div class="pm-figure">'
        f'<img src="{uri}" width="{width}" height="{height}" alt="{alt}"/>'
        f'</div>'
    )


def _alt_text(inner_html: str) -> str:
    m = re.search(r'<img\b[^>]*\balt="([^"]*)"', inner_html, re.I)
    return html_mod.unescape(m.group(1)) if m else ''


def document_html(pages: list[str], sizer=None, keep_chrome: bool = False) -> str:
    """The whole OCR document as one HTML string, page markers included."""
    parts: list[str] = []
    for index, text in enumerate(pages):
        body = page_html(text or '', index, sizer, keep_chrome)
        if not body.strip():
            continue
        parts.append(f'<div class="pm-page-mark">page {index + 1}</div>\n{body}')
    return '\n'.join(parts)
