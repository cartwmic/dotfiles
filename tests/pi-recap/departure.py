#!/usr/bin/env python3
"""Captured recap survives public /new, /reload and actual host shutdown."""
import json, os, pty, select, shutil, subprocess, tempfile, time, fcntl, struct, termios
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'dot_pi/private_agent/extensions/recap'
observations = []
for journey in ('switch', 'reload', 'shutdown'):
    with tempfile.TemporaryDirectory(prefix='recap-departure-') as temporary:
        root = Path(temporary)
        extension = root / 'recap'; shutil.copytree(SOURCE, extension)
        agent = root / 'agent'; (agent / 'extensions').mkdir(parents=True)
        fixture = agent / 'extensions/fixture.ts'; shutil.copy(SOURCE / 'automation-fixture.ts', fixture)
        (extension / 'config.json').write_text(json.dumps({'model': {'provider': 'recap-proof', 'id': 'recap'}, 'completed': False, 'periodic': False, 'beforeCompaction': False}))
        gate = root / 'gate'; log = root / 'events.jsonl'
        wrapper_dir = root / '.local/bin'
        wrapper_dir.mkdir(parents=True)
        shutil.copy(ROOT / 'dot_local/bin/executable_session-recap', wrapper_dir / 'session-recap')
        (wrapper_dir / 'session-recap').chmod(0o700)
        env = dict({k: os.environ[k] for k in ('PATH', 'TERM', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TMPDIR') if k in os.environ}, HOME=str(root), XDG_CONFIG_HOME=str(root / 'config'), PI_CODING_AGENT_DIR=str(agent), XDG_DATA_HOME=str(root / 'data'), PI_OFFLINE='1', PI_RECAP_CLI=str(ROOT / 'dot_local/share/session-recap/session_recap.py'), RECAP_PROOF_LOG=str(log), RECAP_PROOF_GATE=str(gate))
        master, slave = pty.openpty(); tty = os.ttyname(slave)
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 36, 140, 0, 0))
        base = ['pi', '--offline', '--no-extensions', '--no-skills', '--no-prompt-templates', '--no-context-files', '--provider', 'recap-proof', '--model', 'main', '-e', str(fixture), '-e', str(extension / 'index.ts')]
        def launch(args):
            fd = os.open(tty, os.O_RDWR)
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', 36, 140, 0, 0))
            p = subprocess.Popen(base + args, stdin=fd, stdout=fd, stderr=fd, env=env); os.close(fd); return p
        process = launch(['--session-dir', str(root / 'sessions')]); os.close(slave)
        output = bytearray()
        def collect(seconds):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                if select.select([master], [], [], .05)[0]:
                    try: output.extend(os.read(master, 65536))
                    except OSError: time.sleep(.05)
        def send(text, seconds=2):
            os.write(master, text.encode() + b'\r'); collect(seconds)
        def stop():
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
        def records():
            return json.loads(subprocess.check_output(['python3', env['PI_RECAP_CLI'], 'list', '--json'], env=env))['records']
        def calls():
            return [json.loads(line) for line in log.read_text().splitlines()]
        try:
            collect(4); send('departure-' + journey, 9)
            original = next((root / 'sessions').rglob('*.jsonl'))
            native_id = json.loads(original.read_text().splitlines()[0])['id']
            gate.touch(); send('/recap', 3)
            assert len([c for c in calls() if c.get('model') == 'recap']) == 1, 'backend not captured'
            if journey == 'shutdown': stop()
            else: send('/new' if journey == 'switch' else '/reload', 4)
            boundary = len(output); gate.unlink(); collect(5)
            published = [r for r in records() if r['status'] == 'published']
            assert len(published) == 1, ('captured job did not survive', journey, records())
            assert published[0]['metadata']['pi']['nativeSessionId'] == native_id
            assert 'PROOF_RECAP' not in output[boundary:].decode(errors='replace'), 'departed result displayed'
            main_count = len([c for c in calls() if c.get('model') == 'main'])
            if journey != 'shutdown': stop()
            process = launch(['--session', str(original)]); collect(4)
            before = len(output); send('/recap history', 1); send('', 1)
            assert 'PROOF_RECAP' in output[before:].decode(errors='replace'), 'original resume did not discover recap'
            os.write(master, b'\x1b'); collect(1)
            send('/recap', 3)
            assert len([c for c in calls() if c.get('model') == 'recap']) == 1, 'saved coverage lost on resume'
            assert len([c for c in calls() if c.get('model') == 'main']) == main_count, 'delivery caused agent turn'
            assert 'PROOF_RECAP' not in original.read_text(), 'delivery entered native transcript'
            observations.append(journey + '-captured-save-original-resume-history-coverage')
        except Exception:
            import sys
            print(output[-18000:].decode(errors='replace'), file=sys.stderr); raise
        finally:
            if gate.exists(): gate.unlink()
            stop(); os.close(master)
    assert not root.exists(), 'private fixture cleanup failed'
print(json.dumps({'status': 'PASS', 'cases': observations, 'cleanup': 'private processes exited and fixtures removed'}))
