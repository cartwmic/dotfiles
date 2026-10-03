#!/usr/bin/env python3
"""Manual recap while real foreground tool is gated; input-derived dummy narrative."""
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import shutil
import struct
import subprocess
import tempfile
import termios
import time

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'dot_pi/private_agent/extensions/recap'
with tempfile.TemporaryDirectory(prefix='recap-busy-') as temporary:
    root = Path(temporary)
    extension = root / 'recap'
    shutil.copytree(SOURCE, extension)
    agent = root / 'agent'
    (agent / 'extensions').mkdir(parents=True)
    fixture = agent / 'extensions/fixture.ts'
    text = (SOURCE / 'automation-fixture.ts').read_text()
    text = text.replace("message.content = [{ type: 'text', text: 'PROOF_RECAP public progress and next steps.' }];", """const material = JSON.stringify(context.messages);
          const topic = material.lastIndexOf('orchard') > material.lastIndexOf('harbor') ? 'orchard' : 'harbor';
          const completed = material.lastIndexOf('PROOF_TOOL_RESULT') > material.lastIndexOf(topic);
          message.content = [{ type: 'text', text: `Observed ${topic} work. ${completed ? 'Tool returned PROOF_TOOL_RESULT; result is available.' : 'Tool has not returned; work remains unfinished.'} Present state: ${completed ? 'completed activity' : 'ongoing activity'}. Next: ${completed ? 'review the result' : 'wait for the tool result'}.` }];""")
    text = text.replace("for (let i = 0; i < 23; i++)", "while (existsSync(process.env.BUSY_TOOL_GATE!)) await delay(50);\n    for (let i = 0; i < 1; i++)")
    fixture.write_text(text)
    (extension / 'config.json').write_text(json.dumps({'model': {'provider': 'recap-proof', 'id': 'recap'}, 'completed': False, 'periodic': False, 'beforeCompaction': False}))
    log = root / 'events.jsonl'
    gate = root / 'tool-gate'
    wrapper_dir = root / '.local/bin'
    wrapper_dir.mkdir(parents=True)
    shutil.copy(ROOT / 'dot_local/bin/executable_session-recap', wrapper_dir / 'session-recap')
    (wrapper_dir / 'session-recap').chmod(0o700)
    env = dict({k: os.environ[k] for k in ('PATH', 'TERM', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TMPDIR') if k in os.environ}, HOME=str(root), XDG_CONFIG_HOME=str(root / 'config'), PI_CODING_AGENT_DIR=str(agent), XDG_DATA_HOME=str(root / 'data'), PI_OFFLINE='1', PI_RECAP_CLI=str(ROOT / 'dot_local/share/session-recap/session_recap.py'), RECAP_PROOF_LOG=str(log), RECAP_PROOF_GATE=str(root / 'backend-gate'), BUSY_TOOL_GATE=str(gate))
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
    def send(value, seconds=3):
        os.write(master, value.encode() + b'\r')
        collect(seconds)
    def events():
        return [json.loads(line) for line in log.read_text().splitlines()]
    def calls():
        return [event for event in events() if event.get('model') == 'recap']
    def records():
        return json.loads(subprocess.check_output(['python3', env['PI_RECAP_CLI'], 'list', '--json'], env=env))['records']
    try:
        collect(4)
        for topic, command in [('orchard', '/recap'), ('harbor', '/recap full')]:
            gate.touch()
            send(f'Inspect {topic} work', 2)
            starts = sum(event.get('event') == 'tool-start' for event in events())
            ends = sum(event.get('event') == 'tool-end' for event in events())
            assert starts == ends + 1, 'foreground tool not genuinely active'
            count = len(calls())
            main_calls = sum(event.get('model') == 'main' for event in events())
            before = len(output)
            send(command, 4)
            assert gate.exists() and sum(event.get('event') == 'tool-end' for event in events()) == ends
            assert len(calls()) == count + 1, 'manual request did not run while tool active'
            assert sum(event.get('model') == 'main' for event in events()) == main_calls, 'recap triggered a foreground model turn'
            assert topic in calls()[-1]['prompt'], 'wrong captured topic'
            visible = output[before:].decode(errors='replace')
            assert f'Observed {topic} work.' in visible and 'unfinished' in visible and 'wait for the tool result' in visible, 'input-dependent unfinished narrative not displayed'
            saved = [record for record in records() if record['status'] == 'published']
            assert len(saved) == count + 1, 'busy manual result not saved'
            gate.unlink()
            collect(3)
            assert sum(event.get('event') == 'tool-end' for event in events()) == ends + 1
            before = len(output)
            send('/recap', 4)
            assert len(calls()) == count + 2, 'busy recap incorrectly covered final outcome'
            assert 'PROOF_TOOL_RESULT' in calls()[-1]['prompt'], 'final tool result missing from subsequent coverage'
            assert 'result is available' in output[before:].decode(errors='replace'), 'completed narrative does not distinguish tool outcome'
        assert 'orchard' in calls()[0]['prompt'] and 'harbor' in calls()[2]['prompt']
        for path in (root / 'sessions').rglob('*.jsonl'):
            for line in path.read_text().splitlines():
                if json.loads(line).get('type') == 'message':
                    assert 'Observed orchard work.' not in line and 'Observed harbor work.' not in line, 'recap entered native transcript'
        print(json.dumps({'status': 'PASS', 'cases': ['manual-incremental-during-gated-foreground-tool', 'manual-full-during-gated-foreground-tool', 'final-tool-result-remains-uncovered', 'input-derived-distinct-topic-unfinished-completed-next-step-narratives'], 'cleanup': 'private process and fixture removed'}))
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
assert not root.exists()
