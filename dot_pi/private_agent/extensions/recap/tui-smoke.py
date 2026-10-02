"""Disposable real-Pi entry-path smoke; no provider requests or live apply."""
import os
import pty
import select
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

source = Path(__file__).resolve()
repo = source.parents[4]
with tempfile.TemporaryDirectory(prefix="recap-t4-") as temporary:
    wrapper_dir = Path(temporary) / '.local/bin'
    wrapper_dir.mkdir(parents=True)
    shutil.copy(repo / 'dot_local/bin/executable_session-recap', wrapper_dir / 'session-recap')
    (wrapper_dir / 'session-recap').chmod(0o700)
    master, slave = pty.openpty()
    env = dict({k: os.environ[k] for k in ('PATH', 'TERM', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TMPDIR') if k in os.environ}, HOME=temporary, XDG_CONFIG_HOME=temporary + "/config", PI_CODING_AGENT_DIR=temporary + "/agent",
               XDG_DATA_HOME=temporary + "/data", PI_OFFLINE="1",
               PI_RECAP_CLI=str(repo / "dot_local/share/session-recap/session_recap.py"))
    process = subprocess.Popen([
        "pi", "--offline", "--no-extensions", "--no-skills", "--no-prompt-templates",
        "--no-context-files", "--no-session", "-e", str(source.with_name("index.ts")),
    ], stdin=slave, stdout=slave, stderr=slave, env=env)
    os.close(slave)
    output = bytearray()

    def collect(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if select.select([master], [], [], 0.1)[0]:
                try:
                    output.extend(os.read(master, 65536))
                except OSError:
                    break

    try:
        collect(5)
        for command in (b"/recap\r", b"/recap cancel\r", b"/recap history\r"):
            os.write(master, command)
            collect(2)
        os.write(master, b"\x1b")
        collect(0.5)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        os.close(master)
    text = output.decode(errors="replace")
    assert "Failed to load" not in text, text
    assert "operation failed" not in text, text
    for expected in ("Nothing to recap yet", "Recap cancelled", "Recap history"):
        assert expected in text, expected
    assert not list(Path(temporary).rglob("*.jsonl")), "Unexpected conversation archive"
    print("PASS: real TUI empty/cancel/history; no conversation archive")
