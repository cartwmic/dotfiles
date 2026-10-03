#!/usr/bin/env python3
"""recap-discovery-running-public: real Pi autocomplete/help/current-screen proof."""
import fcntl
import json
import os
from pathlib import Path
import signal
import struct
import tempfile
import termios
from current_screen import CurrentScreen
from public_helpers import PublicPi

before = os.environ.get('RECAP_DISCOVERY_BEFORE') == '1'
evidence = Path(os.environ['RECAP_DISCOVERY_EVIDENCE'])
evidence.mkdir(parents=True, exist_ok=True)
observations = []
screen = CurrentScreen()
with tempfile.TemporaryDirectory(prefix='recap-discovery-') as temporary:
    root = Path(temporary)
    pi = PublicPi(root, terminal=screen, config={'inputBudget': 24000}, environment={'RECAP_PROOF_UX': '1', 'TZ': 'America/Los_Angeles'})
    def resize(columns, rows):
        screen.resize(columns, rows)
        fcntl.ioctl(pi.master, termios.TIOCSWINSZ, struct.pack('HHHH', rows, columns, 0, 0))
        os.kill(pi.process.pid, signal.SIGWINCH); pi.collect(.5)
    def frame(label): return screen.capture(label)['lines']
    def clear():
        os.write(pi.master, b'\x1b'); pi.collect(.15)
        os.write(pi.master, b'\x01\x0b'); pi.collect(.2)
    def published(): return [r for r in pi.records() if r['status'] == 'published']
    def running(label, saved=None):
        lines = frame(label)
        headings = [i for i, line in enumerate(lines) if line.startswith('Recap running')]
        assert len(headings) == 1, (label, lines)
        row = headings[0]
        if saved:
            from current_screen import excerpt
            assert 'GMT' in lines[row] and '202' in lines[row], (label, lines[row])
            first = next(line for line in saved['summary'].splitlines() if line.strip())
            from current_screen import plain
            shown = lines[row + 1].rstrip().removesuffix('...').rstrip()
            assert shown and ' '.join(plain(first).split()).startswith(shown), (label, lines[row + 1])
        rule = next(i for i in range(row + 1, row + 6) if lines[i].startswith('─'))
        assert rule - row <= 4, (label, 'more than three excerpt rows')
        assert all(c.get('faint') for y in range(row, rule) for c in screen.frames[-1]['cells'][y] if c['data'].strip())
    def not_running(label): assert not any(line.startswith('Recap running') for line in frame(label))
    try:
        if 'Trust project folder?' in pi.visible(): os.write(pi.master, b'\x1b[B\r'); pi.collect(2)
        for cols, rows in ((48, 32), (180, 40)):
            resize(cols, rows)
            os.write(pi.master, b'/recap '); pi.collect(.6)
            lines = frame(f'{cols}-space')
            available = any('→ view' in line and 'View the sav' in line for line in lines)
            observations.append({'width': cols, 'native_arguments': available})
            if not before:
                assert available, lines
                os.write(pi.master, b'he')
                pi.wait(lambda: any('→ help' in line for line in screen.screen.display), 'native help completion did not become ready', seconds=5)
                frame(f'{cols}-help-completion-ready')
                os.write(pi.master, b'\t'); pi.collect(.4)
                assert any('/recap help' in line for line in frame(f'{cols}-tab-selected-help'))
                os.write(pi.master, b'\r'); pi.collect(.4)
                assert any('Recap help' in line for line in frame(f'{cols}-help'))
                os.write(pi.master, b'\x1b'); pi.collect(.3)
                for prefix, expected in (('history ', 'all'), ('history all ', 'attempts'), ('history legacy ', 'attempts'), ('settings ', 'defaults')):
                    os.write(pi.master, ('/recap ' + prefix).encode())
                    pi.wait(lambda: any(('→ ' + ('all' if prefix == 'history legacy ' else expected)) in line for line in screen.screen.display), 'context completion did not become ready: ' + prefix, seconds=5)
                    assert any(expected in line for line in frame(f'{cols}-context-{prefix}'))
                    if prefix == 'history legacy ': os.write(pi.master, b'\x1b[B'); pi.collect(.2)
                    os.write(pi.master, b'\t'); pi.collect(.3)
                    assert any('/recap ' + prefix + expected in line for line in frame(f'{cols}-selected-{prefix}'))
                    clear()
            else: clear()
            start = len(pi.output); counts = (len(pi.envelopes()), len(pi.events()))
            pi.send('/recap help')
            guide = any('Recap help' in line for line in frame(f'{cols}-guide'))
            observations.append({'width': cols, 'transient_guide': guide})
            if not before:
                assert guide
                os.write(pi.master, b'\x1b[6~'); pi.collect(.3); frame(f'{cols}-guide-bottom')
                assert 'cancel' in pi.visible(start) and 'not Pi' in pi.visible(start)
                os.write(pi.master, b'\x1b'); pi.collect(.3)
                assert counts == (len(pi.envelopes()), len(pi.events())), 'help generated/reserved'
        pi.send('Inspect orchard', 1)
        pi.gate.touch(); pi.send('/recap')
        pi.wait(lambda: bool(pi.envelopes()) and pi.current(pi.envelopes()[-1]['request_key'])['status'] == 'running', 'backend not genuinely running')
        pi.wait(lambda: bool(pi.calls()), 'gated provider not called')
        first = pi.envelopes()[-1]
        pi.collect(.7)
        shown = any(line.startswith('Recap running') for line in frame('first-gated-running'))
        observations.append({'first_running': shown, 'token': first['token'], 'current': pi.current(first['request_key'])})
        if before:
            assert not shown and all(not o.get('native_arguments', False) and not o.get('transient_guide', False) for o in observations if 'width' in o)
        else:
            running('first-running-180')
            resize(48, 32); running('first-running-48')
        pi.gate.unlink(); pi.wait(lambda: len(published()) == 1, 'first not saved'); pi.collect(1)
        if not before:
            saved = published()[-1]; screen.widget(saved, 'local', pi.env, 'first-completed'); not_running('first-cleared')
            # Public keyboard launcher: real help while tool work and unsent editor draft exist.
            (root / 'tool-gate').touch(); pi.send('Inspect harbor'); pi.collect(.4)
            os.write(pi.master, b'UNSENT_DISCOVERY_DRAFT'); pi.collect(.2)
            counts = (len(pi.envelopes()), len(pi.events()))
            fence = pi.current(first['request_key'])
            os.write(pi.master, b'\x1bh'); pi.collect(.5)
            assert any('Recap help' in line for line in frame('help-during-main-tool'))
            os.write(pi.master, b'\x1b'); pi.collect(.4)
            assert any('UNSENT_DISCOVERY_DRAFT' in line for line in frame('help-preserved-editor'))
            assert counts == (len(pi.envelopes()), len(pi.events())) and fence == pi.current(first['request_key'])
            assert (root / 'tool-gate').exists(), 'help interrupted main'
            os.write(pi.master, b'\x01\x0b'); pi.collect(.2)
            (root / 'tool-gate').unlink(); pi.collect(1)
            assert not any(e['event'] == 'tool-aborted' for e in pi.events()), 'help/editor cleanup aborted main'
            pi.gate.touch(); pi.send('/recap'); pi.wait(lambda: len(pi.envelopes()) == 2, 'second missing'); pi.collect(.7)
            second = pi.envelopes()[-1]; running('saved-plus-running-48', saved)
            resize(180, 40); running('saved-plus-running-180', saved)
            session = next((root / 'sessions').rglob('*.jsonl'))
            pi.send('/reload', 2); running('reload-recovered-running', saved)
            # New request fences old work; its completion must not clear newer running.
            pi.send('/recap full'); pi.wait(lambda: len(pi.envelopes()) == 3, 'newer missing'); pi.collect(1)
            newer = pi.envelopes()[-1]; assert newer['token'] != second['token']
            pi.wait(lambda: pi.terminal(second['token']) is not None, 'old not superseded')
            assert pi.terminal(second['token'])['status'] == 'superseded'
            running('old-terminal-keeps-newer', saved)
            pi.send('/recap cancel')
            pi.wait(lambda: pi.current(newer['request_key'])['status'] == 'canceled', 'public cancel did not change durable fence')
            pi.wait(lambda: not any(line.startswith('Recap running') for line in screen.screen.display), 'cancel did not clear running widget', seconds=10)
            not_running('cancel-clears')
            pi.wait(lambda: pi.terminal(newer['token']) is not None, 'newer not canceled')
            pi.gate.unlink(); (root / 'unfinished').write_text('final')
            pi.send('/recap'); pi.wait(lambda: len(pi.envelopes()) == 4, 'failure request missing')
            failed = pi.envelopes()[-1]
            pi.wait(lambda: pi.terminal(failed['token']) is not None, 'failure not terminal'); pi.collect(1)
            assert pi.terminal(failed['token'])['status'] == 'failed'; not_running('failure-clears'); screen.widget(saved, 'local', pi.env, 'failure-keeps-good')
            (root / 'unfinished').unlink()
            # Virtual preflight is genuinely blocked, including across new/reload.
            pi.send('/recap settings')
            for _ in range(2): os.write(pi.master, b'\x1b[B'); pi.collect(.1)
            pi.send(''); pi.send('')
            pi.wait(lambda: 'Follow current Pi model' in pi.visible(), 'model picker not open')
            for _ in range(5): os.write(pi.master, b'\x1b[B'); pi.collect(.1)
            pi.send(''); os.write(pi.master, b'\x1b'); pi.collect(.5)
            entries = [json.loads(line) for line in session.read_text().splitlines()]
            assert next(e['data']['overrides'].get('model') for e in reversed(entries) if e.get('customType') == 'recap-state') == {'provider': 'recap-router', 'id': 'auto'}
            (root / 'budget-gate').touch(); pi.send('/recap'); pi.wait(lambda: any(e['event'] == 'budget-wait' for e in pi.events()), 'preflight not blocked'); pi.collect(.7)
            virtual = pi.envelopes()[-1]; running('preflight-running', saved)
            pi.send('/new', 1); not_running('new-hides-foreign')
            pi.send('/reload', 2); not_running('reload-no-foreign')
            (root / 'budget-gate').unlink(); pi.wait(lambda: pi.terminal(virtual['token']) is not None, 'departed did not finish')
            assert pi.terminal(virtual['token'])['status'] == 'published'; pi.collect(1); not_running('foreign-finish-no-stale')
            pi.stop(); pi.launch(session); pi.collect(4); not_running('resume-finished-not-running')
            screen.widget(published()[-1], 'local', pi.env, 'resume-recovered-success')
            pi.assert_no_transcript_output()
            observations.append({'after': 'native Tab/context/help Escape/editor/no main interruption; first/saved running; reload/supersession/cancel/failure; virtual preflight/new/foreign finish/resume', 'records': len(pi.records())})
        print(json.dumps({'status': 'EXPECTED_FAIL_BEFORE' if before else 'PASS', 'case': 'recap-discovery-running-public', 'observations': observations}))
    finally:
        (evidence / 'ui.ansi').write_bytes(pi.output)
        (evidence / 'provider.jsonl').write_text(pi.log.read_text() if pi.log.exists() else '')
        (evidence / 'transport.jsonl').write_text(pi.transport.read_text() if pi.transport.exists() else '')
        (evidence / 'records.json').write_text(json.dumps(pi.records(), indent=2))
        (evidence / 'frames.json').write_text(json.dumps(screen.frames, ensure_ascii=False))
        (root / 'tool-gate').unlink(missing_ok=True); (root / 'budget-gate').unlink(missing_ok=True)
        pi.close()
assert not root.exists(), 'private resources remained'
(evidence / 'cleanup.json').write_text(json.dumps({'private_root_removed': not root.exists()}))
