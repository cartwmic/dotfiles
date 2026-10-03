#!/usr/bin/env python3
"""Private real-Pi manual, history, settings/resume and branch journeys."""
import json
import fcntl
import struct
import termios
import os
from pathlib import Path
import pty
import select
import shutil
import subprocess
import tempfile
import time
ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'dot_pi/private_agent/extensions/recap'
with tempfile.TemporaryDirectory(prefix='recap-manual-') as temporary:
    root = Path(temporary)
    extension = root / 'recap'
    shutil.copytree(SOURCE, extension)
    agent = root / 'agent'
    (agent / 'extensions').mkdir(parents=True)
    fixture = agent / 'extensions/fixture.ts'
    shutil.copy(SOURCE / 'automation-fixture.ts', fixture)
    fixture.write_text(fixture.read_text().replace("'PROOF_RECAP public progress and next steps.'", "Array.from({ length: 65 }, (_, i) => `PROOF_RECAP_LINE_${i} public progress and next steps.`).join('\\n')"))
    (extension / 'config.json').write_text(json.dumps({'mode': 'full', 'completed': False, 'periodic': False, 'beforeCompaction': False}))
    log = root / 'events.jsonl'
    wrapper_dir = root / '.local/bin'
    wrapper_dir.mkdir(parents=True)
    shutil.copy(ROOT / 'dot_local/bin/executable_session-recap', wrapper_dir / 'session-recap')
    (wrapper_dir / 'session-recap').chmod(0o700)
    env = dict({k: os.environ[k] for k in ('PATH', 'TERM', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TMPDIR') if k in os.environ}, HOME=str(root), XDG_CONFIG_HOME=str(root / 'config'), PI_CODING_AGENT_DIR=str(agent), XDG_DATA_HOME=str(root / 'data'), PI_OFFLINE='1', PI_RECAP_CLI=str(ROOT / 'dot_local/share/session-recap/session_recap.py'), RECAP_PROOF_LOG=str(log), RECAP_PROOF_GATE=str(root / 'gate'))
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 36, 140, 0, 0))
    process = subprocess.Popen(['pi', '--offline', '--no-extensions', '--no-skills', '--no-prompt-templates', '--no-context-files', '--session-dir', str(root / 'sessions'), '--provider', 'recap-proof', '--model', 'main', '-e', str(fixture), '-e', str(extension / 'index.ts')], stdin=slave, stdout=slave, stderr=slave, env=env)
    slave_name = os.ttyname(slave)
    os.close(slave)
    output = bytearray()
    def collect(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if select.select([master], [], [], .05)[0]:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break
    def send(text, seconds=3):
        os.write(master, text.encode() + b'\r')
        collect(seconds)
    def calls():
        return [json.loads(line) for line in log.read_text().splitlines() if json.loads(line).get('model') == 'recap']
    def records():
        return json.loads(subprocess.check_output(['python3', env['PI_RECAP_CLI'], 'list', '--json'], env=env))['records']
    try:
        collect(4)
        send('silent-case', 9)
        send('/recap', 1)
        assert 'Recap model (independent of session model)' in output.decode(errors='replace'), 'first useful recap skipped setup'
        # Select exact independent backend, then persist for future sessions.
        os.write(master, b'\x1b[B'); send('', 1)
        assert 'Save recap model' in output.decode(errors='replace'), 'setup did not offer persistence scope'
        os.write(master, b'\x1b[B'); send('', 4)
        assert json.loads((extension / 'config.json').read_text())['model'] == {'provider': 'recap-proof', 'id': 'recap'}, ('setup did not persist exact backend defaults', json.loads((extension / 'config.json').read_text()))
        assert len(calls()) == 1, calls()
        assert [r for r in records() if r['status'] == 'published'][0]['metadata']['pi']['mode'] == 'incremental', 'bare manual inherited automatic full mode'
        assert 'PROOF_TOOL_RESULT' in calls()[0]['prompt'] and 'PROOF_FINAL' in calls()[0]['prompt'], calls()
        send('/recap')
        assert len(calls()) == 1, 'no-new manual generated again'
        send('/recap full')
        assert len(calls()) == 2, calls()
        send('/recap full')
        assert len(calls()) == 2, 'matching full recap not reused'
        saved = [r for r in records() if r['status'] == 'published']
        assert len(saved) == 2, saved
        assert 'PROOF_RECAP' in output.decode(errors='replace'), 'manual recap not displayed'
        # Type a unique record ID into the real filter; Enter must open that record.
        target = saved[0]['record_id']
        send('/recap history', 1)
        os.write(master, target.encode()); collect(1)
        before_selection = len(output)
        send('', 1)
        assert target in output[before_selection:].decode(errors='replace'), 'typed filter selected a different record'
        assert 'scroll, Esc close' in output.decode(errors='replace'), 'history selection did not open viewer'
        before = len(output)
        os.write(master, b'\x1b[6~'); collect(1)
        assert 'PROOF_RECAP_LINE_18' in output[before:].decode(errors='replace'), 'history page-down did not expose later text'
        os.write(master, b'\x1b'); collect(1)
        assert len(calls()) == 2, 'history unexpectedly generated recap'
        send('/recap settings', 1)
        assert 'Recap session settings' in output.decode(errors='replace') and '(inherited)' in output.decode(errors='replace'), 'session settings did not expose inheritance'
        # Set cadence through the public settings dialog (row 2 + field index 5).
        for _ in range(7):
            os.write(master, b'\x1b[B'); collect(.1)
        send('', .5)  # cadence action
        send('', .5)  # Set
        os.write(master, b'\x01\x0b'); send('3', 1)
        os.write(master, b'\x1b'); collect(1)
        session_paths = list((root / 'sessions').rglob('*.jsonl'))
        entries = [json.loads(line) for path in session_paths for line in path.read_text().splitlines()]
        assert any(e.get('customType') == 'recap-state' and e.get('data', {}).get('overrides', {}).get('cadence') == 3 for e in entries), 'settings change not persisted in session'
        assert json.loads((extension / 'config.json').read_text()).get('cadence') is None, 'session override changed defaults'
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait()
        resumed_slave = os.open(slave_name, os.O_RDWR)
        fcntl.ioctl(resumed_slave, termios.TIOCSWINSZ, struct.pack('HHHH', 36, 140, 0, 0))
        process = subprocess.Popen(['pi', '--offline', '--no-extensions', '--no-skills', '--no-prompt-templates', '--no-context-files', '--session-dir', str(root / 'sessions'), '--session', str(session_paths[0]), '--provider', 'recap-proof', '--model', 'main', '-e', str(fixture), '-e', str(extension / 'index.ts')], stdin=resumed_slave, stdout=resumed_slave, stderr=resumed_slave, env=env)
        os.close(resumed_slave)
        collect(4)
        before = len(output)
        send('/recap settings', 1)
        resumed_output = output[before:].decode(errors='replace')
        assert 'cadence: 3' in resumed_output and 'cadence: 3 (inherited)' not in resumed_output, 'resume lost session override'
        os.write(master, b'\x1b'); collect(1)
        # Change defaults via the public dialog, not by rewriting the fixture config.
        send('/recap settings defaults', 1)
        for _ in range(7):
            os.write(master, b'\x1b[B'); collect(.1)
        send('', .5); send('', .5)
        os.write(master, b'\x01\x0b'); send('5', 1)
        os.write(master, b'\x1b'); collect(1)
        assert json.loads((extension / 'config.json').read_text())['cadence'] == 5, 'defaults dialog did not persist cadence'
        before = len(output)
        send('/recap settings', 1)
        assert 'cadence: 3' in output[before:].decode(errors='replace'), 'changed default replaced explicit session override'
        # Clear the override through the same dialog; effective value must now inherit 5.
        for _ in range(7):
            os.write(master, b'\x1b[B'); collect(.1)
        send('', .5)
        os.write(master, b'\x1b[B'); send('', 1)
        assert 'cadence: 5 (inherited)' in output[before:].decode(errors='replace'), 'cleared override did not inherit changed default'
        os.write(master, b'\x1b'); collect(1)
        # Public clone must preserve source activity but allocate independent recap history.
        original_history = saved[-1]['metadata']['pi']['historyId']
        before_calls = len(calls())
        send('/clone', 2)
        assert 'Cloned to new session' in output.decode(errors='replace'), 'clone command did not finish'
        send('/recap', 4)
        assert len(calls()) == before_calls + 1, 'clone reused parent baseline'
        clone_record, = [r for r in records() if r['status'] == 'published' and r['record_id'] not in {s['record_id'] for s in saved}]
        assert clone_record['metadata']['pi']['historyId'] != original_history, 'clone shared parent recap history'
        assert 'PROOF_TOOL_RESULT' in calls()[-1]['prompt'], 'clone failed to recap inherited activity'
        assert calls()[-1]['model'] == 'recap', 'future clone failed to inherit first-use backend default'
        before = len(output)
        send('/recap history', 1)
        os.write(master, clone_record['record_id'].encode()); collect(1)
        send('', 1)
        assert clone_record['record_id'] in output[before:].decode(errors='replace'), 'clone history omitted own record'
        os.write(master, b'\x1b'); collect(1)
        before = len(output)
        send('/recap history', 1)
        os.write(master, saved[0]['record_id'].encode()); collect(1)
        send('', 1)
        assert 'scroll, Esc close' not in output[before:].decode(errors='replace'), 'clone history leaked parent records'
        os.write(master, b'\x1b'); collect(1)
        send('fork-followup', 9)
        before_calls = len(calls())
        send('/fork', 1); send('', 2)
        assert 'Forked to new session' in output.decode(errors='replace'), 'fork selection did not finish'
        os.write(master, b'\x01\x0b'); send('fork-independent-followup', 9)
        send('/recap', 4)
        assert len(calls()) == before_calls + 1, 'fork reused ancestor baseline'
        fork_record, = [r for r in records() if r['status'] == 'published' and r['record_id'] not in {s['record_id'] for s in saved} | {clone_record['record_id']}]
        assert fork_record['metadata']['pi']['historyId'] not in {original_history, clone_record['metadata']['pi']['historyId']}, 'fork shared ancestor history'
        assert 'fork-independent-followup' in calls()[-1]['prompt'], 'fork recap omitted followup'
        # Navigate to the first activity with the real tree selector, declining summary.
        before = len(output)
        send('/tree', 1)
        os.write(master, b'\x1b[H'); collect(.5)
        send('', 1)
        if 'Summarize branch?' in output[before:].decode(errors='replace'):
            send('', 2)
        os.write(master, b'\x01\x0b'); send('tree-divergent-followup', 9)
        before_calls = len(calls())
        send('/recap', 4)
        assert len(calls()) == before_calls + 1, 'tree branch recap did not generate'
        tree_prompt = calls()[-1]['prompt']
        assert 'tree-divergent-followup' in tree_prompt, 'tree recap omitted active followup'
        assert 'fork-independent-followup' not in tree_prompt, 'tree recap included abandoned branch activity'
        tree_record, = [r for r in records() if r['status'] == 'published' and r['record_id'] not in {s['record_id'] for s in saved} | {clone_record['record_id'], fork_record['record_id']}]
        assert tree_record['metadata']['pi']['historyId'] == fork_record['metadata']['pi']['historyId'], 'tree changed session-wide history identity'
        send('/recap', 2)
        assert len(calls()) == before_calls + 1, 'tree baseline failed no-new followup'
        # A fresh independent session exercises the other first-use persistence choice.
        config = json.loads((extension / 'config.json').read_text())
        config.pop('model')
        config['timeoutSeconds'] = 1
        (extension / 'config.json').write_text(json.dumps(config))
        send('/new', 2)
        send('session-setup-followup', 9)
        before_calls = len(calls())
        send('/recap', 1)
        os.write(master, b'\x1b[B'); send('', 1)
        send('', 4)  # Current session, not defaults.
        assert len(calls()) == before_calls + 1, 'session setup failed generation'
        assert 'model' not in json.loads((extension / 'config.json').read_text()), 'session setup mutated defaults'
        setup_record = [r for r in records() if r['status'] == 'published'][-1]
        assert setup_record['metadata']['pi']['mode'] == 'incremental', 'session setup changed manual coverage'
        entries = [json.loads(line) for path in (root / 'sessions').rglob('*.jsonl') for line in path.read_text().splitlines()]
        assert any(e.get('customType') == 'recap-state' and e.get('data', {}).get('overrides', {}).get('model') == {'provider': 'recap-proof', 'id': 'recap'} for e in entries), 'first-use session backend not persisted'
        send('timeout-followup', 9)
        (root / 'gate').touch()
        before_calls = len(calls())
        send('/recap', 6)
        attempts = [r for r in records() if r.get('failure', {}).get('reason') == 'timed_out']
        assert attempts, 'whole-attempt timeout not safely classified'
        assert len(calls()) == before_calls + 2, 'timeout did not use exactly one immediate retry'
        assert len([r for r in records() if r['status'] == 'published']) == 6, 'timeout advanced published coverage'
        before = len(output)
        send('/recap history attempts', 1)
        assert 'timed out' in output[before:].decode(errors='replace'), 'attempt list omitted timeout classification'
        os.write(master, attempts[-1]['record_id'].encode()); collect(1)
        send('', 1)
        assert 'timed_out' in output[before:].decode(errors='replace'), 'attempt viewer omitted safe timeout reason'
        os.write(master, b'\x1b'); collect(1)
        (root / 'gate').unlink()
        send('/recap', 4)
        assert 'timeout-followup' in calls()[-1]['prompt'], 'timeout incorrectly consumed coverage'
        for path in (root / 'sessions').rglob('*.jsonl'):
            for line in path.read_text().splitlines():
                if json.loads(line).get('type') == 'message':
                    assert 'PROOF_RECAP' not in line, 'recap archived as message'
        print(json.dumps({'status': 'PASS', 'cases': ['first-use-unset-model-session-persistence', 'timeout-one-retry-history-filter-view-unchanged-coverage-followup', 'first-use-unset-model-defaults-exact-independent-backend', 'bare-manual-incremental-with-automatic-full-default', 'manual-completed-tool-source', 'manual-no-new-reuse', 'matching-full-reuse', 'manual-display-not-transcript', 'populated-history-typed-filter-view-scroll', 'session-settings-inheritance-view', 'settings-session-override-resume', 'defaults-edit-persist-override-precedence-clear-inherit', 'public-clone-independent-history-baseline', 'public-fork-independent-history-followup', 'public-tree-active-branch-baseline-followup'], 'published': len([r for r in records() if r['status'] == 'published']), 'cleanup': 'private session/agent/data fixture removed after process exit'}))
    except Exception:
        import sys
        print(output[-16000:].decode(errors='replace'), file=sys.stderr)
        raise
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        os.close(master)
assert not root.exists(), 'private fixture not cleaned'
