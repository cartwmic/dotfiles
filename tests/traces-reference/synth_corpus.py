"""Deterministic synthetic Pi corpora for the stage 2 reference tooling. Nothing real is read.

    python3 synth_corpus.py builder OUT     # the synthetic builder corpus (cache gauges, children, a fork, errors)
    python3 synth_corpus.py odd OUT         # odd inputs: malformed line, float tokens, NaN, bad UTF-8, untimed, naive stamps
    python3 synth_corpus.py fresh OUT       # calls at fixed offsets from wall-clock now (the run-path fixture of G1(f))

`builder` and `odd` use fixed times around T, so a dump of them is the same on every machine.
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "dot_local/share/agent-events"))
from test_agent_events import Fixture, iso  # noqa: E402  (the collector's own fixture builder)

T = 1_790_000_000_000
MIN = 60_000
S1 = "0190aaaa-1111-7222-8333-444455556666"
S2 = "0190bbbb-1111-7222-8333-444455556666"
S3 = "0190cccc-1111-7222-8333-444455556666"
BAD_ID = "not-a-uuid"


def save(root, dirname, name, fx):
    d = Path(root) / dirname
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text("".join(json.dumps(e) + "\n" for e in fx.entries))
    return p


def llm_run(fx, start, n, step=MIN, **kw):
    """n assistant calls, `step` apart, each ending 20 s after it starts."""
    for i in range(n):
        t = start + i * step
        fx.llm(t, end=t + 20_000, **kw)


def builder(root):
    """Three UUID sessions, one session with a non-UUID id, one child run, one fork copy."""
    # S1: busy, ends at T+10 min: cache hits, then a three-call full-miss run
    fx = Fixture(S1, "/Volumes/Workshop/macbook/git/agent-kit", T)
    fx.user(T + 1000)
    llm_run(fx, T + 2000, 4, cr=40_000, cw=1_000, fresh=500, cost=0.02)
    llm_run(fx, T + 5 * MIN, 3, cr=100, cw=60_000, fresh=200, cost=0.2, model="m-big")
    fx.tool("c1", "bash", T + 9 * MIN, T + 9 * MIN + 4000)
    fx.llm(T + 9 * MIN + 5000, end=T + 9 * MIN + 9000, calls=("c1",), cr=30_000, cw=500, fresh=100)
    parent = save(root, "--git-agent-kit--", f"2026-10-01T00-00-00-000Z_{S1}.jsonl", fx)
    # a child run of S1
    ch = Fixture("child-run", "/Volumes/Workshop/macbook/git/agent-kit", T + MIN)
    ch.user(T + MIN + 1000)
    llm_run(ch, T + MIN + 2000, 2, cr=10_000, cw=500, fresh=50)
    child = Path(root) / "--git-agent-kit--" / f"2026-10-01T00-00-00-000Z_{S1}" / "c1" / "run-0"
    child.mkdir(parents=True)
    (child / "session.jsonl").write_text("".join(json.dumps(e) + "\n" for e in ch.entries))
    # S2: another project and model, idle 40 min after its last call (in the streak family only at T+50 min)
    fx = Fixture(S2, "/Volumes/Workshop/macbook/git/dotfiles", T + 2 * MIN)
    fx.user(T + 2 * MIN + 1000)
    llm_run(fx, T + 3 * MIN, 3, cr=20_000, cw=60_000, fresh=100, model="m-2")
    save(root, "--git-dotfiles--", f"2026-10-01T00-02-00-000Z_{S2}.jsonl", fx)
    # S3: a long idle gap (> 1 h) then one full miss
    fx = Fixture(S3, "/tmp/scratch-run", T)
    fx.user(T + 1000)
    llm_run(fx, T + 2000, 1, cr=20_000, cw=500, fresh=50)
    llm_run(fx, T + 80 * MIN, 1, cr=0, cw=70_000, fresh=10)
    save(root, "--tmp-scratch-run--", f"2026-10-01T00-00-00-000Z_{S3}.jsonl", fx)
    # a session whose id is not a UUID: never exported by the cache gauges
    fx = Fixture(BAD_ID, "/Volumes/Workshop/macbook/git/agent-kit", T)
    fx.user(T + 1000)
    llm_run(fx, T + 2000, 2, cr=1_000, cw=60_000, fresh=10)
    save(root, "--git-agent-kit--", "2026-10-01T00-00-00-001Z_notauuid.jsonl", fx)
    # a fork copy of S1: the same entries again, so dedupe has to pick one owner
    fx = Fixture(S1 + "-fork", "/Volumes/Workshop/macbook/git/agent-kit", T)
    fx.entries = [json.loads(line) for line in parent.read_text().splitlines()]
    fx.entries[0]["id"] = S1 + "-fork"
    fx.entries[0]["parentSession"] = str(parent)
    save(root, "--git-agent-kit--", f"2026-10-01T00-00-01-000Z_{S1}-fork.jsonl", fx)


def odd(root):
    """Inputs the plan's section 0 lists as places a port can differ from Python."""
    fx = Fixture(S1, "/work/proj", T)
    fx.user(T + 1000)
    fx.llm(T + 2000, end=T + 22_000, cr=5.0, cw=100, fresh=10)  # a float token count: as_int(5.0) is None
    fx.llm(T + 30_000, end=None, stamp=False, cr=100, cw=100, fresh=10)  # untimed
    lines = [json.dumps(e) for e in fx.entries]
    lines.insert(2, "{not json")
    lines.insert(3, '{"type":"message","message":{"role":"assistant","usage":{"input":NaN,"output":Infinity}}}')
    naive = dict(fx.entries[1], id="naive-ts", timestamp="2026-10-01T00:00:30")  # no zone: local-time rule
    lines.append(json.dumps(naive))
    d = Path(root) / "--work-proj--"
    d.mkdir(parents=True)
    (d / "2026-10-01T00-00-00-000Z_odd.jsonl").write_bytes(("\n".join(lines) + "\n").encode() + b'\xff\xfe{"type":"x"}\n')
    fx2 = Fixture(S2, "/work/proj", T)  # a header and nothing else
    save(root, "--work-proj--", "2026-10-01T00-00-00-001Z_empty.jsonl", fx2)


def fresh(root, now=None):
    """The G1(f) fixture: call times at fixed offsets from wall-clock now, every one 90 s or more from a window edge."""
    now = int((now or time.time()) * 1000)
    fx = Fixture(S1, "/work/proj", now - 70 * MIN)
    fx.user(now - 70 * MIN + 1000)
    for off in (5.0, 15.0, 28.5, 31.5):  # minutes before now; the last is outside the 30-minute window
        end = now - int(off * MIN)
        fx.llm(end - 20_000, end=end, cr=20_000, cw=2_000, fresh=100)
    for off in (6.0, 4.0, 2.0):  # a three-call full-miss run ending at now-2 min: streak 3
        end = now - int(off * MIN)
        fx.llm(end - 20_000, end=end, cr=100, cw=60_000, fresh=100, model="m-miss")
    save(root, "--work-proj--", f"2026-10-01T00-00-00-000Z_{S1}.jsonl", fx)
    fx = Fixture(S2, "/work/proj", now - 80 * MIN)  # a miss run that ended 61 min ago: gone from the streak family
    fx.user(now - 80 * MIN + 1000)
    for off in (65.0, 63.0, 61.0):
        end = now - int(off * MIN)
        fx.llm(end - 20_000, end=end, cr=100, cw=60_000, fresh=100, model="m-old")
    save(root, "--work-proj--", f"2026-10-01T00-00-00-000Z_{S2}.jsonl", fx)
    fx = Fixture(BAD_ID, "/work/proj", now - 10 * MIN)  # not a UUID: skipped
    fx.user(now - 10 * MIN + 1000)
    fx.llm(now - 5 * MIN - 20_000, end=now - 5 * MIN, cr=100, cw=60_000, fresh=100)
    save(root, "--work-proj--", "2026-10-01T00-00-00-000Z_bad.jsonl", fx)


if __name__ == "__main__":
    kind, out = sys.argv[1], sys.argv[2]
    {"builder": builder, "odd": odd, "fresh": fresh}[kind](out)
    print(f"{kind} corpus written to {out}")
