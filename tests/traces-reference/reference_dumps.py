"""Make the reference dumps of the synthetic builder corpus and the odd-input corpus, and list their sha256.

    python3 reference_dumps.py OUT          # writes OUT/builder, OUT/odd, OUT/MANIFEST.sha256

These are the dumps the TS port (S1) is compared to. reference-dumps.sha256, beside this file, is the pinned list; a unit test
rebuilds the dumps and requires the same lines, so a change to the collector, the dump format or the corpora shows up there.
"""
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parents[1] / "dot_local/share/agent-events"
NOW = ("1790000600", "1790001800", "1790003000")
CASES = {"builder": ["--now", *NOW, "--replay-ticks", "3"], "odd": ["--now", NOW[0]]}


def make(out):
    out = Path(out)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("AGENT_EVENTS_", "AGENT_TRACES_", "XDG_"))}
    env.update(PYTHONDONTWRITEBYTECODE="1", TZ="UTC")
    with tempfile.TemporaryDirectory() as tmp:
        for kind, extra in CASES.items():
            corpus = Path(tmp) / kind
            subprocess.run([sys.executable, str(HERE / "synth_corpus.py"), kind, str(corpus)], check=True, env=env, capture_output=True)
            subprocess.run([sys.executable, str(TOOLS / "parity_dump.py"), "dump", "--sessions-dir", str(corpus), "--out", str(out / kind),
                            "--home", "/home/parity", *extra], check=True, env=env, capture_output=True)
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(out)}" for p in sorted(out.rglob("*")) if p.is_file()]
    (out / "MANIFEST.sha256").write_text("\n".join(lines) + "\n")
    return lines


if __name__ == "__main__":
    print("\n".join(make(sys.argv[1])))
