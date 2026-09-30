"""The link stage's compact answer ("caption segments") back into the full one.

Asked for `caption` and `entries` separately, the model wrote every caption
twice — once whole, once cut into entry descriptions — and 89% of the
descriptions' phrases were in the caption word for word (ocrserver
FIGURE_LINK_STALLS §6, 400 replies). The answer's length is what makes a link
session slow and what breaks it, so the segment format has the model write
the caption once, as consecutive pieces, one per line:

    x :: Explanation of Plate 3
    h1 :: Oistodus aff. breviconus Branson & Mehl, lateral views, x40.
    e 1,2 | L=Figs. 1-2. | s=YSUG 00287; YSUG 00288 :: Hunghuayuan Formation.
    t 1,2 :: Scale bar 100 μm.

and this module rebuilds `caption` (the pieces joined, printed labels in
place) and `entries` (open headings + the entry's own text + its trailing
remarks) in the shape the rest of the stage already checks and stores.
Ported from ocrserver `scripts/experiments/link_segments/expand.py` (v3
format, 30 runs: output 55–65%, time 65–75%, no stalls).

Lines that do not parse are kept as caption text (nothing printed is lost)
and reported, so a person can look.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_LINE = re.compile(r'^\s*(?P<kind>x|h1|h2|t|e)(?:\s+(?P<labels>[^|:]+?))?\s*'
                   r'(?P<opts>(\|\s*[Lsd]=.*?)*)\s*::\s?(?P<text>.*)$')
_OPT = re.compile(r'\|\s*([Lsd])=(.*?)(?=\s*\|\s*[Lsd]=|$)')
_TRAILING = re.compile(r'[\s,;:、，；：]+$')
#: Scripts written without spaces between words. A piece of a Japanese or
#: Chinese caption often ends mid-sentence — inside a parenthesis, before a
#: particle — and joining it to the next with a space or a line break made
#: text the page does not have: "頭骨（ Au. afarensis. ）の比較" (pilot 2026-09-30),
#: and the caption check then found its words missing from the page.
_CJK = re.compile(r'[\u3000-\u303f\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\uff00-\uffef]')
_OPENERS = '([{（［｛「『〈《'
_CLOSERS = ')]}）］｝」』〉》、。，．,.;；:：'
_ENDS = ('.', '!', '?', ')', '。', '．', '！', '？', '）', '」', '』')

#: The fields a full figure result carries, in the order the schema lists them.
FIGURE_FIELDS = ('figure_id', 'name', 'caption', 'caption_source', 'caption_pages', 'continuation_of', 'entries')


@dataclass
class Segment:
    kind: str
    text: str
    labels: list[str] = field(default_factory=list)
    printed: str = ''        # L=  the label as printed; in the caption, not in descriptions
    specimens: str = ''      # s=  one per label, ';'-separated
    ditto: str | None = None  # d= the full description, for a ditto the pieces cannot make
    bad: bool = False


def parse(segs: str) -> list[Segment]:
    out = []
    for line in (segs or '').split('\n'):
        if not line.strip():
            continue
        m = _LINE.match(line)
        if not m:
            out.append(Segment('x', line.strip(), bad=True))
            continue
        opts = {k: v.strip() for k, v in _OPT.findall(m.group('opts') or '')}
        out.append(Segment(
            kind=m.group('kind'), text=m.group('text').strip(),
            labels=[x.strip() for x in (m.group('labels') or '').split(',') if x.strip()],
            printed=opts.get('L', ''), specimens=opts.get('s', ''), ditto=opts.get('d')))
    return out


def _trim(text: str) -> str:
    return _TRAILING.sub('', text.strip())


def _close(text: str) -> str:
    """End a part of a description as a sentence, once, in its own script."""
    t = _trim(text)
    if not t or t.endswith(_ENDS):
        return t
    return t + ('。' if _CJK.match(t[-1]) else '.')


def _join(left: str, right: str, sep: str) -> str:
    """`sep` between two pieces, or nothing where the printed text has none:
    at a CJK boundary, after an opening bracket, before closing punctuation."""
    if not left or not right:
        return left + right
    if (_CJK.match(left[-1]) or _CJK.match(right[0]) or left[-1] in _OPENERS
            or right[0] in _CLOSERS):
        return left + right
    return left + sep + right


def _run_on(parts: list[str]) -> str:
    """Pieces that continue one sentence ("Specimen X in" + "lateral view")."""
    out = ''
    for p in parts:
        out = _join(out, p.strip(), ' ')
    return out


def _description(body: list[str], tails: list[str]) -> str:
    """Headings and the entry's text run on; each remark is closed off as its
    own sentence — unless it only finishes the one before ("）の比較")."""
    out = _run_on(body)
    for tail in tails:
        tail = tail.strip()
        if not tail:
            continue
        if out and tail[0] in _CLOSERS:
            out = _trim(out) + tail
        else:
            out = _join(_close(out), tail, ' ') if out else tail
    return _close(out)


def expand_figure(figure: dict) -> tuple[dict, list[str]]:
    """One figure's `segs` → its full result; plus warnings for a person."""
    segs = parse(figure.get('segs', ''))
    caption = ''
    for s in segs:
        caption = _join(caption, (s.printed + ' ' if s.printed else '') + s.text, '\n')
    entries: list[dict] = []
    group: list[dict] = []      # entries since the last h1 — what a bare `t` applies to
    h1 = h2 = ''
    warnings = []
    for s in segs:
        if s.bad:
            warnings.append('unparsed: ' + s.text[:60])
        if s.kind == 'h1':
            h1, h2, group = s.text, '', []
        elif s.kind == 'h2':
            h2 = s.text
        elif s.kind == 't':
            pool = entries if s.labels else group
            hit = [e for e in pool if not s.labels or e['label'] in s.labels]
            if s.labels and len(hit) < len(s.labels):
                warnings.append(f't labels not found: {s.labels}')
            for e in hit:
                if not e['_ditto']:
                    e['_tail'].append(s.text)
        elif s.kind == 'e':
            specimens = [x.strip() for x in s.specimens.split(';')] if s.specimens else []
            for i, label in enumerate(s.labels):
                e = {'label': label,
                     # "Figs. 1-2." belongs to both; each entry keeps its own label.
                     'printed_label': s.printed if (s.printed and len(s.labels) == 1) else label,
                     'specimen_number': specimens[i] if i < len(specimens) else '',
                     '_body': [x for x in (h1, h2, s.text) if x], '_ditto': s.ditto, '_tail': []}
                entries.append(e)
                group.append(e)
    out = []
    for e in entries:
        description = e['_ditto'] or _description(e['_body'], e['_tail'])
        out.append({'label': e['label'], 'printed_label': e['printed_label'],
                    'description': description.strip(), 'specimen_number': e['specimen_number']})
    full = {k: v for k, v in figure.items() if k != 'segs'}
    full['caption'] = caption
    full['entries'] = out
    return {k: full.get(k) for k in FIGURE_FIELDS}, warnings


def expand(result: dict) -> tuple[dict, dict[str, list[str]]]:
    """A whole reply: figures given as `segs` are expanded, full ones pass
    through. Returns the reply in the full shape and warnings by figure id."""
    figures, warnings = [], {}
    for f in result.get('figures', []) or []:
        if isinstance(f, dict) and 'segs' in f:
            full, w = expand_figure(f)
            figures.append(full)
            if w:
                warnings[str(f.get('figure_id', ''))] = w
        else:
            figures.append(f)
    return {**result, 'figures': figures}, warnings


def is_compact(result: dict) -> bool:
    return any(isinstance(f, dict) and 'segs' in f for f in result.get('figures', []) or [])
