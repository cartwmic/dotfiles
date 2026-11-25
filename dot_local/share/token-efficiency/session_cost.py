#!/usr/bin/env python3
"""session-cost: list-price cost per agent seat, over two windows, from usage.sqlite (built by collect.py).

  session-cost                      last 7 days next to the 7 days before
  session-cost --days 3             windows of 3 days
  session-cost --since ISO --until ISO    one window, e.g. the published baseline
  session-cost --refresh            run collect.py first (about 10 seconds) so the last hour is in
  session-cost --snapshot [DIR]     write today's snapshot (JSON) to DIR and say where; the daily timer does this
  session-cost workstreams --since DATE [--until DATE]
                                    list-price spend per coordinator workstream (collects first; see workstreams.py)

Seats, list prices and request counting are analyze.py's (one source). List price is what the tokens would cost
at public per-token rates; it is not subscription billing.
"""
import argparse
import contextlib
import json
import os
import sqlite3
import sys
import tempfile
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import collect  # noqa: E402
import workstreams  # noqa: E402
from analyze import COMPLETE_FROM, fmt, load_files, load_requests, parse_ts  # noqa: E402

SNAPSHOT_DIR = os.path.expanduser('~/.local/share/token-efficiency-snapshots')
T3_DB = os.path.expanduser('~/.t3/userdata/statev2.sqlite')
LEDGER_DB = os.path.expanduser('~/.local/share/coordinator/ledger.sqlite')
PST = timedelta(hours=8)   # the harness counts days in PST (UTC-8), all year


def iso(dt):
    """UTC ISO with milliseconds, the same shape as the timestamps in usage.sqlite (so string comparison is exact)."""
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (dt.microsecond // 1000)


def short(ts):
    return ts[:16] + 'Z'


def pst_day(dt):
    return (dt - PST).strftime('%Y-%m-%d')


def first_complete_pst_day(complete_from):
    """The first whole PST day that starts at or after the moment logs became complete."""
    t = parse_ts(complete_from)
    day_start = (t - PST).replace(hour=0, minute=0, second=0, microsecond=0) + PST
    return pst_day(day_start if day_start >= t else day_start + timedelta(days=1))


def window_stats(reqs, name, since, until, clipped=False):
    seats = defaultdict(lambda: dict(requests=0, list_usd=0.0, ctx=0))
    for r in reqs:
        s = seats[r['seat']]
        s['requests'] += 1
        s['list_usd'] += r['usd']
        s['ctx'] += r['ctx']
    first = min((r['ts'] for r in reqs), default=None)
    last = max((r['ts'] for r in reqs), default=None)
    # days = first request to last request in the window: the divisor analyze.py's "per day" uses, so numbers match the baseline
    days = (parse_ts(last) - parse_ts(first)).total_seconds() / 86400 if len(reqs) > 1 else 0
    total = dict(requests=sum(s['requests'] for s in seats.values()), list_usd=sum(s['list_usd'] for s in seats.values()),
                 ctx=sum(s['ctx'] for s in seats.values()))
    out = dict(name=name, since=since, until=until, clipped=clipped, first_request=first, last_request=last, days=days, seats={}, total=None)
    for seat, s in list(seats.items()) + ([('all', total)] if reqs else []):
        row = dict(requests=s['requests'], list_usd=s['list_usd'], avg_prompt=s['ctx'] / s['requests'] if s['requests'] else 0,
                   usd_per_day=s['list_usd'] / days if days else None)
        if seat == 'all':
            out['total'] = row
        else:
            out['seats'][seat] = row
    return out


def per_day(reqs):
    days = defaultdict(lambda: defaultdict(lambda: dict(requests=0, list_usd=0.0, ctx=0)))
    for r in reqs:
        d = days[r['day']][r['seat']]
        d['requests'] += 1
        d['list_usd'] += r['usd']
        d['ctx'] += r['ctx']
    return {day: {seat: dict(requests=v['requests'], list_usd=v['list_usd'], avg_prompt=v['ctx'] / v['requests'])
                  for seat, v in sorted(seats.items())} for day, seats in sorted(days.items())}


def build_report(db_path, now, days=7, since=None, until=None):
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    files = load_files(db)
    start_ok = iso(parse_ts(COMPLETE_FROM))
    if since:
        spans = [('window', since, until or iso(now))]
    else:
        spans = [('last %dd' % days, iso(now - timedelta(days=days)), iso(now)),
                 ('prior %dd' % days, iso(now - timedelta(days=2 * days)), iso(now - timedelta(days=days)))]
    windows = []
    for name, lo, hi in spans:
        clipped = lo < start_ok   # before COMPLETE_FROM the logs are partial: not counted
        cut = max(lo, start_ok)
        reqs = load_requests(db, files, cut, hi) if cut < hi else []
        windows.append(window_stats(reqs, name, lo, hi, clipped))
    everything = load_requests(db, files, start_ok, iso(now))
    return dict(generated_at=iso(now), pst_day=pst_day(now), complete_from=COMPLETE_FROM,
                first_complete_pst_day=first_complete_pst_day(COMPLETE_FROM), windows=windows, days=per_day(everything))


def money(v):
    return '-' if v is None else ('$%.0f' % v if v >= 10 else '$%.2f' % v)


def change(new, old):
    if new is None or old is None:
        return '-'
    if not old:
        return 'new' if new else '-'
    return '%+.0f%%' % (100 * (new - old) / old)


def render(rep, db_mtime=None):
    out = ['session-cost: list-price cost per agent seat, from the Claude Code logs on this host.',
           'List price = what the tokens would cost at public per-token rates. It is NOT subscription billing.',
           '$/day = window list $ / days between the first and last request in the window. Avg prompt = input + cache tokens per request.',
           'Logs are complete from %s (first complete PST day: %s). Earlier logs are partial and are not counted.'
           % (short(rep['complete_from']), rep['first_complete_pst_day'])]
    if db_mtime:
        out.append('Data collected: %s.' % db_mtime)
    out.append('')
    ws = rep['windows']
    for w in ws:
        if w['total']:
            out.append('%-9s %s to %s, %d requests over %.2f days, list $%.0f%s'
                       % (w['name'] + ':', short(w['first_request']), short(w['last_request']), w['total']['requests'], w['days'],
                          w['total']['list_usd'], ' (starts where complete logs start, not %s)' % short(w['since']) if w['clipped'] else ''))
        else:
            out.append('%-9s no requests counted (%s to %s; logs before %s are partial and are not counted)'
                       % (w['name'] + ':', short(w['since']), short(w['until']), short(rep['complete_from'])))
    out.append('')
    seats = []
    for w in ws:
        seats += [s for s in sorted(w['seats'], key=lambda k: -w['seats'][k]['list_usd']) if s not in seats]
    seats.append('all')
    head = ['seat']
    for w in ws:
        head += ['%s $/day' % w['name'], 'avg prompt', 'list $']
    if len(ws) == 2:
        head.append('$/day change')
    rows = []
    for seat in seats:
        row = [seat]
        cells = []
        for w in ws:
            x = w['total'] if seat == 'all' else w['seats'].get(seat)
            x = x or None
            if x is None:
                row += ['-', '-', '-']
                cells.append(None)
            else:
                row += [money(x['usd_per_day']), fmt(x['avg_prompt']), money(x['list_usd'])]
                cells.append(x['usd_per_day'])
        if len(ws) == 2:
            row.append(change(cells[0], cells[1]))
        rows.append(row)
    widths = [max(len(str(r[i])) for r in [head] + rows) for i in range(len(head))]
    for r in [head, None] + rows:
        out.append('-' * (sum(widths) + 2 * (len(widths) - 1)) if r is None
                   else '  '.join(str(c).ljust(widths[i]) if i == 0 else str(c).rjust(widths[i]) for i, c in enumerate(r)))
    return '\n'.join(out)


def write_snapshot(rep, directory):
    """One file per PST day, written whole and moved into place. A rerun the same day replaces that day's file; no other file is touched."""
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, rep['pst_day'] + '.json')
    fd, tmp = tempfile.mkstemp(dir=directory, prefix='.snapshot-', suffix='.tmp')
    with os.fdopen(fd, 'w') as fh:
        json.dump(rep, fh, indent=1)
        fh.write('\n')
    os.replace(tmp, path)
    return path


def when(text):
    """A date (UTC midnight) or an ISO time, as the ISO shape usage.sqlite uses."""
    return iso(parse_ts(text if 'T' in text else text + 'T00:00:00Z'))


def log_action(state_dir, record):
    """One JSON line per run in state_dir/log.jsonl: what ran, over which window, how it ended. A failure to write it is ignored."""
    try:
        with open(os.path.join(state_dir, 'log.jsonl'), 'a') as fh:
            fh.write(json.dumps(record) + '\n')
    except OSError:
        pass


def workstreams_main(argv):
    ap = argparse.ArgumentParser(prog='session-cost workstreams', description='List-price spend per coordinator workstream.')
    ap.add_argument('--since', required=True, help='start: a date (UTC midnight) or an ISO UTC time')
    ap.add_argument('--until', default=None, help='end (default: now)')
    ap.add_argument('--db', default=os.path.join(collect.STATE_DIR, 'usage.sqlite'))
    ap.add_argument('--t3-db', default=T3_DB, help='T3 database, opened read-only (default %s)' % T3_DB)
    ap.add_argument('--ledger', default=LEDGER_DB, help='coordinator ledger, opened read-only (default %s)' % LEDGER_DB)
    ap.add_argument('--no-collect', action='store_true', help='use the usage database as it is; by default collect.py runs first')
    a = ap.parse_args(argv)
    state_dir = os.path.dirname(os.path.abspath(a.db))
    run_id, started, outcome, rep = uuid.uuid4().hex[:12], time.time(), 'failed', None
    try:
        if not a.no_collect:
            with contextlib.redirect_stdout(sys.stderr):   # collect prints its own counts; keep stdout for the report
                collect.main(state_dir)
        for label, path in (('usage database', a.db), ('T3 database', a.t3_db), ('ledger', a.ledger)):
            if not os.path.exists(path):
                sys.exit('session-cost workstreams: %s not found at %s' % (label, path))
        since = when(a.since)
        until = when(a.until) if a.until else iso(datetime.now(timezone.utc))
        rep = workstreams.build(a.db, workstreams.load_t3(a.t3_db), workstreams.load_ledger(a.ledger), since, until)
        mtime = datetime.fromtimestamp(os.path.getmtime(a.db), timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
        print(workstreams.render(rep, a.db, mtime))
        outcome = 'ok'
    finally:
        record = dict(ts=iso(datetime.now(timezone.utc)), run=run_id, action='workstreams', outcome=outcome, collected=not a.no_collect,
                      seconds=round(time.time() - started, 1))
        if rep:
            record.update(since=rep['since'], until=rep['until'], sessions=rep['sessions'], requests=rep['total']['requests'],
                          list_usd=round(rep['total']['usd'], 2), unmapped_share=round(workstreams.unmapped_share(rep), 4))
        log_action(state_dir, record)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == 'workstreams':
        return workstreams_main(argv[1:])
    ap = argparse.ArgumentParser(description='List-price cost per agent seat, two windows side by side.')
    ap.add_argument('--days', type=int, default=7, help='window length in days (default 7)')
    ap.add_argument('--now', default=None, help='end of the last window, ISO UTC (default: now)')
    ap.add_argument('--since', default=None, help='one window from this ISO UTC time (with --until, instead of two windows)')
    ap.add_argument('--until', default=None)
    ap.add_argument('--db', default=os.path.join(collect.STATE_DIR, 'usage.sqlite'))
    ap.add_argument('--refresh', action='store_true', help='run collect.py first')
    ap.add_argument('--snapshot', nargs='?', const=SNAPSHOT_DIR, default=None, metavar='DIR',
                    help='write today\'s snapshot JSON to DIR (default %s) instead of printing the table' % SNAPSHOT_DIR)
    a = ap.parse_args(argv)
    if a.until and not a.since:
        ap.error('--until needs --since')
    if a.refresh:
        collect.main(os.path.dirname(os.path.abspath(a.db)))
    if not os.path.exists(a.db):
        sys.exit('session-cost: no usage database at %s. Run collect.py (the daily timer does), or pass --refresh.' % a.db)
    now = parse_ts(a.now) if a.now else datetime.now(timezone.utc)
    rep = build_report(a.db, now, a.days, a.since, a.until)
    if a.snapshot:
        print('wrote', write_snapshot(rep, a.snapshot))
    else:
        mtime = datetime.fromtimestamp(os.path.getmtime(a.db), timezone.utc).strftime('%Y-%m-%dT%H:%MZ')
        print(render(rep, mtime))


if __name__ == '__main__':
    main()
