"""Contact sheets for reviewing assembled figures — the P16 Phase 1 gate.

The gate is "a person looks at the pilot's figures and says the assembly is
right". The pilot has 3,750 figures; nobody clicks through that in the Text
tab, and clicking would show one figure at a time without the page around it —
which is where an assembly error shows (a photograph left out of a plate, a
caption that belongs to the column next door). fsis2026 checked its rules by
rendering the pages a rule had touched and looking (devlog 275); 097 §4 did
the same by hand. This makes that a command.

A sheet is one HTML page per *stratum* — pages grouped by what the rule did
to them, because each kind is checked for a different mistake — with every
page drawn once: picture blocks and captions faintly, the assembled figures in
colour, and the assembly's own words next to it (name, kind, caption hint).
Pages with pictures but no figure are a stratum of their own: that is where
a filter has thrown a figure away (fsis lost 766 plate photographs that way).

Nothing here writes to the database. Recording a decision is
`papermeister.figure_curation`.
"""
from __future__ import annotations

import html
import json
import os
import random
from collections import Counter
from dataclasses import dataclass, field

from PIL import Image, ImageDraw

from . import figures
from .figures import (
    CAPTION_GROUP,
    CAPTIONED_PLATE,
    DUP_NUMBER,
    MANY_MARKS,
    PLATE_KIND,
    PLATE_UNION,
    SINGLE,
    AssembledFigure,
    PageAssembly,
)

#: Strata in the order a page is tested — the first that matches wins. Each
#: names the mistake to look for, which is what the sheet's header says.
STRATA: tuple[tuple[str, str], ...] = (
    ('dropped', 'Pages with pictures but no figure — did a filter throw a figure away? '
                '(fsis: a width filter dropped 766 plate photographs)'),
    ('plate_inferred', 'Plate number not printed on this page, inferred from the page before '
                       '(Explanation of Plate N), the page after (PLATE N+1) or a bare PLATE — '
                       'is the number right?'),
    ('dup_number', 'One-photo page whose plate number another page also carries — no name given. '
                   'Is it really a stray (an arrow figure on an explanation page), or a plate '
                   'the OCR misread (Pl. XLI → Pl. XII)?'),
    ('many_marks', 'Two plate numbers on one page — nothing merged. Two plates on one page, '
                   'or one plate with a cross-reference?'),
    ('captioned_plate', 'Plate header over photographs that carry their own Fig. N captions — '
                        'one figure per photograph, named Plate N, Fig. M. Are the captions theirs?'),
    ('plate_single', 'One-photo plate page — the whole plate scanned as one image. '
                     'Is it a plate, or a body figure citing a plate?'),
    ('plate_union', 'Plate page merged from several photographs — is every photograph inside '
                    'the box, and nothing that is not the plate?'),
    ('cut_up', 'A figure the OCR cut into pieces, joined under one numbered caption — '
               'are the pieces one figure, and is nothing from the next figure joined in?'),
    ('body', 'Ordinary figures — one picture block each. Is the caption hint the right caption '
             '(not the next column\'s)?'),
)
STRATUM_NAMES = tuple(name for name, _ in STRATA)

#: Box colours, by what the box is.
_PICTURE = (140, 140, 140)
_CAPTION = (230, 190, 0)
_FIGURE = {
    SINGLE: (40, 90, 220),
    PLATE_UNION: (220, 40, 40),
    CAPTION_GROUP: (30, 160, 60),
}
_CAPTIONED_PLATE_COLOUR = (240, 130, 20)
_PLATE_SINGLE_COLOUR = (180, 40, 160)


def classify_page(assembly: PageAssembly) -> str | None:
    """Which stratum a page belongs to, or None when there is nothing to review."""
    if assembly.picture_blocks == 0:
        return None
    figs = assembly.figures
    if not figs:
        return 'dropped'
    if any(f.plate_inferred for f in figs):
        return 'plate_inferred'
    if assembly.verdict == DUP_NUMBER:
        return 'dup_number'
    if assembly.verdict == MANY_MARKS:
        return 'many_marks'
    if any(f.page_kind == CAPTIONED_PLATE for f in figs):
        return 'captioned_plate'
    if any(f.page_kind == PLATE_KIND and f.assembly == PLATE_UNION for f in figs):
        return 'plate_union'
    if any(f.page_kind == PLATE_KIND for f in figs):
        return 'plate_single'
    if any(f.assembly == CAPTION_GROUP for f in figs):
        return 'cut_up'
    return 'body'


@dataclass
class Card:
    """One page on a sheet."""

    paper_id: int
    paper_file_id: int
    title: str
    pdf_path: str | None
    page: int                           # 0-based, as everywhere in P16
    page_text: str
    assembly: PageAssembly
    stratum: str
    row_ids: dict[tuple, int] = field(default_factory=dict)   # figure key -> stored Figure.id
    image: str = ''                     # relative path of the rendered page, once drawn

    def key(self, fig: AssembledFigure) -> str:
        """The identity a person can hand to figure_curate before rows exist."""
        return f'{self.paper_file_id}:{fig.page}:{",".join(str(v) for v in fig.bbox)}'


def sample_cards(cards: list[Card], per_stratum: int | None, seed: int) -> list[Card]:
    """At most `per_stratum` pages per stratum, chosen with the seed; all when None."""
    if per_stratum is None:
        return cards
    rng = random.Random(seed)
    by_stratum: dict[str, list[Card]] = {}
    for card in cards:
        by_stratum.setdefault(card.stratum, []).append(card)
    chosen: list[Card] = []
    for name in STRATUM_NAMES:
        group = by_stratum.get(name, [])
        if len(group) > per_stratum:
            group = rng.sample(group, per_stratum)
        chosen.extend(group)
    return chosen


def _scale(box, width: int, height: int) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = box
    return (x0 / 1000 * width, y0 / 1000 * height, x1 / 1000 * width, y1 / 1000 * height)


def draw_page(image: Image.Image, facts: figures.PageFacts, figs: list[AssembledFigure]) -> Image.Image:
    """Picture blocks and captions faintly, assembled figures in colour, on a copy."""
    out = image.convert('RGB')
    draw = ImageDraw.Draw(out)
    w, h = out.size
    for reg in facts.regs:
        if reg.is_picture:
            draw.rectangle(_scale(reg.box, w, h), outline=_PICTURE, width=1)
        elif reg.label == 'Caption':
            draw.rectangle(_scale(reg.box, w, h), outline=_CAPTION, width=2)
    for index, fig in enumerate(figs, 1):
        if fig.page_kind == CAPTIONED_PLATE:
            colour = _CAPTIONED_PLATE_COLOUR
        elif fig.page_kind == PLATE_KIND and fig.assembly != PLATE_UNION:
            colour = _PLATE_SINGLE_COLOUR
        else:
            colour = _FIGURE.get(fig.assembly, _FIGURE[SINGLE])
        x0, y0, x1, y1 = _scale(fig.bbox, w, h)
        draw.rectangle((x0, y0, x1, y1), outline=colour, width=3)
        draw.rectangle((x0, y0, x0 + 18, y0 + 14), fill=colour)
        draw.text((x0 + 3, y0 + 1), str(index), fill=(255, 255, 255))
    return out


def _describe(card: Card, fig: AssembledFigure, index: int) -> str:
    row = card.row_ids.get((fig.page, tuple(fig.bbox), fig.assembly))
    ident = f'#{row}' if row is not None else card.key(fig)
    kind = fig.assembly
    if fig.page_kind != figures.BODY:
        kind += f' · {fig.page_kind}'
    if fig.plate is not None:
        kind += f' · plate {fig.plate}' + (' (inferred)' if fig.plate_inferred else '')
    bits = [
        f'<b>{index}</b> <code>{html.escape(ident)}</code>',
        f'<b>{html.escape(fig.name_hint) or "(no name)"}</b> — {html.escape(kind)}, '
        f'{len(fig.blocks)} block{"s" if len(fig.blocks) != 1 else ""}',
    ]
    if fig.caption_hint:
        bits.append(f'<span class="hint">caption hint: {html.escape(fig.caption_hint[:160])}'
                    f'{"…" if len(fig.caption_hint) > 160 else ""}</span>')
    else:
        bits.append('<span class="none">no caption hint</span>')
    if fig.label_hints:
        bits.append('labels: ' + html.escape(', '.join(fig.label_hints[:12])))
    return '<br>'.join(bits)


def _card_html(card: Card) -> str:
    a = card.assembly
    dropped = ', '.join(f'{k} {v}' for k, v in sorted(a.dropped.items()))
    head = (f'<div class="head"><b>paper {card.paper_id}</b> · {html.escape(card.title[:90])}'
            f' · page {card.page} <small>(print {card.page + 1})</small>'
            f' · {a.picture_blocks} picture block{"s" if a.picture_blocks != 1 else ""}'
            + (f' · verdict <code>{html.escape(a.verdict)}</code>' if a.verdict else '')
            + (f' · dropped: {html.escape(dropped)}' if dropped else '')
            + '</div>')
    if card.image:
        img = f'<a href="{card.image}"><img src="{card.image}" loading="lazy"></a>'
    else:
        img = '<div class="nopdf">PDF not on this machine — boxes not drawn</div>'
    figs = ''.join(f'<li>{_describe(card, f, i)}</li>' for i, f in enumerate(a.figures, 1)) or \
        '<li class="none">no figure assembled from this page</li>'
    return f'<div class="card">{head}<div class="body">{img}<ol>{figs}</ol></div></div>'


_CSS = """
body{font:14px/1.4 system-ui,sans-serif;margin:16px;background:#f4f4f4;color:#222}
h1{font-size:20px}h2{font-size:16px;margin:24px 0 8px}
.legend span{display:inline-block;padding:2px 8px;margin-right:6px;border-radius:3px;color:#fff}
.card{background:#fff;border:1px solid #ddd;border-radius:6px;margin:12px 0;padding:10px}
.head{margin-bottom:8px}.body{display:flex;gap:16px;align-items:flex-start}
.body img{max-width:520px;max-height:700px;border:1px solid #ccc}
.body ol{margin:0;padding-left:20px;flex:1}.body li{margin-bottom:8px}
.hint{color:#555}.none{color:#a33}.nopdf{width:520px;height:200px;background:#eee;
display:flex;align-items:center;justify-content:center;color:#888}
code{background:#eef;padding:0 3px}small{color:#888}
table{border-collapse:collapse}td,th{padding:3px 10px;border-bottom:1px solid #ddd;text-align:left}
"""


def _legend() -> str:
    items = [
        (_FIGURE[SINGLE], 'single'), (_FIGURE[PLATE_UNION], 'plate page union'),
        (_FIGURE[CAPTION_GROUP], 'cut-up figure'), (_PLATE_SINGLE_COLOUR, 'one-photo plate'),
        (_CAPTIONED_PLATE_COLOUR, 'captioned plate photo'),
        (_PICTURE, 'picture block (thin)'), (_CAPTION, 'caption block (thin)'),
    ]
    return '<div class="legend">' + ''.join(
        f'<span style="background:rgb{c}">{html.escape(t)}</span>' for c, t in items) + '</div>'


def write_sheets(cards: list[Card], totals: Counter, out_dir: str) -> dict[str, str]:
    """One HTML per stratum plus an index. Returns stratum -> file name."""
    os.makedirs(out_dir, exist_ok=True)
    files: dict[str, str] = {}
    by_stratum: dict[str, list[Card]] = {}
    for card in cards:
        by_stratum.setdefault(card.stratum, []).append(card)
    for name, what in STRATA:
        group = by_stratum.get(name)
        if not group:
            continue
        group.sort(key=lambda c: (c.paper_id, c.page))
        body = ''.join(_card_html(c) for c in group)
        page = (f'<!doctype html><meta charset="utf-8"><title>{name} — figure review</title>'
                f'<style>{_CSS}</style><h1>{name} <small>{len(group)} of {totals[name]} pages</small></h1>'
                f'<p>{html.escape(what)}</p>{_legend()}'
                f'<p>To record a decision: <code>python scripts/figure_curate.py &lt;confirm|dismiss|rename|set-bbox|merge&gt; '
                f'--figure-ids ID[,ID] --reason "…" --execute</code> — or <code>--keys file:page:x0,y0,x1,y1</code> '
                f'before rows are stored.</p>{body}')
        files[name] = f'{name}.html'
        with open(os.path.join(out_dir, files[name]), 'w', encoding='utf-8') as f:
            f.write(page)
    rows = ''.join(
        f'<tr><td><a href="{files[name]}">{name}</a></td><td>{len(by_stratum.get(name, []))}</td>'
        f'<td>{totals[name]}</td><td>{html.escape(what)}</td></tr>'
        for name, what in STRATA if name in files)
    index = (f'<!doctype html><meta charset="utf-8"><title>Figure review</title><style>{_CSS}</style>'
             f'<h1>Figure assembly review</h1>{_legend()}'
             f'<table><tr><th>stratum</th><th>shown</th><th>total</th><th>what to check</th></tr>{rows}</table>')
    with open(os.path.join(out_dir, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(index)
    return files


def render_card(card: Card, out_dir: str, dpi: int) -> None:
    """Render the card's page, draw on it, save it under out_dir/img, set card.image."""
    if not card.pdf_path or not os.path.isfile(card.pdf_path):
        return
    from . import pdfdoc
    facts = figures.read_page(card.page, card.page_text)
    image = draw_page(pdfdoc.render_page(card.pdf_path, card.page, dpi=dpi), facts, card.assembly.figures)
    os.makedirs(os.path.join(out_dir, 'img'), exist_ok=True)
    name = f'p{card.paper_file_id}_{card.page:04d}.jpg'
    image.save(os.path.join(out_dir, 'img', name), 'JPEG', quality=72)
    card.image = f'img/{name}'


def row_ids_for(paper_file_id: int) -> dict[tuple, int]:
    """Stored Figure rows of a file, keyed like assembly output, when the table exists."""
    from .models import Figure
    if not Figure.table_exists():
        return {}
    out = {}
    for row in Figure.select(Figure.id, Figure.page, Figure.bbox_page_1000, Figure.assembly).where(
            Figure.paper_file == paper_file_id):
        out[(row.page, tuple(json.loads(row.bbox_page_1000)), row.assembly)] = row.id
    return out
