#!/usr/bin/env python3
"""Focused genuine Pi UX/default/model/timezone proof; no owner resources."""
import fcntl
import hashlib
import json
import os
import re
from pathlib import Path
import signal
import struct
import sys
import tempfile
import termios
from public_helpers import PublicPi
from current_screen import CurrentScreen

screen = CurrentScreen()
observed = []
with tempfile.TemporaryDirectory(prefix='recap-ux-followup-') as temporary:
    root = Path(temporary)
    pi = PublicPi(root, seed_defaults=True, config={'intervalMinutes': .02},
                  terminal=screen, agent_settings={'compaction': {'enabled': True, 'keepRecentTokens': 1, 'reserveTokens': 1000}},
                  environment={'RECAP_PROOF_UX': '1', 'RECAP_PROOF_COMPACTION': 'manual', 'TZ': 'America/Los_Angeles'})
    def published(): return [r for r in pi.records() if r['status'] == 'published']
    def resize(columns, rows):
        screen.resize(columns, rows)
        fcntl.ioctl(pi.master, termios.TIOCSWINSZ, struct.pack('HHHH', rows, columns, 0, 0))
        os.kill(pi.process.pid, signal.SIGWINCH)
        pi.collect(.7)
    def wait_saved(count):
        pi.wait(lambda: len(published()) >= count, 'expected genuine saved recap')
        pi.collect(.8)
    def delivered_widget(record, zone, label):
        result = []
        def ready():
            try: result[:] = screen.widget(record, zone, pi.env, label); return True
            except AssertionError: return False
        pi.wait(ready, 'saved record never reached expected current muted widget: ' + label, seconds=10)
        return result
    def model(name):
        pi.send('/model recap-proof/' + name, .7)
    try:
        if 'Trust project folder?' in pi.visible():
            os.write(pi.master, b'\x1b[B\r'); pi.collect(3)
        seed = json.loads((pi.extension / 'config.json').read_text())
        assert all(seed[k] for k in ('completed', 'periodic', 'beforeCompaction')) and seed['model'] is None
        resize(48, 32)
        pi.send('Inspect orchard')
        wait_saved(1)
        first = published()[0]
        assert first['metadata']['pi']['trigger'] == 'settlement'
        assert first['backend_identity']['model'] == 'main'
        assert 'orchard-checks-passed' in first['summary'] and 'orchard-review-before-deploy' in first['summary']
        assert 'Recap updated' in pi.visible() and '詳しい' not in pi.visible(), 'automatic narrative dumped'
        screen.widget(first, 'local', pi.env, '48x32-first-save')
        observed.append('default-on settlement uses captured current main model, saves input-derived narrative quietly')
        for columns, rows in ((48, 32), (180, 40)):
            resize(columns, rows)
            screen.widget(first, 'local', pi.env, f'{columns}x{rows}-saved')
            start = len(pi.output)
            pi.send('/recap settings')
            assert 'null follows current Pi model' in pi.visible(start)
            assert 'After final response, error or abort' in pi.visible(start)
            assert 'Progress only while Pi is active' in pi.visible(start)
            assert '(inherited)' in pi.visible(start)
            for _ in range(14): os.write(pi.master, b'\x1b[B'); pi.collect(.05)
            assert 'Display only: local, UTC or IANA zone' in pi.visible(start)
            os.write(pi.master, b'\x1b'); pi.collect(.4)
            envelopes_before = len(pi.envelopes())
            foreground_before = sum(e['event'] == 'call' and 'number' not in e for e in pi.events())
            current_before = pi.current(pi.envelopes()[-1]['request_key'])
            start = len(pi.output)
            pi.send('/recap view')
            assert 'Observed orchard' in pi.visible(start) and 'Esc close' in pi.visible(start)
            for _ in range(20): os.write(pi.master, b'\x1b[6~'); pi.collect(.15)
            assert '詳しい36' in pi.visible(start), 'PageDown did not expose saved end'
            os.write(pi.master, b'\x1b'); pi.collect(.4)
            assert len(pi.envelopes()) == envelopes_before
            assert pi.current(pi.envelopes()[-1]['request_key']) == current_before, 'view changed reservation/coverage'
            assert sum(e['event'] == 'call' and 'number' not in e for e in pi.events()) == foreground_before
            assert pi.process.poll() is None and 'exceeds terminal width' not in pi.visible(start)
            screen.widget(first, 'local', pi.env, f'{columns}x{rows}-after-view')
            observed.append(f'{columns}x{rows}: muted per-field inherited help, compact saved widget, full saved view/PageDown/Escape, no reservation or generation/foreground turn')
        # Persisted session timezone changes presentation but not matching full reuse.
        start = len(pi.output)
        pi.send('/recap full'); wait_saved(2)
        assert '詳しい36' not in pi.visible(start), 'manual narrative dumped instead of compact widget'
        full = published()[-1]
        screen.widget(full, 'local', pi.env, 'manual-full-save')
        before = len(pi.envelopes())
        pi.setting('timeZone', 'America/New_York')
        # Reject invalid timezone through the real session settings input.
        start = len(pi.output)
        pi.send('/recap settings')
        for _ in range(14): os.write(pi.master, b'\x1b[B'); pi.collect(.03)
        pi.send(''); pi.send(''); os.write(pi.master, b'\x01\x0b')
        pi.send('"Not/AZone"'); os.write(pi.master, b'\x1b'); pi.collect(.4)
        assert 'Invalid setting' in pi.visible(start)
        # Defaults edits stay separate from a saved session override.
        pi.send('/recap settings defaults')
        for _ in range(14): os.write(pi.master, b'\x1b[B'); pi.collect(.03)
        pi.send(''); pi.send(''); os.write(pi.master, b'\x01\x0b')
        pi.send('"UTC"'); os.write(pi.master, b'\x1b'); pi.collect(.4)
        assert json.loads((pi.extension / 'config.json').read_text())['timeZone'] == 'UTC'
        start = len(pi.output)
        pi.send('/recap full', 1)
        assert len(pi.envelopes()) == before and len(published()) == 2, 'timezone invalidated full reuse'
        assert 'Reused matching full recap' in pi.visible(start)
        assert 'America/New_York' in pi.visible(), 'widget zone not refreshed'
        stable_widget = screen.widget(full, 'America/New_York', pi.env, 'timezone-full-reuse')
        pi.send('/recap', 1)
        assert len(pi.envelopes()) == before and len(published()) == 2, 'no-new activity generated work'
        assert screen.widget(full, 'America/New_York', pi.env, 'manual-no-new') == stable_widget
        session = next((root / 'sessions').rglob('*.jsonl'))
        pi.stop(); pi.launch(session); pi.collect(4)
        if 'Trust project folder?' in pi.visible(): os.write(pi.master, b'\x1b[B\r'); pi.collect(2)
        start = len(pi.output)
        pi.send('/recap view')
        assert 'America/New_York' in pi.visible(start) and 'Observed orchard' in pi.visible(start), 'resume presentation missing'
        os.write(pi.master, b'\x1b'); pi.collect(.4)
        before_reload = len(pi.envelopes())
        pi.send('/reload', 2)
        start = len(pi.output); pi.send('/recap view')
        assert 'America/New_York' in pi.visible(start) and 'Observed orchard' in pi.visible(start), 'reload lost current saved view'
        os.write(pi.master, b'\x1b'); pi.collect(.4)
        start = len(pi.output); pi.send('/recap history')
        assert 'GMT' in pi.visible(start) and 'America/New_York' in pi.visible(start), 'history labels ignored timezone'
        os.write(pi.master, b'\x1b'); pi.collect(.4)
        assert len(pi.envelopes()) == before_reload, 'reload/view/history generated work'
        observed.append('manual full quiet save, invalid timezone rejected, separate defaults UTC/session New York edits, timezone preserved on resume/reload/history, timezone-only full reuse makes no request')
        # A gated old capture retains its model across a main model switch.
        pi.setting('completed', False)
        pi.setting('periodic', False)
        pi.gate.touch()
        pi.send('Inspect harbor')
        pi.wait(lambda: any(e.get('event') == 'settled' and e.get('time', 0) > 0 for e in pi.events()[len(pi.events())-2:]), 'harbor did not settle', seconds=10)
        pi.send('/recap')
        pi.wait(lambda: len(pi.envelopes()) > before, 'old request not captured')
        old = pi.envelopes()[-1]
        assert old['selection']['model']['id'] == 'main'
        model('main-next')
        pi.gate.unlink()
        wait_saved(3)
        assert published()[-1]['backend_identity']['model'] == 'main'
        pi.send('Inspect orchard', 1)
        pi.send('/recap'); wait_saved(4)
        assert pi.envelopes()[-1]['selection']['model']['id'] == 'main-next'
        assert published()[-1]['backend_identity']['model'] == 'main-next'
        # The actual picker sets an independent override while main stays main-next.
        pi.send('/recap settings')
        for _ in range(2): os.write(pi.master, b'\x1b[B'); pi.collect(.05)
        pi.send(''); pi.send('')
        pi.wait(lambda: 'Follow current Pi model' in pi.visible(), 'model picker missing')
        # Picker sorted by catalog: navigate to label containing recap-proof/recap.
        for _ in range(3): os.write(pi.master, b'\x1b[B'); pi.collect(.08)
        pi.send(''); os.write(pi.master, b'\x1b'); pi.collect(.4)
        entries = [json.loads(line) for line in session.read_text().splitlines()]
        override = next(e['data']['overrides'].get('model') for e in reversed(entries) if e.get('customType') == 'recap-state')
        assert override == {'provider': 'recap-proof', 'id': 'recap'}, ('picker chose wrong model', override)
        model('main')
        pi.send('Inspect harbor', 1); pi.send('/recap'); wait_saved(5)
        assert pi.envelopes()[-1]['selection']['model']['id'] == 'recap'
        observed.append('old captured main identity survives switch; next capture follows main-next; picker override remains recap after main switch')
        # Return to seed policy using public Clear override for model and trigger fields.
        def clear(field):
            fields = list(seed)
            pi.send('/recap settings')
            for _ in range(fields.index(field) + 2): os.write(pi.master, b'\x1b[B'); pi.collect(.03)
            pi.send(''); os.write(pi.master, b'\x1b[B'); pi.collect(.1); pi.send('')
            os.write(pi.master, b'\x1b'); pi.collect(.3)
        for field in ('model', 'completed', 'periodic'): clear(field)
        tool_gate = root / 'tool-gate'; tool_gate.touch()
        count = len(published())
        pi.send('Inspect orchard')
        pi.wait(lambda: any(r['metadata']['pi']['trigger'] == 'periodic' for r in published()[count:]), 'default active periodic did not publish', seconds=15)
        count = len(published()); calls = len(pi.envelopes())
        latest = published()[-1]
        stable_widget = delivered_widget(latest, 'America/New_York', 'periodic-save')
        # A nonempty unsent draft must survive async public delivery/repaints.
        os.write(pi.master, b'UNSENT_DRAFT_orchard'); pi.collect(.3)
        pi.collect(3)
        assert any('UNSENT_DRAFT_orchard' in line for line in screen.capture('periodic-draft')['lines'])
        assert screen.widget(latest, 'America/New_York', pi.env, 'periodic-no-new') == stable_widget
        # Kill this real editor text; viewer must preserve the real kill ring.
        os.write(pi.master, b'\x01\x0b'); pi.collect(.2)
        # Independent active periodic no-new checks above legitimately reserve
        # tokens. Disable that public timer before isolating VIEW's fence effect.
        pi.setting('periodic', False)
        event_boundary = len(pi.events())
        foreground_before = sum(e['event'] == 'call' and 'number' not in e for e in pi.events())
        fence = pi.current(pi.envelopes()[-1]['request_key'])
        assert len(published()) == count and len(pi.envelopes()) == calls, 'silent no-new progress generated duplicate'
        start = len(pi.output)
        pi.send('/recap view', .5)
        latest = published()[-1]
        assert latest['summary'].split(':')[0] in pi.visible(start), 'view omitted current saved narrative'
        assert tool_gate.exists(), 'view interrupted foreground work'
        os.write(pi.master, b'\x1b'); pi.collect(.3)
        while_closed = pi.events()[event_boundary:]
        assert not any(e['event'] in ('tool-aborted', 'tool-completed', 'tool-end', 'settled') for e in while_closed), ('foreground interrupted', while_closed)
        assert sum(e['event'] == 'call' and 'number' not in e for e in pi.events()) == foreground_before
        assert pi.current(pi.envelopes()[-1]['request_key']) == fence, 'view changed busy fence'
        os.write(pi.master, b'\x19'); pi.collect(.3)
        assert any('UNSENT_DRAFT_orchard' in line for line in screen.capture('viewer-restored-killring')['lines'])
        # Keep draft present during the actual fresh settlement/save delivery.
        release_boundary = len(pi.events())
        tool_gate.unlink(); wait_saved(count + 1)
        after_release = pi.events()[release_boundary:]
        assert any(e['event'] == 'tool-completed' and not e['aborted'] for e in after_release)
        assert any(e['event'] == 'tool-end' and not e['isError'] for e in after_release)
        assert any(e['event'] == 'settled' for e in after_release)
        assert not any(e['event'] == 'tool-aborted' for e in after_release)
        assert published()[-1]['metadata']['pi']['trigger'] == 'settlement'
        assert 'orchard-checks-passed' in published()[-1]['summary']
        assert any('UNSENT_DRAFT_orchard' in line for line in screen.capture('async-save-retained-draft')['lines'])
        screen.widget(published()[-1], 'America/New_York', pi.env, 'fresh-settlement-save')
        os.write(pi.master, b'\x01\x0b'); pi.collect(.2)
        calls = len(pi.envelopes()); pi.collect(2)
        assert len(pi.envelopes()) == calls, 'idle generation'
        observed.append('default active periodic (disclosed 1.2s test interval), quiet no-new/no duplicate, view while foreground tool active, final settlement and idle stop')
        # Default pre-compaction must generate removed public material, not a reused recap.
        pi.setting('mode', 'full')
        pi.setting('instructions', 'Recap the pre-compaction captured evidence and pending work.')
        count = len(published())
        pi.send('/compact', 1)
        pi.wait(lambda: any(e['event'] == 'compacted' for e in pi.events()), 'native compaction failed')
        wait_saved(count + 1)
        assert published()[-1]['metadata']['pi']['trigger'] == 'before-compaction'
        assert 'orchard-checks-passed' in published()[-1]['summary']
        envelope = pi.envelopes()[-1]
        recap_call = [e for e in pi.events() if e['event'] == 'call' and 'number' in e][-1]
        for fact in ('FACT_result=orchard-checks-passed', 'FACT_result=harbor-checks-passed'):
            assert fact in envelope['material'], 'fact available only in prior background'
            assert fact in recap_call['prompt'] and envelope['material'] in recap_call['prompt']
            assert fact not in json.dumps([e for e in pi.events() if e['event'] == 'compacted'][-1]['projection'])
            assert fact.split('=')[1] in published()[-1]['summary']
        screen.widget(published()[-1], 'America/New_York', pi.env, 'compaction-save')
        observed.append('default-on before-compaction genuine native compaction plus captured evidence save')
        # Real tree navigation must hide the abandoned branch recap immediately.
        calls = len(pi.envelopes())
        start = len(pi.output)
        pi.send('/tree', .7)
        clean_tree = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', pi.visible(start))
        position = int(re.findall(r'\((\d+)/(\d+)\)', clean_tree)[-1][0])
        for _ in range(position - 2): os.write(pi.master, b'\x1b[A'); pi.collect(.03)
        pi.send('', .7)
        if 'Summarize branch?' in pi.visible(start): pi.send('', .7)
        os.write(pi.master, b'\x01\x0b'); pi.collect(.2)
        screen.absent('immediate-abandoned-tree')
        start = len(pi.output); pi.send('/recap view')
        assert 'No saved recap for this branch' in pi.visible(start), 'tree displayed abandoned recap'
        assert len(pi.envelopes()) == calls
        pi.send('/fork', .7); pi.send('', 1)
        os.write(pi.master, b'\x01\x0b'); pi.collect(.2)
        start = len(pi.output); pi.send('/recap view')
        assert 'No saved recap for this branch' in pi.visible(start), 'fork imported parent recap'
        screen.absent('immediate-fork')
        assert len(pi.envelopes()) == calls
        observed.append('real tree abandoned-branch and fork isolation: no saved view, no generation')
        # Fresh session must not inherit the compact recap. Viewer cannot create a job.
        pi.send('/new', 1)
        screen.absent('immediate-new')
        start = len(pi.output); pi.send('/recap view')
        assert 'No saved recap for this branch' in pi.visible(start)
        assert len(pi.envelopes()) == calls
        pi.assert_no_transcript_output()
        for path in (root / 'sessions').rglob('*.jsonl'):
            for line in path.read_text().splitlines():
                entry = json.loads(line)
                if entry.get('type') == 'message': assert '詳しい36' not in line, 'recap narrative entered transcript'
        observed.append('new-session saved-view isolation and no recap/helper transcript messages')
        # Resume the exact original file via public Pi CLI, preserving branch selection.
        pi.stop(); pi.launch(session); pi.collect(4)
        pi.send('/tree', .7)
        # Reach the original last branch using supported ordinary arrows, not
        # terminal End (the public tree need not implement it).
        clean_tree = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', pi.visible())
        position, total = map(int, re.findall(r'\((\d+)/(\d+)\)', clean_tree)[-1])
        for _ in range(total - position): os.write(pi.master, b'\x1b[B'); pi.collect(.03)
        pi.send('', .7)
        if 'Summarize branch?' in pi.visible(): pi.send('', .7)
        os.write(pi.master, b'\x01\x0b'); pi.collect(.3)
        screen.widget(published()[-1], 'America/New_York', pi.env, 'original-resumed-restored')
        print(json.dumps({'status': 'PASS', 'observations': observed, 'interval': '1.2 seconds instead of production 15 minutes', 'runtime': 'pi 0.99.2', 'record_count': len(published())}))
    except Exception:
        print(json.dumps({'status': 'FAIL', 'observations_completed': observed}), file=sys.stderr)
        print(pi.visible()[-22000:], file=sys.stderr)
        raise
    finally:
        evidence = Path(os.environ['RECAP_UX_EVIDENCE']) if 'RECAP_UX_EVIDENCE' in os.environ else None
        if evidence:
            evidence.mkdir(parents=True, exist_ok=True)
            (evidence / 'ui.ansi').write_bytes(pi.output)
            (evidence / 'provider.jsonl').write_text(pi.log.read_text() if pi.log.exists() else '')
            (evidence / 'transport.jsonl').write_text(pi.transport.read_text() if pi.transport.exists() else '')
            (evidence / 'records.json').write_text(json.dumps(pi.records(), indent=2))
            (evidence / 'frames.json').write_text(json.dumps(screen.frames, ensure_ascii=False, indent=2))
        (root / 'tool-gate').unlink(missing_ok=True)
        pi.close()
assert not root.exists(), 'private resources remained'
