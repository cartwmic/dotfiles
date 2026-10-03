#!/usr/bin/env python3
"""Real disposable Pi cancellation and reasoning privacy follow-up."""
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
with tempfile.TemporaryDirectory(prefix='recap-lifecycle-') as temporary:
    root = Path(temporary)
    extension = root / 'recap'
    shutil.copytree(SOURCE, extension)
    agent = root / 'agent'
    (agent / 'extensions').mkdir(parents=True)
    fixture = agent / 'extensions/fixture.ts'
    text = (SOURCE / 'automation-fixture.ts').read_text()
    text = text.replace("[{ type: 'text', text: 'PROOF_FINAL tool completed.' }]", "[{ type: 'thinking', thinking: 'PRIVATE_REASONING_SENTINEL_7491' }, { type: 'text', text: 'PROOF_FINAL tool completed.' }]")
    fixture.write_text(text)
    (extension / 'config.json').write_text(json.dumps({'model': {'provider': 'recap-proof', 'id': 'recap'}, 'completed': False, 'periodic': False, 'beforeCompaction': False}))
    log = root / 'events.jsonl'
    gate = root / 'gate'
    wrapper_dir = root / '.local/bin'
    wrapper_dir.mkdir(parents=True)
    shutil.copy(ROOT / 'dot_local/bin/executable_session-recap', wrapper_dir / 'session-recap')
    (wrapper_dir / 'session-recap').chmod(0o700)
    env = dict({k: os.environ[k] for k in ('PATH', 'TERM', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TMPDIR') if k in os.environ}, HOME=str(root), XDG_CONFIG_HOME=str(root / 'config'), PI_CODING_AGENT_DIR=str(agent), XDG_DATA_HOME=str(root / 'data'), PI_OFFLINE='1', PI_RECAP_CLI=str(ROOT / 'dot_local/share/session-recap/session_recap.py'), RECAP_PROOF_LOG=str(log), RECAP_PROOF_GATE=str(gate))
    visible_unsaved = os.environ.get('RECAP_PROOF_UNSAVED') == 'visible'
    unsaved = visible_unsaved or os.environ.get('RECAP_PROOF_UNSAVED') == '1'
    if unsaved:
        wrapper = root / 'transport.py'
        wrapper.write_text('''import os, subprocess, sys, time
from pathlib import Path
p = subprocess.Popen([sys.executable, os.environ["GENUINE_RECAP_CLI"], *sys.argv[1:]], stdout=subprocess.PIPE, text=True)
for line in p.stdout:
    if '"generated-unsaved"' in line and '"event"' in line:
        Path(os.environ["BUFFER_RECEIPT"]).write_text(line)
        while Path(os.environ["CONSUMPTION_GATE"]).exists(): time.sleep(.05)
    print(line, end="", flush=True)
sys.exit(p.wait())
''')
        env.update(GENUINE_RECAP_CLI=env['PI_RECAP_CLI'], PI_RECAP_CLI=str(wrapper), BUFFER_RECEIPT=str(root / 'buffer.json'), CONSUMPTION_GATE=str(root / 'consume-gate'))
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 36, 140, 0, 0))
    process = subprocess.Popen(['pi', '--offline', '--no-extensions', '--no-skills', '--no-prompt-templates', '--no-context-files', '--session-dir', str(root / 'sessions'), '--provider', 'recap-proof', '--model', 'main', '-e', str(fixture), '-e', str(extension / 'index.ts')], stdin=slave, stdout=slave, stderr=slave, env=env)
    os.close(slave)
    output = bytearray()
    def collect(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if select.select([master], [], [], .05)[0]:
                try: output.extend(os.read(master, 65536))
                except OSError: break
    def send(text, seconds=2):
        os.write(master, text.encode() + b'\r'); collect(seconds)
    def calls():
        return [json.loads(line) for line in log.read_text().splitlines() if json.loads(line).get('model') == 'recap']
    def records():
        return json.loads(subprocess.check_output(['python3', env['PI_RECAP_CLI'], 'list', '--json'], env=env))['records']
    try:
        collect(4)
        send('privacy-cancellation-followup', 9)
        sessions = list((root / 'sessions').rglob('*.jsonl'))
        assert any('PRIVATE_REASONING_SENTINEL_7491' in p.read_text() for p in sessions), 'thinking fixture never reached actual transcript'
        if unsaved:
            storage = root / 'data/session-recap'
            storage.mkdir(parents=True, exist_ok=True)
            (storage / 'records').write_text('controlled storage failure')
            (root / 'consume-gate').touch()
        gate.touch()
        send('/recap', 3)
        assert len(calls()) == 1, 'captured backend did not start'
        assert 'PROOF_TOOL_RESULT' in calls()[0]['prompt'] and 'PROOF_FINAL' in calls()[0]['prompt'], 'missing completed activity'
        assert 'PRIVATE_REASONING_SENTINEL_7491' not in calls()[0]['prompt'], 'thinking leaked into recap model request'
        if unsaved:
            gate.unlink()
            for _ in range(100):
                collect(.1)
                if (root / 'buffer.json').exists(): break
            assert (root / 'buffer.json').exists(), 'real generated-unsaved terminal never buffered'
            terminal = json.loads((root / 'buffer.json').read_text())
            assert terminal['status'] == 'generated-unsaved' and 'PROOF_RECAP' in terminal['text'], terminal
        calls_before_followup = len(calls())
        assert calls_before_followup == (2 if unsaved else 1), 'unexpected backend attempts before cancellation'
        if not visible_unsaved:
            send('/recap cancel', 1)
        before = len(output)
        if unsaved:
            (root / 'consume-gate').unlink()
            if not visible_unsaved:
                (storage / 'records').unlink()
        else:
            gate.unlink()
        collect(4)
        visible = output[before:].decode(errors='replace')
        if visible_unsaved:
            assert 'PROOF_RECAP' in visible, 'available original UI did not consume generated-unsaved narrative'
            assert 'unsaved' in visible.lower() or 'not saved' in visible.lower(), 'missing unsaved warning'
            (storage / 'records').unlink()
        else:
            assert 'PROOF_RECAP' not in visible, 'canceled result displayed'
        assert not [r for r in records() if r['status'] == 'published'], 'failed/canceled result published'
        send('/recap', 4)
        assert len(calls()) == calls_before_followup + 1, 'cancel advanced baseline or followup failed'
        published = [r for r in records() if r['status'] == 'published']
        assert len(published) == 1, published
        assert 'PROOF_RECAP' in output[before:].decode(errors='replace'), 'followup not displayed'
        assert 'PROOF_TOOL_RESULT' in calls()[-1]['prompt'], 'followup lost canceled coverage'
        for path in (root / 'data').rglob('*'):
            if path.is_file():
                assert b'PRIVATE_REASONING_SENTINEL_7491' not in path.read_bytes(), f'thinking leaked to recap storage: {path}'
        for path in sessions:
            for line in path.read_text().splitlines():
                if json.loads(line).get('type') == 'message':
                    assert 'PROOF_RECAP' not in line, 'recap archived as conversation'
        print(json.dumps({'status': 'PASS', 'cases': (['available-original-ui-generated-unsaved-narrative-warning-no-save-followup-coverage'] if visible_unsaved else ['buffered-real-generated-unsaved-after-cancel-no-display-no-save-no-advance'] if unsaved else ['public-gated-cancel-no-display-no-publish']) + [('unsaved-followup-preserves-coverage' if visible_unsaved else 'cancel-followup-preserves-coverage'), 'reasoning-sentinel-source-storage-exclusion'], 'cleanup': 'private fixture removed after process exit'}))
    except Exception:
        import sys
        print(output[-16000:].decode(errors='replace'), file=sys.stderr)
        raise
    finally:
        if gate.exists(): gate.unlink()
        process.terminate()
        try: process.wait(timeout=5)
        except subprocess.TimeoutExpired: process.kill(); process.wait()
        os.close(master)
assert not root.exists(), 'private fixture not cleaned'
