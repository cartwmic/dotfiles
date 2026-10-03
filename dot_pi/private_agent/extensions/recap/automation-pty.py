"""Real public TUI automation with accelerated settings and a scripted provider/tool."""
import json
import os
import pty
import select
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

source = Path(__file__).resolve().parent
repo = source.parents[3]
with tempfile.TemporaryDirectory(prefix='recap-t5-') as temporary:
    root = Path(temporary)
    extension = root / 'recap'
    shutil.copytree(source, extension)
    agent = root / 'agent'
    (agent / 'extensions').mkdir(parents=True)
    (agent / 'settings.json').write_text(json.dumps({'compaction': {'enabled': True, 'keepRecentTokens': 1, 'reserveTokens': 1000}, 'retry': {'enabled': True, 'maxRetries': 1, 'baseDelayMs': 500}}))
    fixture = agent / 'extensions' / 'proof.ts'
    shutil.copy(source / 'automation-fixture.ts', fixture)
    config = dict(model=dict(provider='recap-proof', id='recap'), completed=True,
                  periodic=True, beforeCompaction=True, intervalMinutes=0.02,
                  cadence=1, timeoutSeconds=60,
                  mode=os.environ.get('RECAP_PROOF_MODE', 'incremental'))
    assert config['mode'] in ('incremental', 'full')
    (extension / 'config.json').write_text(json.dumps(config))
    log = root / 'events.jsonl'
    gate = root / 'gate'
    wrapper_dir = root / '.local/bin'
    wrapper_dir.mkdir(parents=True)
    shutil.copy(repo / 'dot_local/bin/executable_session-recap', wrapper_dir / 'session-recap')
    (wrapper_dir / 'session-recap').chmod(0o700)
    env = dict({k: os.environ[k] for k in ('PATH', 'TERM', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TMPDIR') if k in os.environ}, HOME=str(root), XDG_CONFIG_HOME=str(root / 'config'), PI_CODING_AGENT_DIR=str(agent), XDG_DATA_HOME=str(root / 'data'),
               PI_OFFLINE='1', PI_RECAP_CLI=str(repo / 'dot_local/share/session-recap/session_recap.py'),
               RECAP_PROOF_LOG=str(log), RECAP_PROOF_GATE=str(gate))
    master, slave = pty.openpty()
    process = subprocess.Popen(['pi', '--offline', '--no-extensions', '--no-skills',
        '--no-prompt-templates', '--no-context-files', '--session-dir', str(root / 'sessions'),
        '--provider', 'recap-proof', '--model', 'main', '-e', str(fixture), '-e', str(extension / 'index.ts')],
        stdin=slave, stdout=slave, stderr=slave, env=env)
    os.close(slave)
    output = bytearray()

    def collect(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if select.select([master], [], [], 0.05)[0]:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break

    def send(command, seconds):
        os.write(master, command.encode() + b'\r')
        collect(seconds)

    def events():
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def records():
        return json.loads(subprocess.check_output(['python3', env['PI_RECAP_CLI'], 'list', '--json'], env=env))['records']

    try:
        collect(4)
        send('silent-case', 9)
        rows = events()
        assert sum(e['event'] == 'agent-start' for e in rows) == 1, rows
        start = next(e['time'] for e in rows if e['event'] == 'tool-start')
        end = next(e['time'] for e in rows if e['event'] == 'tool-end')
        calls = [e for e in rows if e['event'] == 'call' and e['model'] == 'recap']
        assert any(start < e['time'] < end for e in calls), rows
        assert len(calls) == 2, ('silent no-new must avoid extra calls', rows)
        assert 'PROOF_TOOL_RESULT' in calls[-1]['prompt'] and 'PROOF_FINAL' in calls[-1]['prompt'], 'partial recap hid final work'
        saved = [r for r in records() if r['status'] == 'published']
        assert {r['metadata']['pi']['trigger'] for r in saved} == {'periodic', 'settlement'}, saved
        assert all(r['metadata']['pi']['mode'] == config['mode'] for r in saved), saved
        assert 'No new activity' in output.decode(errors='replace'), output.decode(errors='replace')
        assert 'Ongoing:' in output.decode(errors='replace'), 'no-new recap omitted current working status'
        count = len(calls)
        collect(2)
        assert len([e for e in events() if e['event'] == 'call' and e['model'] == 'recap']) == count, 'idle trigger'
        send('error-case', 3)
        send('abort-case', 3)
        # Wait for durable publication, not a fixed backend/startup latency.
        deadline = time.monotonic() + 10
        while sum(r['metadata']['pi']['trigger'] == 'settlement' for r in records() if r['status'] == 'published') < 3 and time.monotonic() < deadline:
            collect(0.1)
        assert sum(r['metadata']['pi']['trigger'] == 'settlement' for r in records() if r['status'] == 'published') == 3, records()
        before = len(records())
        before_events = len(events())
        send('retry-case', 10)
        stint = events()[before_events:]
        assert sum(e['event'] == 'call' and e['model'] == 'main' for e in stint) == 3, stint
        assert any(e['event'] == 'tool-update' for e in stint), stint
        progress = [r for r in records()[before:] if r['status'] == 'published' and r['metadata']['pi']['trigger'] == 'periodic']
        assert len(progress) >= 2, progress
        first_call = next(e['time'] for e in stint if e['event'] == 'call' and e['model'] == 'main')
        from datetime import datetime
        milliseconds = lambda value: datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp() * 1000
        first_capture = milliseconds(progress[0]['metadata']['pi']['capturedAt'])
        assert 1100 <= first_capture - first_call <= 1700, ('retry/update reset countdown', stint, progress)
        for old, new in zip(progress, progress[1:]):
            assert milliseconds(new['metadata']['pi']['capturedAt']) - milliseconds(old['created_at']) >= 1100, 'save did not restart a full interval'
        # Ensure compaction exercises generation, not legitimate matching-full reuse.
        config.update(mode='full', instructions='Recap the captured pre-compaction activity.')
        (extension / 'config.json').write_text(json.dumps(config))
        gate.touch()
        send('/compact', 2)
        assert any(e['event'] == 'compact' for e in events()), events()
        assert sum(r['metadata']['pi']['trigger'] == 'before-compaction' for r in records() if r['status'] == 'published') == 0
        gate.unlink()
        collect(3)
        assert any(r['metadata']['pi']['trigger'] == 'before-compaction' for r in records() if r['status'] == 'published'), records()
        config.update(mode='incremental', cadence=2)
        (extension / 'config.json').write_text(json.dumps(config))
        count = len([r for r in records() if r['status'] == 'published'])
        send('error-case', 3)
        assert len([r for r in records() if r['status'] == 'published']) == count, 'cadence counted internal attempts'
        send('abort-case', 3)
        assert len([r for r in records() if r['status'] == 'published']) == count + 1, 'configured final cadence'
        text = output.decode(errors='replace')
        assert 'Failed to load' not in text and 'operation failed' not in text, text
        sessions = list((root / 'sessions').rglob('*.jsonl'))
        assert sessions, 'missing real session'
        for path in sessions:
            for line in path.read_text().splitlines():
                entry = json.loads(line)
                if entry.get('type') == 'message':
                    assert 'recap-deliver-internal' not in line and 'PROOF_RECAP' not in line, line
        assert sum(e['event'] == 'agent-start' for e in events()) == 7, events()
        config.update(model=None, completed=False)
        (extension / 'config.json').write_text(json.dumps(config))
        count = len(records())
        recap_calls = sum(e['event'] == 'call' and e['model'] == 'recap' for e in events())
        send('/new', 1)
        assert len(records()) == count, 'session departure triggered recap'
        send('silent-case', 9)
        assert len(records()) == count, 'status-only created a record'
        assert sum(e['event'] == 'call' and e['model'] == 'recap' for e in events()) == recap_calls, 'status-only generated'
        assert 'Recap model is not configured' in output.decode(errors='replace'), 'missing honest status'
        print('PASS: retry/update timing, saved reset/new stint, silent-tool periodic/no-new/status-only, idle/departure stop, final error/abort/cadence, gated nonblocking compaction; no extra turns/transcript output')
    except Exception:
        print(output.decode(errors='replace'))
        print(records())
        raise
    finally:
        gate.unlink(missing_ok=True)
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        os.close(master)
