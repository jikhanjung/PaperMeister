"""Pilot of the compact link answer ("caption segments", ocrserver P03).

The papers are the ones whose stored captions have a figure's own number as
its only entry ("Fig. 14" → entry "14") — 2026-09-30 decided such figures
have no entries. Re-asked in the segment format, the model decides per
figure whether the caption labels parts, so its answer checks the rule
(`figure_link.own_number_entry`) and, on the same run, whether the new
format answers as well as the old one (entries, labels, specimen numbers,
descriptions).

Submit and collect write nothing to the database: the stored answers are
snapshotted at submit time and the replies are compared against the snapshot.
`--apply` writes the replies through the same checks a collect uses — a
figure the model skipped or a reply the checks reject keeps its old answer
(no attempt counted), and fewer entries than before is refused and flagged
for a person (`entries_shrank`).

    python scripts/segs_pilot.py                 # which papers, how many figures (read-only)
    python scripts/segs_pilot.py --execute       # submit them, one job per paper
    python scripts/segs_pilot.py --collect       # compare finished replies → report
    python scripts/segs_pilot.py --apply         # what writing the replies would do
    python scripts/segs_pilot.py --apply --execute   # write them (the model's answer replaces the old)

State and report live in <data>/tmp/segs_pilot*.json. Close the app and the
queue runner first: the submit uploads workspaces, nothing else touches the DB.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from peewee import fn  # noqa: E402

from papermeister import (  # noqa: E402
    figure_lane,
    figure_link,
    figure_prompts,
    figure_share,
    figures,
)
from papermeister.database import init_db  # noqa: E402
from papermeister.figure_store import PAGE, protection  # noqa: E402
from papermeister.models import Figure, FigureEntry, PaperFile  # noqa: E402
from papermeister.nettls import install_system_trust  # noqa: E402
from papermeister.paths import DATA_DIR  # noqa: E402

install_system_trust()
sys.stdout.reconfigure(encoding='utf-8')

STATE_PATH = os.path.join(DATA_DIR, 'tmp', 'segs_pilot.json')
REPORT_PATH = os.path.join(DATA_DIR, 'tmp', 'segs_pilot_report.json')


def pages_of(pf) -> list[str] | None:
    path = figure_share.cache_path(pf)
    if not os.path.isfile(path):
        return None
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    return [(p.get('markdown') or '') for p in sorted(data.get('pages') or [], key=lambda p: p.get('page', 0))]


def pilot_files() -> list[PaperFile]:
    """One file per PDF (siblings share a hash and an answer) holding an own-number entry."""
    ids = (FigureEntry.select(FigureEntry.figure).group_by(FigureEntry.figure)
           .having(fn.COUNT(FigureEntry.id) == 1))
    rows = Figure.select().where((Figure.id << ids) & (Figure.dismissed == False))  # noqa: E712
    by_hash: dict[str, PaperFile] = {}
    for row in rows:
        if row.file_hash in by_hash or figure_link.own_number_entry(row) is None:
            continue
        pf = PaperFile.get_or_none(PaperFile.id == row.paper_file_id)
        if pf is not None and pf.trashed_at is None:
            by_hash[row.file_hash] = pf
    return sorted(by_hash.values(), key=lambda pf: pf.paper_id)


def askable(pf) -> figure_link.LinkTargets:
    """The figures that have an answer to compare with: linked, not a person's.
    Rows still failing are left out — their attempts would shrink every item
    (and widen the reading) for figures that have nothing to compare."""
    out = figure_link.LinkTargets()
    for row in Figure.select().where(Figure.paper_file == pf.id).order_by(Figure.page, Figure.id):
        if row.dismissed or row.assembly == PAGE or row.page_kind == figures.CAPTIONED_PLATE:
            continue
        if protection(row).caption:
            out.context.append(row)
        elif row.link_key:
            out.due.append(row)
    return out


def snapshot(row: Figure) -> dict:
    own = figure_link.own_number_entry(row)
    return {
        'figure_id': str(row.id), 'page': row.page, 'page_kind': row.page_kind, 'name': row.name,
        'caption': row.caption, 'linked': bool(row.link_key), 'own_number': own is not None,
        'entries': [{'label': e.label, 'printed_label': e.printed_label, 'description': e.description,
                     'specimen_number': e.specimen_number} for e in row.entries.order_by(FigureEntry.order)],
    }


def load_state() -> dict:
    if os.path.isfile(STATE_PATH):
        with open(STATE_PATH, encoding='utf-8') as f:
            return json.load(f)
    return {'jobs': {}}


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_PATH)


def submit(args) -> None:
    from papermeister.figure_client import from_preferences
    prompt = figure_prompts.load('link', 'segs')
    files = pilot_files()
    if args.limit:
        files = files[:args.limit]
    state = load_state()
    state['prompt_version'] = prompt['version']
    done = {j['file_hash'] for j in state['jobs'].values()}
    client = from_preferences() if args.execute else None
    items_total = figures_total = 0
    for pf in files:
        if pf.hash in done:
            continue
        pages = pages_of(pf)
        if pages is None:
            print(f'  paper {pf.paper_id:>6}  no OCR cache — skipped')
            continue
        targets = askable(pf)
        if not targets.due:
            continue
        digest = figure_link.ocr_digest(pages)
        request = figure_link.link_payload(pf, pages, targets, digest,
                                           client.client_id if client else 'dry-run', prompt)
        own = sum(1 for r in targets.due if figure_link.own_number_entry(r) is not None)
        items_total += len(request['items'])
        figures_total += len(targets.due)
        reading = request.get('reading_pages')
        line = (f'  paper {pf.paper_id:>6}  {len(targets.due):>3} figure(s) ({own} own-number) '
                f'in {len(request["items"])} item(s), '
                + (f'reading {len(reading)}/{len(pages)}' if reading else f'whole text {len(pages)}'))
        if not client:
            print(line)
            continue
        figure_lane.ensure_workspace(client, pf, figure_link.workspace_for(pf, pages, request), lambda m: None)
        reply = client.submit('link', request)
        state['jobs'][reply['job_id']] = {
            'file_hash': pf.hash, 'paper_file_id': pf.id, 'paper_id': pf.paper_id,
            'submitted_at': datetime.now().isoformat(timespec='seconds'),
            'items': request['items'],
            'snapshot': {str(r.id): snapshot(r) for r in targets.due},
        }
        save_state(state)
        print(f'{line}  job {reply["job_id"][:8]}')
    print(f'\n{len(files)} file(s), {figures_total} figure(s), {items_total} item(s)'
          + ('' if client else ' — dry run, add --execute to submit'))


# ── comparing ────────────────────────────────────────────────────────

_WORDS = re.compile(r'\w+', re.UNICODE)


def similarity(a: str, b: str) -> float:
    wa, wb = _WORDS.findall((a or '').lower()), _WORDS.findall((b or '').lower())
    return difflib.SequenceMatcher(None, wa, wb, autojunk=False).ratio() if (wa or wb) else 1.0


def digits(text: str) -> list[str]:
    return re.findall(r'\d+', text or '')


def compare_figure(old: dict, new: dict | None, reasons: list[str], rejected: str | None) -> dict:
    out = {'figure_id': old['figure_id'], 'name': old['name'], 'page_kind': old['page_kind'],
           'own_number_rule': old['own_number'], 'old_entries': len(old['entries'])}
    if rejected:
        out['outcome'] = f'rejected:{rejected}'
        return out
    if new is None:
        out['outcome'] = 'skipped' if any(r.startswith('link_skipped') for r in reasons) else 'missing'
        out['reasons'] = reasons
        return out
    out['outcome'] = 'answered'
    out['reasons'] = reasons
    out['new_entries'] = len(new['entries'])
    out['caption_sim'] = round(similarity(old['caption'], new['caption']), 3)
    if old['own_number']:
        # The rule says "no entries"; does the model agree?
        out['own_number_agrees'] = len(new['entries']) == 0
    old_by = {e['label']: e for e in old['entries']}
    new_by = {e['label']: e for e in new['entries']}
    common = [lab for lab in old_by if lab in new_by]
    out['labels_same'] = [e['label'] for e in old['entries']] == [e['label'] for e in new['entries']]
    out['labels_only_old'] = [lab for lab in old_by if lab not in new_by][:20]
    out['labels_only_new'] = [lab for lab in new_by if lab not in old_by][:20]
    if common:
        sims = [similarity(old_by[lab]['description'], new_by[lab]['description']) for lab in common]
        out['desc_sim'] = round(sum(sims) / len(sims), 3)
        out['specimen_same'] = sum(digits(old_by[lab]['specimen_number']) == digits(new_by[lab]['specimen_number'])
                                   for lab in common)
        out['specimen_compared'] = len(common)
        low = sorted(zip(sims, common, strict=True))[:2]
        out['desc_low'] = [{'label': lab, 'sim': round(sim, 2), 'old': old_by[lab]['description'][:160],
                            'new': new_by[lab]['description'][:160]} for sim, lab in low if sim < 0.8]
    return out


def collect(args) -> None:
    from papermeister.figure_client import from_preferences
    state = load_state()
    if not state['jobs']:
        print('nothing submitted yet')
        return
    client = from_preferences()
    rows, jobs_out = [], []
    status = Counter()
    for job_id, job in state['jobs'].items():
        info = client.job('link', job_id)
        status[info.get('status')] += 1
        replies = figure_lane.results_by_key(info)
        pf = PaperFile.get_by_id(job['paper_file_id'])
        pages = pages_of(pf) or []
        elapsed = 0.0
        item_status = Counter()
        for item in job['items']:
            reply = replies.get(item['key'], {})
            item_status[reply.get('status', 'missing')] += 1
            elapsed += float(reply.get('elapsed_s') or 0)
            if reply.get('status') != 'done' or not isinstance(reply.get('result'), dict):
                continue
            check = figure_link.validate_link_result(item, reply['result'], pages)
            rejected = dict(check.rejected)
            for f in item['figures']:
                fid = f['figure_id']
                if f.get('locked') or fid not in job['snapshot']:
                    continue
                rows.append({'paper_id': job['paper_id'], 'job': job_id[:8],
                             **compare_figure(job['snapshot'][fid], check.accepted.get(fid),
                                              check.review.get(fid, []), rejected.get(fid))})
        jobs_out.append({'job': job_id[:8], 'paper_id': job['paper_id'], 'status': info.get('status'),
                         'items': dict(item_status), 'elapsed_s': round(elapsed)})
    answered = [r for r in rows if r['outcome'] == 'answered']
    own = [r for r in answered if r['own_number_rule']]
    summary = {
        'jobs': dict(status),
        'figures': len(rows),
        'outcomes': dict(Counter(r['outcome'].split(':')[0] for r in rows)),
        'own_number_rule': {'answered': len(own), 'model_agrees': sum(r['own_number_agrees'] for r in own)},
        'model_says_none_where_rule_did_not': sum(1 for r in answered if not r['own_number_rule']
                                                  and r['old_entries'] > 0 and r['new_entries'] == 0),
        'entries_old_new': [sum(r['old_entries'] for r in answered), sum(r['new_entries'] for r in answered)],
        'labels_same': sum(r['labels_same'] for r in answered),
        'desc_sim_mean': round(sum(r['desc_sim'] for r in answered if 'desc_sim' in r)
                               / max(1, sum(1 for r in answered if 'desc_sim' in r)), 3),
        'specimen_same': [sum(r.get('specimen_same', 0) for r in answered),
                          sum(r.get('specimen_compared', 0) for r in answered)],
        'reasons': dict(Counter(x for r in rows for x in r.get('reasons', []))),
        'elapsed_s': sum(j['elapsed_s'] for j in jobs_out),
    }
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        json.dump({'summary': summary, 'jobs': jobs_out, 'figures': rows}, f, ensure_ascii=False, indent=1)
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    disagree = [r for r in own if not r['own_number_agrees']]
    by_paper = defaultdict(list)
    for r in disagree:
        by_paper[r['paper_id']].append(r)
    if disagree:
        print(f'\nown-number figures the model gave entries ({len(disagree)}):')
        for pid, rs in sorted(by_paper.items()):
            print(f'  paper {pid}: ' + ', '.join(f"#{r['figure_id']} {r['name']} → {r['new_entries']}" for r in rs[:6]))
    print(f'\nreport: {REPORT_PATH}')


def apply(args) -> None:
    from papermeister.figure_client import from_preferences
    state = load_state()
    version = state.get('prompt_version') or figure_prompts.version('link', 'segs')
    client = from_preferences()
    totals = Counter()
    for job_id, job in state['jobs'].items():
        info = client.job('link', job_id)
        replies = figure_lane.results_by_key(info)
        pf = PaperFile.get_by_id(job['paper_file_id'])
        pages = pages_of(pf)
        if pages is None:
            totals['no OCR cache'] += 1
            continue
        digest = figure_link.ocr_digest(pages)
        rows = {str(r.id): r for r in Figure.select().where(Figure.id << [int(i) for i in job['snapshot']])}
        rows = {fid: r for fid, r in rows.items() if not r.dismissed and not protection(r).caption}
        check = figure_link.LinkCheck()
        model = 'gpt-6-astra'
        for item in job['items']:
            reply = replies.get(item['key'], {})
            if reply.get('status') != 'done' or not isinstance(reply.get('result'), dict):
                totals[f'item {reply.get("status", "missing")}'] += 1
                continue
            check.merge(figure_link.validate_link_result(item, reply['result'], pages, rows))
            model = reply.get('model') or model
        accepted = [r for fid, r in rows.items() if fid in check.accepted]
        shrank = [rows[fid] for fid, why in check.rejected if why == figure_link.ENTRIES_SHRANK and fid in rows]
        totals['accepted'] += len(accepted)
        totals['refused: entries shrank'] += len(shrank)
        totals['skipped or rejected otherwise'] += len(rows) - len(accepted) - len(shrank)
        totals['own-number entries dropped'] += sum(
            1 for r in accepted if figure_link.own_number_entry(r) is not None
            and not check.accepted[str(r.id)]['entries'])
        if not args.execute:
            continue
        # Only the accepted rows are "due": the rest keep their answer and
        # their attempt count — they were linked before this run.
        targets = figure_link.LinkTargets(due=accepted)
        applied = figure_link.apply_link(targets, check, {}, digest, version, model)
        totals['written'] += applied.written
        totals['unchanged'] += applied.unchanged
        for row in shrank:
            figure_link._store_reasons(row, check.review.get(str(row.id), [figure_link.ENTRIES_SHRANK]))
            row.save()
        totals['copied to siblings'] += figure_link.propagate_link(pf)
        try:
            figure_share.write_to_cache(pf)
        except Exception as exc:  # the DB has the result; the cache catches up on the next write
            totals['cache JSON not updated'] += 1
            print(f'  paper {pf.paper_id}: cache JSON not updated ({type(exc).__name__}: {exc})')
        print(f'  paper {pf.paper_id:>6}  written {applied.written}, refused {len(shrank)}')
    print('\n' + '\n'.join(f'  {k}: {v}' for k, v in sorted(totals.items())))
    if not args.execute:
        print('\ndry run — add --execute to write')


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--execute', action='store_true', help='submit (default: list what would be sent)')
    ap.add_argument('--collect', action='store_true', help='compare finished replies with the snapshot')
    ap.add_argument('--apply', action='store_true', help='write the replies (with --execute)')
    ap.add_argument('--limit', type=int, default=0, help='only the first N files')
    args = ap.parse_args()
    init_db()
    if args.apply:
        apply(args)
    elif args.collect:
        collect(args)
    else:
        submit(args)


if __name__ == '__main__':
    main()
