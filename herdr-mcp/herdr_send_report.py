#!/usr/bin/env python3
"""Read-only report: text sends through the Herdr MCP bridge with no matching landing.

The bridge's audit log records, for each text send, an HMAC of the text (text_hash) and its
length, never the text. This report looks for a user message with the same hash in the Pi
session files shortly after each send. A send with none is listed as unmatched: a candidate
for a dropped message (agent busy and message queued, session reloaded, wrong pane, non-Pi
target). It is a candidate, not proof.

Reads only: the audit log and its rotations, the hash key, and Pi session JSONL files (to hash
user messages in memory). Writes nothing and prints no message text. Python 3.9 stdlib only.
Run: /usr/bin/python3 -I -B herdr_send_report.py [--hours N | --since ISO] [--window SECONDS] [--json]
"""
import argparse, datetime, glob, importlib.util, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location('herdr_control_mcp', os.path.join(HERE, 'herdr_control_mcp.py'))
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

LEAD = 2.0  # a landing may be stamped this long before the call started (clock jitter)
SEND_KINDS = {'agent.prompt': 'prompt', 'pane.send_text': 'send-text', 'pane.send_input': 'send-input'}


def parse_ts(value):
    return datetime.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


def kind_of(rec):
    if rec.get('tool') == 'herdr_cli':
        return {'prompt': 'prompt', 'send-text': 'send-text', 'run': 'run'}.get(rec.get('sub'))
    return SEND_KINDS.get(rec.get('method'))


def read_sends(audit_path, since):
    """One dict per hashed send: start and end records joined on the call id."""
    calls = {}
    for path in sorted(glob.glob(audit_path + '.*'), reverse=True) + [audit_path]:
        if path.endswith('.lock'):
            continue
        try:
            handle = open(path, encoding='utf-8')
        except OSError:
            continue
        with handle:
            for line in handle:
                try:
                    rec = json.loads(line)
                    ts = parse_ts(rec['ts'])
                except (ValueError, KeyError, TypeError):
                    continue
                if ts < since or not rec.get('call'):
                    continue
                entry = calls.setdefault(rec['call'], {'call': rec['call']})
                entry['start' if rec.get('event') == 'start' else 'end'] = rec
                entry['start_ts' if rec.get('event') == 'start' else 'end_ts'] = ts
    sends, unhashed = [], 0
    for entry in calls.values():
        rec = entry.get('start') or entry.get('end')
        kind = kind_of(rec)
        if not kind:
            continue
        if not rec.get('text_hash'):
            unhashed += 1
            continue
        end = entry.get('end') or {}
        sends.append({'call': entry['call'], 'kind': kind, 'method': rec.get('method'), 'targets': rec.get('targets', []),
                      'hash': rec['text_hash'], 'len': rec.get('text_len'), 'start': entry.get('start_ts', entry.get('end_ts')),
                      'end': entry.get('end_ts'), 'outcome': end.get('outcome', 'no_end')})
    sends.sort(key=lambda s: s['start'])
    return sends, unhashed


def message_text(message):
    content = message.get('content')
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return '\n'.join(b.get('text', '') for b in content if isinstance(b, dict) and b.get('type') == 'text')
    return ''


def read_landings(sessions_dir, since, key, lengths, hashes):
    """{hash: [timestamps]} for user messages whose hash is one of the sent hashes."""
    found = {}
    for dirpath, _dirs, files in os.walk(sessions_dir):
        for name in files:
            if not name.endswith('.jsonl'):
                continue
            path = os.path.join(dirpath, name)
            try:
                if os.path.getmtime(path) < since - 60:
                    continue
                handle = open(path, encoding='utf-8', errors='replace')
            except OSError:
                continue
            with handle:
                for line in handle:
                    if '"user"' not in line:
                        continue
                    try:
                        entry = json.loads(line)
                        message = entry['message']
                        if entry.get('type') != 'message' or message.get('role') != 'user':
                            continue
                        stamp = message.get('timestamp')
                        ts = stamp / 1000.0 if isinstance(stamp, (int, float)) else parse_ts(entry['timestamp'])
                    except (ValueError, KeyError, TypeError):
                        continue
                    text = bridge.normalize_text(message_text(message))
                    if len(text) not in lengths:
                        continue
                    digest = bridge.hash_text(text, key)
                    if digest in hashes:
                        found.setdefault(digest, []).append(ts)
    for stamps in found.values():
        stamps.sort()
    return found


def match(sends, landings, window, now):
    """Each landing satisfies at most one send. A send is judged only after its window closed."""
    result = []
    for send in sends:
        if send['outcome'] in ('not_sent', 'rejected', 'error'):
            result.append((send, 'not_delivered', None))
            continue
        high = (send['end'] or send['start']) + window
        pool = landings.get(send['hash'], [])
        hit = next((t for t in pool if send['start'] - LEAD <= t <= high), None)
        if hit is not None:
            pool.remove(hit)
            result.append((send, 'landed', hit - send['start']))
        elif now < high:
            result.append((send, 'pending', None))
        else:
            result.append((send, 'unmatched', None))
    return result


def iso(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def main(argv=None):
    ap = argparse.ArgumentParser(description='List bridge text sends with no matching landing (read-only).')
    ap.add_argument('--hours', type=float, default=24, help='look back this many hours (default 24)')
    ap.add_argument('--since', help='ISO time (UTC) instead of --hours')
    ap.add_argument('--window', type=float, default=300, help='seconds after the call that a landing still counts (default 300)')
    ap.add_argument('--target', help='only sends whose recorded targets include this id, e.g. w1:p2')
    ap.add_argument('--audit-log', default=bridge.AUDIT_PATH)
    ap.add_argument('--sessions-dir', default=os.path.expanduser('~/.pi/agent/sessions'))
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args(argv)
    now = datetime.datetime.now(datetime.timezone.utc).timestamp()
    try:
        since = parse_ts(args.since) if args.since else now - args.hours * 3600
    except ValueError:
        ap.error('--since must be an ISO time such as 2026-10-20T00:00:00Z')
    key = bridge.load_hash_key(create=False)
    if key is None:
        print('herdr-send-report: no text-hash key at %s; the bridge creates it on its first text send' % bridge.HASH_KEY_PATH,
              file=sys.stderr)
        return 2
    sends, unhashed = read_sends(args.audit_log, since)
    if args.target:
        sends = [s for s in sends if args.target in s['targets']]
    candidates = [s for s in sends if s['kind'] != 'run']  # 'pane run' types into shells, which have no Pi session to land in
    landings = read_landings(args.sessions_dir, since, key, {s['len'] for s in candidates if isinstance(s['len'], int)},
                             {s['hash'] for s in candidates}) if candidates else {}
    judged = match(candidates, landings, args.window, now)
    counts = {}
    for _send, verdict, _lag in judged:
        counts[verdict] = counts.get(verdict, 0) + 1
    summary = {'since': iso(since), 'window_s': args.window, 'sends_checked': len(judged), 'counts': counts,
               'shell_runs_not_checked': len(sends) - len(candidates), 'sends_without_hash': unhashed}
    unmatched = [s for s, v, _ in judged if v == 'unmatched']
    if args.json:
        json.dump({'summary': summary,
                   'unmatched': [dict(s, start=iso(s['start']), end=iso(s['end']) if s['end'] else None) for s in unmatched]},
                  sys.stdout, indent=1)
        print()
        return 0
    print('Bridge text sends since %s: %d checked, landing window %ds' % (summary['since'], len(judged), args.window))
    print('  ' + ', '.join('%s %d' % (k, counts[k]) for k in sorted(counts)) if counts else '  none')
    if summary['shell_runs_not_checked'] or unhashed:
        print('  not checked: %d pane-run sends (shells), %d sends recorded before the hash existed' % (summary['shell_runs_not_checked'], unhashed))
    if unmatched:
        print('Unmatched sends (no user message with the same hash in a Pi session; candidates, not proof):')
        for s in unmatched:
            print('  %s  %s  %-9s %-14s targets=%s len=%s hash=%s outcome=%s' % (
                iso(s['start']), s['call'][:8], s['kind'], s['method'], ','.join(s['targets']) or '-', s['len'], s['hash'][:11], s['outcome']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
