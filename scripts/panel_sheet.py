"""③ gate: look at the panels the model drew.

One card per figure that has panels: the figure cropped from the PDF, each
panel's box and label drawn on it, and beside it the entries the panel was
matched to. Read-only. Written to <data>/tmp/p16_panels/<paper>.html.

    python scripts/panel_sheet.py --paper-ids 664
"""
import argparse
import html
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import ImageDraw  # noqa: E402

from papermeister import pdfdoc  # noqa: E402
from papermeister.database import init_db  # noqa: E402
from papermeister.figure_lane import local_pdf  # noqa: E402
from papermeister.models import Figure, FigureEntry, FigurePanel, PaperFile  # noqa: E402
from papermeister.paths import DATA_DIR  # noqa: E402

DPI = 110
COLOURS = ['#e11d48', '#2563eb', '#16a34a', '#d97706', '#7c3aed', '#0891b2']


def crop_figure(pdf: str, row: Figure):
    page = pdfdoc.render_page(pdf, row.page, dpi=DPI)
    w, h = page.size
    x0, y0, x1, y1 = json.loads(row.bbox_page_1000)
    return page.crop((int(x0 * w / 1000), int(y0 * h / 1000), int(x1 * w / 1000), int(y1 * h / 1000)))


def draw_panels(image, panels):
    draw = ImageDraw.Draw(image)
    w, h = image.size
    for i, p in enumerate(panels):
        x0, y0, x1, y1 = json.loads(p.bbox_figure_1000)
        box = (x0 * w / 1000, y0 * h / 1000, x1 * w / 1000, y1 * h / 1000)
        colour = COLOURS[i % len(COLOURS)]
        draw.rectangle(box, outline=colour, width=3)
        text = p.label or '?'
        tw = 7 * len(text) + 6
        draw.rectangle((box[0], box[1], box[0] + tw, box[1] + 14), fill=colour)
        draw.text((box[0] + 3, box[1] + 1), text, fill='white')
    return image


def card(row: Figure, image_rel: str, panels, entries) -> str:
    by_order = {e.order: e for e in entries}
    lines = []
    for i, p in enumerate(panels):
        matched = [by_order[o] for o in json.loads(p.entry_orders_json or '[]') if o in by_order]
        desc = '; '.join(f'<b>{html.escape(e.label)}</b> {html.escape(e.description[:140])}' for e in matched) or '<i>no entry</i>'
        colour = COLOURS[i % len(COLOURS)]
        flag = ' <span class=ann>annotation</span>' if p.annotation else ''
        lines.append(f'<li><span class=sw style="background:{colour}"></span> <b>{html.escape(p.label or "?")}</b>'
                     f' <small>{p.confidence}</small>{flag} — {desc}</li>')
    unmatched = [e for e in entries if not any(e.order in json.loads(p.entry_orders_json or '[]') for p in panels)]
    if unmatched:
        lines.append('<li class=un>entries without a panel: ' + ', '.join(html.escape(e.label) for e in unmatched) + '</li>')
    reasons = json.loads(row.uncertain_reasons_json or '[]')
    return (f'<div class=card><h3>#{row.id} {html.escape(row.name)} — p.{row.page + 1} · {row.kind or "?"} · '
            f'{"compound" if row.is_compound else "single"} · {len(panels)} panels / {len(entries)} entries'
            + (f' · <span class=rev>{html.escape(", ".join(reasons))}</span>' if reasons else '') + '</h3>'
            f'<div class=body><img src="{image_rel}"><ol>{"".join(lines)}</ol></div></div>')


CSS = """body{font-family:system-ui;background:#111;color:#ddd;margin:16px}.card{margin:0 0 28px;border-top:1px solid #333;padding-top:8px}
.body{display:flex;gap:16px;align-items:flex-start}img{max-width:60%;border:1px solid #444}ol{font-size:13px;line-height:1.5;margin:0;padding-left:20px;max-width:38%}
.sw{display:inline-block;width:10px;height:10px;margin-right:3px}.ann{color:#f6c744}.un{color:#f87171;list-style:none}.rev{color:#f6c744;font-weight:normal}small{color:#888}"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--paper-ids', required=True)
    ap.add_argument('--out', default=os.path.join(DATA_DIR, 'tmp', 'p16_panels'))
    args = ap.parse_args()
    init_db()
    for pid in [int(x) for x in args.paper_ids.split(',')]:
        out_dir = os.path.join(args.out, str(pid))
        os.makedirs(os.path.join(out_dir, 'img'), exist_ok=True)
        cards = []
        for pf in PaperFile.select().where(PaperFile.paper == pid):
            pdf = local_pdf(pf)
            if not pdf:
                print(f'paper {pid}: PDF not on this machine')
                continue
            rows = (Figure.select().where((Figure.paper_file == pf.id) & (Figure.dismissed == False))  # noqa: E712
                    .order_by(Figure.page, Figure.id))
            for row in rows:
                panels = list(FigurePanel.select().where(FigurePanel.figure == row.id).order_by(FigurePanel.order))
                if not panels and not row.paneled_at:
                    continue
                entries = list(FigureEntry.select().where(FigureEntry.figure == row.id).order_by(FigureEntry.order))
                name = f'f{row.id}.jpg'
                draw_panels(crop_figure(pdf, row), panels).save(os.path.join(out_dir, 'img', name), 'JPEG', quality=80)
                cards.append(card(row, f'img/{name}', panels, entries))
        path = os.path.join(out_dir, 'index.html')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(f'<!doctype html><meta charset=utf-8><title>panels {pid}</title><style>{CSS}</style>'
                    f'<h1>paper {pid} — {len(cards)} figures with a panels result</h1>' + ''.join(cards))
        print(f'paper {pid}: {len(cards)} cards → {path}')


if __name__ == '__main__':
    main()
