#!/usr/bin/env python3
"""Real Pi history viewer must fit phone and wide terminals without crashing."""
import fcntl
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import tempfile
import termios
from public_helpers import PublicPi

with tempfile.TemporaryDirectory(prefix='recap-viewer-width-') as temporary:
    root = Path(temporary)
    pi = PublicPi(root)
    observations = []
    try:
        # Seed a genuinely generated generic record for the real Pi session.
        # This regression isolates history rendering, not SDK generation.
        if 'Trust project folder?' in pi.visible():
            os.write(pi.master, b'\x1b[B\r')
            pi.collect(3)
        pi.send('Inspect orchard')
        pi.wait(lambda: any(e.get('event') == 'settled' for e in pi.events()), 'scripted work did not settle')
        entries = [json.loads(line) for f in (root / 'sessions').rglob('*.jsonl') for line in f.read_text().splitlines()]
        owned = next(e['data'] for e in reversed(entries) if e.get('customType') == 'recap-state')
        config = root / 'config/session-recap'
        config.mkdir(parents=True)
        backend = root / 'history-backend.py'
        backend.write_text('import sys\nsys.stdout.write(sys.stdin.read())\n')
        (config / 'config.toml').write_text('command = ' + json.dumps([sys.executable, str(backend)]) + '\n')
        (config / 'single-prompt.md').write_text('[[TEXT]]')
        (config / 'group-prompt.md').write_text('[[MEMBERS]]')
        metadata = {'pi': {'historyId': owned['historyId'], 'nativeSessionId': owned['nativeSessionId'],
                           'sessionId': owned['nativeSessionId'], 'trigger': 'manual'}}
        narrative = 'Observed orchard: checks passed; review remains pending.\n' + '\n'.join(
            f'Observed orchard: retained detail {i}; check evidence remains available.' for i in range(1, 41))
        result = subprocess.run([sys.executable, pi.env['GENUINE_RECAP_CLI'], 'create', '--kind', 'single',
                                 '--source-kind', 'pi', '--source-id', owned['historyId'],
                                 '--metadata-json', json.dumps(metadata)],
                                input=narrative, env=pi.env, text=True, capture_output=True, timeout=30)
        assert result.returncode == 0, result.stderr
        saved = next(r for r in pi.records() if r['record_id'] == result.stdout.strip())
        assert len(saved['record_id'] + ' ' + saved['created_at'] + ' published — ↑↓ scroll, Esc close') > 48
        assert 'retained detail 40' in saved['summary']
        main_calls = sum(e.get('model') == 'main' for e in pi.events())
        recap_calls = len(pi.calls())
        for columns, rows in ((48, 32), (180, 40)):
            fcntl.ioctl(pi.master, termios.TIOCSWINSZ, struct.pack('HHHH', rows, columns, 0, 0))
            os.kill(pi.process.pid, signal.SIGWINCH)
            pi.collect(1)
            start = len(pi.output)
            pi.send('/recap history', 2)
            assert 'Recap history' in pi.visible(start), 'searchable selector did not open'
            pi.send('', 2)
            shown = pi.visible(start)
            assert pi.process.poll() is None, ('Pi crashed opening viewer', columns)
            assert 'Esc close' in shown and 'Observed orchard:' in shown, 'viewer header/body missing'
            assert 'exceeds terminal width' not in shown, 'renderer overflow'
            start = len(pi.output)
            os.write(pi.master, b'\x1b[6~')
            pi.collect(2)
            assert pi.process.poll() is None, ('Pi crashed scrolling viewer', columns)
            # PageDown must reveal later narrative, not just accept a key.
            assert 'retained detail' in pi.visible(start), 'page scroll did not render later narrative'
            os.write(pi.master, b'\x1b')
            pi.collect(2)
            assert pi.process.poll() is None, ('Pi crashed leaving viewer', columns)
            observations.append(f'{columns}x{rows}-history-open-wrapped-header-body-page-scroll-escape')
        assert len(pi.calls()) == recap_calls, 'history caused recap generation'
        assert sum(e.get('model') == 'main' for e in pi.events()) == main_calls, 'history caused foreground turn'
        assert len([r for r in pi.records() if r['status'] == 'published']) == 1
        pi.assert_no_transcript_output()
    except Exception:
        print(pi.visible()[-16000:], file=sys.stderr)
        raise
    finally:
        pi.close()
assert not root.exists(), 'private resources not removed'
print(json.dumps({'status': 'PASS', 'cases': observations,
                  'history_generation_calls': 0, 'foreground_extra_turns': 0,
                  'cleanup': 'owned Pi and supervisor exited; private resources removed'}))
