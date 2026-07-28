from papermeister.paths import DB_PATH

#!/usr/bin/env python3
"""P11 — references-extraction progress monitor (read-only).

Reports how far the library-wide `extract_references` run has got, plus a
processing rate and ETA derived from the change since the previous invocation.

READ-ONLY by design. Opens the live DB with `mode=ro` and never writes to it,
so it is safe to run *alongside* the extraction — but ONLY on native Windows
(WAL lets a reader coexist with the writer). Do NOT run it from WSL against the
`/mnt/c` DB: drvfs gives no SQLite locking and a concurrent reader can desync an
index (see devlog 068). Pure stdlib, so it runs outside the conda env too.

    python scripts/refs_progress.py            # one-shot snapshot + rate-since-last-run
    python scripts/refs_progress.py --watch 60 # live: resample every 60s, rolling rate/ETA
    python scripts/refs_progress.py --db PATH  # override DB location

The "remaining" count matches extract_references.py::fetch_targets exactly:
distinct papers that own a processed, non-JSON PDF and are not yet
`references_checked`.
"""
import argparse
import json
import os
import sqlite3
import sys
import time

DEFAULT_DB = DB_PATH
STATE_FILE = os.path.expanduser('~/PaleoBytes/PaperMeister/.refs_progress_state.json')

# Eligible = distinct papers with a processed, non-JSON PDF (mirrors
# extract_references.fetch_targets). checked = those already stamped.
_SQL_ELIGIBLE = """
WITH proc AS (
    SELECT DISTINCT paper_id FROM paperfile
    WHERE status = 'processed' AND hash <> '' AND path NOT LIKE '%.json'
)
SELECT
    (SELECT COUNT(*) FROM proc) AS eligible,
    (SELECT COUNT(*) FROM proc p JOIN paper pa ON pa.id = p.paper_id
     WHERE pa.references_checked = 1) AS checked
"""


def connect_ro(db_path):
    if not os.path.exists(db_path):
        sys.exit(f'DB not found: {db_path}')
    uri = f'file:{db_path}?mode=ro'
    con = sqlite3.connect(uri, uri=True, timeout=30)
    con.execute('PRAGMA query_only = 1')
    return con


def snapshot(con):
    cur = con.cursor()
    eligible, checked = cur.execute(_SQL_ELIGIBLE).fetchone()
    refs = cur.execute('SELECT COUNT(*) FROM reference').fetchone()[0]
    held = cur.execute(
        'SELECT COUNT(*) FROM reference WHERE resolved_paper_id IS NOT NULL'
    ).fetchone()[0]
    external = cur.execute(
        'SELECT COUNT(*) FROM reference WHERE resolved_work_id IS NOT NULL'
    ).fetchone()[0]
    return {
        'ts': time.time(),
        'eligible': eligible,
        'checked': checked,
        'remaining': eligible - checked,
        'refs': refs,
        'held': held,
        'external': external,
    }


def load_state():
    try:
        with open(STATE_FILE, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def save_state(snap):
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(snap, f)
    except OSError:
        pass  # state is a convenience; never fail the monitor over it


def fmt_eta(seconds):
    if seconds is None or seconds <= 0 or seconds == float('inf'):
        return '—'
    m, _ = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    if d:
        return f'{d}d {h}h {m}m'
    if h:
        return f'{h}h {m}m'
    return f'{m}m'


def render(snap, prev, elapsed_label='since last run'):
    pct = 100.0 * snap['checked'] / snap['eligible'] if snap['eligible'] else 0.0
    bar_w = 32
    filled = int(bar_w * pct / 100)
    bar = '#' * filled + '-' * (bar_w - filled)

    lines = [
        "References extraction progress",
        f"  [{bar}] {pct:5.1f}%",
        f"  papers checked : {snap['checked']:>7,} / {snap['eligible']:,} "
        f"(processed PDFs)",
        f"  remaining      : {snap['remaining']:>7,}",
        f"  Reference rows : {snap['refs']:>7,}  "
        f"(held {snap['held']:,} / external {snap['external']:,})",
    ]

    if prev:
        dt = snap['ts'] - prev['ts']
        d_checked = snap['checked'] - prev['checked']
        d_refs = snap['refs'] - prev['refs']
        if dt > 0 and d_checked > 0:
            per_hr = d_checked / dt * 3600
            refs_hr = d_refs / dt * 3600
            eta = snap['remaining'] / (d_checked / dt) if d_checked else None
            lines += [
                f"  rate ({elapsed_label}, Δt={fmt_eta(dt)}): "
                f"{per_hr:,.0f} papers/hr, {refs_hr:,.0f} refs/hr",
                f"  ETA (at this rate)     : {fmt_eta(eta)}",
            ]
        elif dt > 0:
            lines.append(
                f"  rate ({elapsed_label}, Δt={fmt_eta(dt)}): "
                f"no new papers checked yet")
    return '\n'.join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--db', default=DEFAULT_DB, help='DB path (default: live DB)')
    ap.add_argument('--watch', type=int, metavar='SECONDS',
                    help='Resample every N seconds with a rolling rate (Ctrl-C to stop)')
    args = ap.parse_args()

    con = connect_ro(args.db)
    try:
        if args.watch:
            prev = None
            print(f'Watching every {args.watch}s (Ctrl-C to stop)...\n')
            while True:
                snap = snapshot(con)
                # clear screen for a live dashboard feel
                sys.stdout.write('\033[2J\033[H')
                print(render(snap, prev, elapsed_label=f'last {args.watch}s tick'))
                print(f"\n  {time.strftime('%Y-%m-%d %H:%M:%S')}")
                prev = snap
                if snap['remaining'] <= 0:
                    print('\nAll eligible papers checked. Done.')
                    break
                time.sleep(args.watch)
        else:
            prev = load_state()
            snap = snapshot(con)
            print(render(snap, prev))
            save_state(snap)
    except KeyboardInterrupt:
        print('\nstopped.')
    finally:
        con.close()


if __name__ == '__main__':
    main()
