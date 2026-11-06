"""Black-box tests for dot_local/bin/executable_qmd-export (runs the real script on fixture trees)."""
import fcntl
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT = Path(os.environ.get("QMD_EXPORT_SCRIPT") or Path(__file__).resolve().parents[2] / "dot_local/bin/executable_qmd-export")
DAY = 86400


def jl(*objs):
    return "\n".join(json.dumps(o) for o in objs) + "\n"


def session(sid, started="2026-10-20T10:00:00.000Z", cwd="/w/proj", msgs=(("user", "hello world"), ("assistant", "hi there"))):
    rows = [{"type": "session", "id": sid, "timestamp": started, "cwd": cwd}]
    for i, (role, text) in enumerate(msgs):
        rows.append({"type": "message", "timestamp": "2026-10-20T10:0%d:00.000Z" % i,
                     "message": {"role": role, "content": [{"type": "text", "text": text}]}})
    return jl(*rows)


def cc_user(text, ts="2026-10-20T10:00:00.000Z", sid="cc1", **kw):
    o = {"type": "user", "message": {"role": "user", "content": text}, "timestamp": ts, "sessionId": sid, "cwd": "/w/proj",
         "isSidechain": False}
    o.update(kw)
    return o


def cc_asst(blocks, ts="2026-10-20T10:01:00.000Z", sid="cc1"):
    return {"type": "assistant", "message": {"role": "assistant", "content": blocks}, "timestamp": ts, "sessionId": sid,
            "cwd": "/w/proj"}


def cx_meta(sid="cx1", cwd="/w/codex"):
    return {"timestamp": "2026-10-20T10:00:01.000Z", "type": "session_meta",
            "payload": {"id": sid, "timestamp": "2026-10-20T10:00:00.000Z", "cwd": cwd, "base_instructions": {"text": "BASE-INSTR"}}}


def cx_msg(role, *texts, ts="2026-10-20T10:01:00.000Z"):
    kind = "output_text" if role == "assistant" else "input_text"
    return {"timestamp": ts, "type": "response_item",
            "payload": {"type": "message", "role": role, "content": [{"type": kind, "text": t} for t in texts]}}


class Fx:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sessions = self.root / "sessions"
        self.recaps = self.root / "recaps"
        self.claude = self.root / "claude"
        self.codex = self.root / "codex"
        self.out = self.root / "corpus"
        self.t3db = self.root / "no-t3.sqlite"          # the T3 db the exporter reads; missing unless a test sets one
        for d in (self.sessions, self.recaps, self.claude, self.codex):
            d.mkdir()

    def put(self, path, text, age_days=0):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        t = time.time() - age_days * DAY
        os.utime(path, (t, t))
        return path

    def sess(self, sid, text=None, age_days=0, sub="--w-proj--", name=None, **kw):
        return self.put(self.sessions / sub / (name or "2026-10-20T10-00-00-000Z_%s.jsonl" % sid), text or session(sid, **kw), age_days)

    def recap(self, rid, summary="we decided X", day="2026-10-26", age_days=0, **kw):
        o = {"record_id": rid, "kind": "single", "created_at": day + "T01:02:03Z", "summary": summary,
             "metadata": {"pi": {"nativeSessionId": "sid-" + rid}}, "annotations": {"herdr": {"pane_id": "p1"}}}
        o.update(kw)
        return self.put(self.recaps / day / (rid + ".json"), json.dumps(o), age_days)

    def cc(self, rows, rel="-w-proj/cc1.jsonl", age_days=0):
        return self.put(self.claude / rel, jl(*rows), age_days)

    def cx(self, rows, rel="2026/10/20/rollout-2026-10-20T10-00-00-cx1.jsonl", age_days=0):
        return self.put(self.codex / rel, jl(*rows), age_days)

    def run(self, *args, check=0):
        p = subprocess.run([sys.executable, str(SCRIPT), "--out", str(self.out), "--sessions-root", str(self.sessions),
                            "--claude-root", str(self.claude), "--codex-root", str(self.codex),
                            "--recaps-root", str(self.recaps), *args], capture_output=True, text=True, timeout=120,
                           env=dict(os.environ, QMD_EXPORT_T3_DB=str(self.t3db)))
        self.p = p
        if check is not None:
            assert p.returncode == check, (p.returncode, p.stdout, p.stderr)
        return p

    def files(self, kind=None):
        base = self.out / kind if kind else self.out
        return sorted(str(p.relative_to(self.out)) for p in base.rglob("*.md")) if base.exists() else []

    def close(self):
        self.tmp.cleanup()


class Base(unittest.TestCase):
    def setUp(self):
        self.f = Fx()
        self.addCleanup(self.f.close)


class ExportTest(Base):
    def test_layout_frontmatter_and_content(self):
        f = self.f
        f.sess("s1", msgs=(("user", "find the bug in parser"), ("assistant", "it is in line 4")), cwd="/w/proj")
        f.recap("r1", "we decided X")
        f.run()
        self.assertEqual(f.files(), ["recaps/2026-10-26/r1.md", "sessions/2026-10-20/s1.md"])
        s = (f.out / "sessions/2026-10-20/s1.md").read_text()
        self.assertTrue(s.startswith('---\nsession: s1\ncwd: "/w/proj"\nstarted: "2026-10-20T10:00:00.000Z"\n---\n# find the bug in parser\n'))
        self.assertIn("## user 2026-10-20T10:00:00.000Z\n\nfind the bug in parser", s)
        self.assertIn("## assistant 2026-10-20T10:01:00.000Z\n\nit is in line 4", s)
        r = (f.out / "recaps/2026-10-26/r1.md").read_text()
        self.assertIn("session: sid-r1\nkind: single", r)
        self.assertIn("we decided X", r)
        self.assertTrue((f.out / ".qmd-corpus").exists())

    def test_filters_and_escaping(self):
        rows = jl(
            {"type": "session", "id": "s2", "timestamp": "2026-10-20T10:00:00Z", "cwd": "/c"},
            {"type": "session_info", "name": "My title"},
            {"type": "message", "timestamp": "t1", "message": {"role": "toolResult", "content": [{"type": "text", "text": "SECRET-TOOL-OUTPUT"}]}},
            {"type": "custom", "timestamp": "t2", "message": {"role": "user", "content": "CUSTOM-ENTRY"}},
            {"type": "message", "timestamp": "t3", "message": {"role": "system", "content": "SYSTEM-PROMPT"}},
            {"type": "message", "timestamp": "t4", "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": "THINK"}, {"type": "text", "text": "# not a heading\nbody"}]}},
            {"type": "message", "timestamp": "t5", "message": {"role": "user", "content": "x" * 5000}},
            {"type": "compaction", "timestamp": "t6", "summary": "COMPACTED " + "y" * 9000},
        )
        self.f.sess("s2", rows)
        self.f.run()
        s = (self.f.out / "sessions/2026-10-20/s2.md").read_text()
        for bad in ("SECRET-TOOL-OUTPUT", "CUSTOM-ENTRY", "SYSTEM-PROMPT", "THINK"):
            self.assertNotIn(bad, s)
        self.assertIn("# My title", s)
        self.assertIn("\\# not a heading", s)
        self.assertNotIn("\n# not a heading", s)
        self.assertIn("x" * 4000, s)
        self.assertNotIn("x" * 4001, s)
        self.assertIn("## compaction t6", s)
        self.assertIn("y" * 7000, s)
        self.assertNotIn("y" * 8000, s)

    def test_nested_subagent_session_and_duplicate_ids(self):
        f = self.f
        f.sess("dup", sub="--a--", name="a.jsonl")
        f.sess("dup", sub="--b--/run-0", name="session.jsonl", msgs=(("user", "second one"), ("assistant", "ok")))
        f.run()
        files = f.files("sessions")
        self.assertEqual(len(files), 2, files)
        self.assertIn("sessions/2026-10-20/dup.md", files)
        self.assertEqual(f.run().returncode, 0)
        self.assertEqual(f.files("sessions"), files, "stable across runs")

    def test_duplicate_ids_keep_the_right_content_when_the_first_one_goes_away(self):
        f = self.f
        a = f.sess("dup", sub="--a--", name="a.jsonl", msgs=(("user", "AAA content"), ("assistant", "ok")))
        f.sess("dup", sub="--b--", name="b.jsonl", msgs=(("user", "BBB content"), ("assistant", "ok")))
        f.run()
        texts = sorted((f.out / p).read_text() for p in f.files("sessions"))
        self.assertTrue("AAA content" in texts[0] + texts[1] and "BBB content" in texts[0] + texts[1])
        a.unlink()                                   # B now owns the plain name; A's output (newer than B) must not be reused
        f.run()
        files = f.files("sessions")
        self.assertEqual(len(files), 1)
        body = (f.out / files[0]).read_text()
        self.assertIn("BBB content", body)
        self.assertNotIn("AAA content", body)
        f.run()                                      # and it stays that way
        self.assertIn("BBB content", (f.out / f.files("sessions")[0]).read_text())

    def test_a_failed_write_does_not_hand_the_old_output_to_the_new_owner(self):
        f = self.f
        a = f.sess("dup", sub="--a--", name="a.jsonl", msgs=(("user", "AAA content"), ("assistant", "ok")))
        f.sess("dup", sub="--b--", name="b.jsonl", msgs=(("user", "BBB content"), ("assistant", "ok")))
        f.run()
        a.unlink()
        day = f.out / "sessions/2026-10-20"
        day.chmod(0o555)
        self.addCleanup(lambda: day.chmod(0o755))
        if os.access(day, os.W_OK):
            self.skipTest("running as a user that ignores permissions")
        f.run(check=1)
        day.chmod(0o755)
        f.run()
        files = f.files("sessions")
        self.assertEqual(len(files), 1)
        body = (f.out / files[0]).read_text()
        self.assertIn("BBB content", body)
        self.assertNotIn("AAA content", body)

    def test_nothing_to_index(self):
        f = self.f
        f.sess("empty", msgs=())
        f.sess("junk", "not json\n{broken\n")
        f.put(f.sessions / "x" / "notes.txt", "x")
        f.recap("nosummary", summary="")
        f.run()
        self.assertEqual(f.files(), [])


class ClaudeTest(Base):
    def test_layout_frontmatter_title_and_filters(self):
        f = self.f
        f.cc([
            {"type": "queue-operation", "operation": "enqueue", "timestamp": "2026-10-20T09:59:59.000Z", "sessionId": "cc1", "content": "QUEUED"},
            cc_user("find the parser bug"),
            {"type": "attachment", "attachment": {"type": "environment"}, "timestamp": "t", "sessionId": "cc1",
             "rendered": [{"content": "<system-reminder>ATTACHED-REMINDER</system-reminder>"}]},
            cc_user("<local-command-caveat>CAVEAT</local-command-caveat>", isMeta=True),
            cc_user("<system-reminder>\nINJECTED-REMINDER\n</system-reminder>"),
            cc_asst([{"type": "thinking", "thinking": "THINK"}, {"type": "text", "text": "# heading\nit is line 4"},
                     {"type": "tool_use", "name": "Bash", "input": {"command": "TOOL-CALL"}}]),
            cc_user([{"type": "tool_result", "content": "TOOL-OUTPUT"}]),
            cc_user([{"type": "text", "text": "and the lexer?"}], ts="2026-10-20T10:02:00.000Z"),
            cc_user("COMPACT " + "z" * 9000, isCompactSummary=True, ts="2026-10-20T10:03:00.000Z"),
            {"type": "ai-title", "aiTitle": "Old title", "sessionId": "cc1"},
            {"type": "ai-title", "aiTitle": "Parser bug hunt", "sessionId": "cc1"},
            {"type": "api-request-blob", "message": {"role": "user", "content": [{"type": "text", "text": "API-BLOB"}]}},
        ])
        f.run()
        self.assertEqual(f.files("claude-sessions"), ["claude-sessions/2026-10-20/cc1.md"])
        s = (f.out / "claude-sessions/2026-10-20/cc1.md").read_text()
        self.assertTrue(s.startswith('---\nsession: cc1\ncwd: "/w/proj"\nstarted: "2026-10-20T09:59:59.000Z"\n---\n# Parser bug hunt\n'), s[:200])
        self.assertIn("## user 2026-10-20T10:00:00.000Z\n\nfind the parser bug", s)
        self.assertIn("## assistant 2026-10-20T10:01:00.000Z\n\n\\# heading\nit is line 4", s)
        self.assertIn("## user 2026-10-20T10:02:00.000Z\n\nand the lexer?", s)
        self.assertIn("## compaction 2026-10-20T10:03:00.000Z", s)
        self.assertNotIn("z" * 8000, s)
        for bad in ("QUEUED", "ATTACHED-REMINDER", "CAVEAT", "INJECTED-REMINDER", "THINK", "TOOL-CALL", "TOOL-OUTPUT", "API-BLOB"):
            self.assertNotIn(bad, s)

    def test_custom_title_wins_and_first_prompt_is_the_fallback(self):
        f = self.f
        f.cc([cc_user("hello there"), cc_asst([{"type": "text", "text": "hi"}]),
              {"type": "ai-title", "aiTitle": "AI", "sessionId": "cc1"}, {"type": "custom-title", "customTitle": "Mine", "sessionId": "cc1"}])
        f.cc([cc_user("second prompt", sid="cc2"), cc_asst([{"type": "text", "text": "ok"}], sid="cc2")], rel="-w-proj/cc2.jsonl")
        f.run()
        self.assertIn("\n# Mine\n", (f.out / "claude-sessions/2026-10-20/cc1.md").read_text())
        self.assertIn("\n# second prompt\n", (f.out / "claude-sessions/2026-10-20/cc2.md").read_text())

    def test_subagent_transcripts_name_their_parent(self):
        f = self.f
        f.cc([cc_user("main"), cc_asst([{"type": "text", "text": "ok"}])])
        f.cc([cc_user("sub task", isSidechain=True), cc_asst([{"type": "text", "text": "done"}])],
             rel="-w-proj/cc1/subagents/agent-a1.jsonl")
        f.run()
        self.assertEqual(f.files("claude-sessions"), ["claude-sessions/2026-10-20/cc1-agent-a1.md", "claude-sessions/2026-10-20/cc1.md"])
        self.assertIn("session: cc1\n", (f.out / "claude-sessions/2026-10-20/cc1-agent-a1.md").read_text())

    def test_nothing_to_index_and_incremental(self):
        f = self.f
        f.cc([{"type": "queue-operation", "timestamp": "t", "sessionId": "e"}], rel="-x/e.jsonl")
        f.cc([cc_user("hi"), cc_asst([{"type": "text", "text": "yo"}])])
        f.run()
        self.assertEqual(f.files("claude-sessions"), ["claude-sessions/2026-10-20/cc1.md"])
        self.assertIn("claude-sessions: 0 written, 1 unchanged", f.run().stdout)


class CodexTest(Base):
    def test_layout_and_filters(self):
        f = self.f
        f.cx([
            cx_meta(),
            cx_msg("developer", "DEV-PERMISSIONS"),
            cx_msg("user", "# AGENTS.md instructions for /w\n\n<INSTRUCTIONS>\nAGENTS-BODY\n</INSTRUCTIONS>"),
            cx_msg("user", "<environment_context>\n  <cwd>/w</cwd>\n</environment_context>"),
            {"timestamp": "t", "type": "world_state", "payload": {"state": {"agents_md": {"text": "WORLD"}}}},
            cx_msg("user", "fix the flaky test", ts="2026-10-20T10:02:00.000Z"),
            {"timestamp": "t", "type": "response_item", "payload": {"type": "reasoning", "summary": [{"type": "summary_text", "text": "REASONING"}]}},
            {"timestamp": "t", "type": "response_item", "payload": {"type": "function_call", "name": "shell", "arguments": "TOOL-ARGS"}},
            {"timestamp": "t", "type": "response_item", "payload": {"type": "function_call_output", "output": "TOOL-OUTPUT"}},
            {"timestamp": "t", "type": "event_msg", "payload": {"type": "agent_message", "message": "EVENT-COPY"}},
            cx_msg("assistant", "## Done\nretried the clock", ts="2026-10-20T10:03:00.000Z"),
            {"timestamp": "2026-10-20T10:04:00.000Z", "type": "compacted", "payload": {"message": "COMPACTED SUMMARY"}},
        ])
        f.run()
        self.assertEqual(f.files("codex-sessions"), ["codex-sessions/2026-10-20/cx1.md"])
        s = (f.out / "codex-sessions/2026-10-20/cx1.md").read_text()
        self.assertTrue(s.startswith('---\nsession: cx1\ncwd: "/w/codex"\nstarted: "2026-10-20T10:00:00.000Z"\n---\n# fix the flaky test\n'), s[:200])
        self.assertIn("## user 2026-10-20T10:02:00.000Z\n\nfix the flaky test", s)
        self.assertIn("## assistant 2026-10-20T10:03:00.000Z\n\n\\## Done\nretried the clock", s)
        self.assertIn("## compaction 2026-10-20T10:04:00.000Z\n\nCOMPACTED SUMMARY", s)
        for bad in ("BASE-INSTR", "DEV-PERMISSIONS", "AGENTS-BODY", "environment_context", "WORLD", "REASONING", "TOOL-ARGS",
                    "TOOL-OUTPUT", "EVENT-COPY"):
            self.assertNotIn(bad, s)

    def test_only_injected_context_is_nothing_to_index(self):
        f = self.f
        f.cx([cx_meta(), cx_msg("user", "<environment_context>x</environment_context>")])
        f.cx(["not json"], rel="2026/10/20/bad.jsonl")
        f.run()
        self.assertEqual(f.files("codex-sessions"), [])


class SourcesTest(Base):
    def test_every_collection_folder_exists_even_without_sources(self):
        f = self.f
        for d in (f.claude, f.codex):
            d.rmdir()
        p = f.run()
        self.assertIn("claude-sessions: source", p.stderr)
        for kind in ("sessions", "claude-sessions", "codex-sessions", "recaps"):
            self.assertTrue((f.out / kind).is_dir(), kind)

    def test_one_missing_root_does_not_prune_another_kind(self):
        f = self.f
        f.cc([cc_user("hi"), cc_asst([{"type": "text", "text": "yo"}])])
        f.cx([cx_meta(), cx_msg("user", "hi"), cx_msg("assistant", "yo")])
        f.sess("s1")
        f.run()
        mine = f.files()
        self.assertEqual(len(mine), 3, mine)
        subprocess.run(["rm", "-rf", str(f.claude)])
        f.run()
        self.assertEqual(f.files(), mine, "a missing ~/.claude must not wipe its corpus or the others")
        (f.codex / "2026/10/20/rollout-2026-10-20T10-00-00-cx1.jsonl").unlink()
        f.run()
        self.assertEqual(f.files(), [m for m in mine if not m.startswith("codex-")])


class IncrementalTest(Base):
    def counts(self, f):
        out = f.run().stdout
        return out

    def test_second_run_writes_nothing_and_never_reads_unchanged_files(self):
        f = self.f
        f.sess("s1")
        f.recap("r1")
        f.sess("empty", msgs=())
        f.run()
        before = {p: (f.out / p).stat().st_mtime_ns for p in f.files()}
        out = f.run().stdout
        self.assertIn("sessions: 0 written, 1 unchanged", out)
        self.assertIn("recaps: 0 written, 1 unchanged", out)
        self.assertEqual({p: (f.out / p).stat().st_mtime_ns for p in f.files()}, before)

    def test_unchanged_sources_are_not_even_opened_whole(self):
        f = self.f
        p = f.sess("s1")
        f.run()
        good = p.read_text()
        p.write_text(good.split("\n")[0] + "\nGARBAGE THAT WOULD NOT PARSE\n")   # same header, rest corrupted...
        old = time.time() - 3600
        os.utime(p, (old, old))                                                   # ...but not newer than the output
        f.run()
        self.assertIn("hello world", (f.out / "sessions/2026-10-20/s1.md").read_text())

    def test_a_changed_source_is_rewritten(self):
        f = self.f
        p = f.sess("s1")
        f.run()
        time.sleep(0.05)
        f.put(p, session("s1", msgs=(("user", "hello world"), ("assistant", "hi there"), ("user", "a follow up"))))
        self.assertIn("sessions: 1 written", f.run().stdout)
        self.assertIn("a follow up", (f.out / "sessions/2026-10-20/s1.md").read_text())

    def test_a_source_with_nothing_to_export_is_remembered_by_mtime(self):
        f = self.f
        p = f.sess("e", msgs=())
        f.run()
        st = p.stat()
        p.write_text(session("e"))
        os.utime(p, (st.st_atime, st.st_mtime))      # content changed, mtime did not: the remembered verdict stands
        f.run()
        self.assertEqual(f.files(), [])

    def test_an_empty_session_is_not_reread_until_it_changes(self):
        f = self.f
        p = f.sess("e", msgs=())
        f.run()
        self.assertEqual(f.files(), [])
        time.sleep(0.05)
        f.put(p, session("e"))
        f.run()
        self.assertEqual(f.files("sessions"), ["sessions/2026-10-20/e.md"])


class PruneTest(Base):
    def test_old_sources_are_not_exported_and_aged_outputs_go(self):
        f = self.f
        f.sess("new", age_days=1)
        f.sess("old", age_days=400, name="old.jsonl")
        f.recap("rnew", age_days=1)
        f.recap("rold", day="2026-05-01", age_days=400)
        out = f.run().stdout
        self.assertEqual(f.files(), ["recaps/2026-10-26/rnew.md", "sessions/2026-10-20/new.md"])
        self.assertIn("1 older than 365 days", out)
        # now the new session ages out
        new = f.sessions / "--w-proj--" / "2026-10-20T10-00-00-000Z_new.jsonl"
        t = time.time() - 370 * DAY
        os.utime(new, (t, t))
        f.run()
        self.assertEqual(f.files("sessions"), [])
        self.assertFalse((f.out / "sessions/2026-10-20").exists(), "empty day dir removed")

    def test_days_option(self):
        f = self.f
        f.sess("a", age_days=5)
        f.sess("b", age_days=20, name="b.jsonl", started="2026-10-01T00:00:00Z")
        f.run("--days", "10")
        self.assertEqual(f.files("sessions"), ["sessions/2026-10-20/a.md"])

    def test_deleted_source_is_pruned_and_stale_temp_files_go(self):
        f = self.f
        p = f.sess("gone")
        f.recap("keep")
        f.run()
        p.unlink()
        (f.out / "sessions/2026-10-20").mkdir(parents=True, exist_ok=True)
        (f.out / "recaps/2026-10-26/keep.md.tmp-123").write_text("half")
        f.run()
        self.assertEqual(f.files(), ["recaps/2026-10-26/keep.md"])
        self.assertFalse((f.out / "recaps/2026-10-26/keep.md.tmp-123").exists())

    def test_a_missing_or_unreadable_source_root_prunes_nothing(self):
        f = self.f
        f.sess("s1")
        f.recap("r1")
        f.run()
        mine = f.files()
        subprocess.run(["rm", "-rf", str(f.sessions)])
        p = f.run()
        self.assertIn("does not exist", p.stderr)
        self.assertEqual(f.files(), mine, "an unmounted or moved root must not wipe the corpus")
        f.sessions.mkdir()
        f.sess("s1")
        d = f.sessions / "--locked--"
        d.mkdir()
        d.chmod(0)
        self.addCleanup(lambda: d.chmod(0o755))
        if os.access(d, os.R_OK):
            self.skipTest("running as a user that ignores permissions")
        p = f.run(check=1)
        self.assertEqual(f.files(), mine)

    def test_a_source_that_cannot_be_stat_ed_prunes_nothing(self):
        f = self.f
        f.sess("s1", sub="--ok--")
        f.sess("s2", sub="--locked--", name="b.jsonl")
        f.run()
        mine = f.files()
        d = f.sessions / "--locked--"
        d.chmod(0o444)                                # listable, but its entries cannot be stat-ed
        self.addCleanup(lambda: d.chmod(0o755))
        if os.access(d / "b.jsonl", os.R_OK):
            self.skipTest("running as a user that ignores permissions")
        p = f.run(check=1)
        self.assertIn("Permission denied", p.stderr)
        self.assertEqual(f.files(), mine)

    def test_a_second_exporter_is_refused_while_one_runs(self):
        f = self.f
        f.sess("s1")
        f.run()
        before = f.files()
        with open(f.out / ".qmd-export.lock", "a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            f.sess("s2", name="s2.jsonl")
            p = f.run(check=3)
            self.assertIn("another qmd-export", p.stderr)
            self.assertEqual(f.files(), before)
            f.run("--dry-run")                         # a dry run only reads, so it does not need the lock
        f.run()
        self.assertEqual(len(f.files("sessions")), 2)

    def test_dry_run_changes_nothing(self):
        f = self.f
        f.sess("s1")
        f.run("--dry-run")
        self.assertFalse(f.out.exists())
        f.run()
        before = f.files()
        f.sess("s2", name="s2.jsonl")
        (f.sessions / "--w-proj--" / "2026-10-20T10-00-00-000Z_s1.jsonl").unlink()
        out = f.run("--dry-run").stdout
        self.assertEqual(f.files(), before)
        self.assertIn("1 written", out)
        self.assertIn("1 pruned", out)

    def test_refuses_a_directory_it_did_not_make(self):
        f = self.f
        f.out.mkdir()
        (f.out / "important.md").write_text("mine")
        f.sess("s1")
        p = f.run(check=2)
        self.assertIn("refusing", p.stderr)
        self.assertEqual(sorted(x.name for x in f.out.iterdir()), ["important.md"])
        self.assertEqual((f.out / "important.md").read_text(), "mine")


class ArgsTest(Base):
    def test_bad_days(self):
        p = self.f.run("--days", "0", check=2)
        self.assertIn("--days", p.stderr)

    def test_quiet(self):
        self.f.sess("s1")
        self.assertEqual(self.f.run("-q").stdout, "")

    def test_defaults_are_relative_to_home(self):
        home = self.f.root / "home"
        (home / ".pi/agent/sessions/--x--").mkdir(parents=True)
        self.f.put(home / ".pi/agent/sessions/--x--/a.jsonl", session("hs"))
        self.f.put(home / ".local/share/session-recap/records/2026-10-26/rr.json",
                   json.dumps({"record_id": "rr", "created_at": "2026-10-26T00:00:00Z", "summary": "s"}))
        p = subprocess.run([sys.executable, str(SCRIPT)], env=dict(os.environ, HOME=str(home)), capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue((home / ".local/share/qmd-corpus/sessions/2026-10-20/hs.md").exists())
        self.assertTrue((home / ".local/share/qmd-corpus/recaps/2026-10-26/rr.md").exists())
        self.assertIn("claude-sessions: source %s/.claude/projects does not exist" % home, p.stderr)
        self.assertIn("codex-sessions: source %s/.codex/sessions does not exist" % home, p.stderr)


def ts_at(s):
    """A T3-style stamp s seconds after 2026-10-20T10:00:00Z (the day the fixtures use)."""
    t = datetime(2026, 10, 20, 10, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=s)
    return t.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def t3_db(path, threads, projects=(("p1", "widgets"),)):
    """A T3 state db with T3's table and column names (the ones the exporter reads, plus the NOT NULL ones), written with the
    sqlite3 module here. A thread: id, title, claude (a Claude session id), codex (a Codex session id), parent (a thread id),
    updated, project, and messages [(stamp, text, 'user' or 'agent')] in order."""
    db = sqlite3.connect(str(path))
    db.executescript("""
        CREATE TABLE projection_projects (project_id TEXT PRIMARY KEY, title TEXT NOT NULL);
        CREATE TABLE orchestration_v2_projection_threads (thread_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, title TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT, payload_json TEXT NOT NULL);
        CREATE TABLE orchestration_v2_projection_provider_threads (provider_thread_id TEXT PRIMARY KEY, thread_id TEXT,
            driver TEXT, payload_json TEXT NOT NULL);
        CREATE TABLE orchestration_v2_projection_messages (message_id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, role TEXT NOT NULL,
            streaming INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload_json TEXT NOT NULL);
    """)
    db.executemany("INSERT INTO projection_projects VALUES (?, ?)", projects)
    for t in threads:
        last = t["messages"][-1][0] if t.get("messages") else ts_at(0)
        lineage = {"lineage": {"parentThreadId": t["parent"]}} if t.get("parent") else {}
        db.execute("INSERT INTO orchestration_v2_projection_threads VALUES (?, ?, ?, ?, ?, NULL, ?)",
                   (t["id"], t.get("project", "p1"), t["title"], last, t.get("updated", last), json.dumps({"id": t["id"], **lineage})))
        for driver, key in (("claudeAgent", "claude"), ("codex", "codex")):
            if t.get(key):
                db.execute("INSERT INTO orchestration_v2_projection_provider_threads VALUES (?, ?, ?, ?)",
                           ("pt-%s-%s" % (t["id"], driver), t["id"], driver,
                            json.dumps({"driver": driver, "nativeThreadRef": {"driver": driver, "nativeId": t[key]}})))
        for i, (at, text, by) in enumerate(t.get("messages", [])):
            db.execute("INSERT INTO orchestration_v2_projection_messages VALUES (?, ?, 'user', 0, ?, ?, ?)",
                       ("%s-m%d" % (t["id"], i), t["id"], at, at, json.dumps({"text": text, "createdBy": by})))
    db.commit()
    db.close()


class T3Test(Base):
    def setUp(self):
        super().setUp()
        self.db = self.f.root / "statev2.sqlite"

    def use(self, threads, **kw):
        t3_db(self.db, threads, **kw)
        self.f.t3db = self.db

    def db_exec(self, sql, args=()):
        db = sqlite3.connect(str(self.db))
        db.execute(sql, args)
        db.commit()
        db.close()

    def claude_out(self, name="cc1"):
        return (self.f.out / ("claude-sessions/2026-10-20/%s.md" % name)).read_text()

    def test_header_carries_the_thread_title_project_and_parent(self):
        f = self.f
        f.cc([cc_user("plan the work"), cc_asst([{"type": "text", "text": "ok"}])])
        self.use([{"id": "P1", "title": "Coordinator"},
                  {"id": "T1", "title": "Fix   the build", "claude": "cc1", "parent": "P1", "messages": [(ts_at(0), "plan the work", "agent")]}])
        f.run()
        self.assertTrue(self.claude_out().startswith(
            '---\nsession: cc1\ncwd: "/w/proj"\nstarted: "2026-10-20T10:00:00.000Z"\n'
            't3_thread: "T1"\nt3_title: "Fix the build"\nt3_project: "widgets"\nt3_parent: "P1"\nt3_parent_title: "Coordinator"\n'
            '---\n# Fix the build\n'), self.claude_out()[:300])

    def test_owner_and_agent_turns_are_marked_and_unmatched_turns_stay_user(self):
        f = self.f
        f.cc([cc_user("plan the work", ts="2026-10-20T10:00:00.050Z"),
              cc_asst([{"type": "text", "text": "planned"}]),
              cc_user("no,   not that\nthe other one", ts="2026-10-20T10:01:00.070Z"),
              cc_user("typed in a terminal", ts="2026-10-20T10:05:00.000Z")])
        self.use([{"id": "T1", "title": "Fix", "claude": "cc1", "messages": [
            (ts_at(0), "plan the work", "agent"), (ts_at(60), "no, not that the other one", "user")]}])
        f.run()
        s = self.claude_out()
        self.assertIn("## agent 2026-10-20T10:00:00.050Z\n\nplan the work\n", s)
        self.assertIn("## owner 2026-10-20T10:01:00.070Z\n\nno,   not that\nthe other one\n", s)
        self.assertIn("## user 2026-10-20T10:05:00.000Z\n\ntyped in a terminal\n", s)
        self.assertIn("## assistant 2026-10-20T10:01:00.000Z\n\nplanned\n", s)
        self.assertEqual((s.count("## owner "), s.count("## agent ")), (1, 1))

    def test_repeated_text_pairs_by_time_and_each_t3_message_is_used_once(self):
        f = self.f
        f.cc([cc_user("yes", ts="2026-10-20T10:00:30.100Z"), cc_user("yes", ts="2026-10-20T10:00:10.100Z"),
              cc_user("yes", ts="2026-10-20T10:00:50.000Z")])
        self.use([{"id": "T1", "title": "Yes", "claude": "cc1", "messages": [(ts_at(10), "yes", "user"), (ts_at(30), "yes", "agent")]}])
        f.run()
        s = self.claude_out()
        self.assertIn("## agent 2026-10-20T10:00:30.100Z\n\nyes", s)
        self.assertIn("## owner 2026-10-20T10:00:10.100Z\n\nyes", s)
        self.assertIn("## user 2026-10-20T10:00:50.000Z\n\nyes", s)     # no T3 message is left for it

    def test_subagent_files_carry_the_parent_title_and_no_marks(self):
        f = self.f
        f.cc([cc_user("plan the work", ts="2026-10-20T10:00:00.050Z")])
        f.cc([cc_user("plan the work", ts="2026-10-20T10:00:00.060Z", isSidechain=True)], rel="-w-proj/cc1/subagents/agent-a1.jsonl")
        self.use([{"id": "T1", "title": "Parent work", "claude": "cc1", "messages": [(ts_at(0), "plan the work", "agent")]}])
        f.run()
        sub = (f.out / "claude-sessions/2026-10-20/cc1-agent-a1.md").read_text()
        self.assertIn("## agent 2026-10-20T10:00:00.050Z", self.claude_out())
        self.assertIn('t3_title: "Parent work"\n', sub)
        self.assertIn("\n# Parent work\n", sub)
        self.assertIn("## user 2026-10-20T10:00:00.060Z\n\nplan the work", sub)
        self.assertNotIn("## owner ", sub)
        self.assertNotIn("## agent ", sub)

    def test_sessions_without_a_t3_thread_are_as_before(self):
        f = self.f
        f.cc([cc_user("plan the work"), cc_asst([{"type": "text", "text": "ok"}])])
        self.use([{"id": "T9", "title": "Other", "claude": "cc9", "messages": [(ts_at(0), "plan the work", "agent")]}])
        f.run()
        s = self.claude_out()
        self.assertTrue(s.startswith('---\nsession: cc1\ncwd: "/w/proj"\nstarted: "2026-10-20T10:00:00.000Z"\n---\n# plan the work\n'), s[:200])
        self.assertIn("## user 2026-10-20T10:00:00.000Z\n\nplan the work", s)
        self.assertNotIn("t3_", s)

    def test_a_missing_db_is_silent_and_adds_nothing(self):
        f = self.f
        f.cc([cc_user("plan the work")])
        p = f.run()                                  # self.f.t3db is the missing default
        self.assertEqual(p.stderr, "")
        self.assertNotIn("t3_", self.claude_out())
        self.assertIn("## user 2026-10-20T10:00:00.000Z", self.claude_out())

    def test_a_foreign_schema_or_a_file_that_is_not_a_database_is_silent(self):
        f = self.f
        f.cc([cc_user("plan the work")])
        db = sqlite3.connect(str(self.db))
        db.execute("CREATE TABLE other (x TEXT)")
        db.commit()
        db.close()
        f.t3db = self.db
        p = f.run()
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        self.assertNotIn("t3_", self.claude_out())
        junk = f.root / "junk.sqlite"
        junk.write_bytes(b"not a database\n" * 20)
        f.t3db = junk
        p = f.run()
        self.assertEqual((p.returncode, p.stderr), (0, ""))

    def test_the_db_is_never_written(self):
        f = self.f
        f.cc([cc_user("plan the work")])
        self.use([{"id": "T1", "title": "Fix", "claude": "cc1", "messages": [(ts_at(0), "plan the work", "agent")]}])
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        f.run()
        f.run()
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), before)
        self.assertFalse(Path(str(self.db) + "-journal").exists())

    def test_a_t3_title_change_re_renders_the_session_and_nothing_else(self):
        f = self.f
        src = f.cc([cc_user("plan the work", ts="2026-10-20T10:00:00.050Z")])
        self.use([{"id": "T1", "title": "Old title", "claude": "cc1", "messages": [(ts_at(0), "plan the work", "agent")]}])
        f.run()
        self.assertIn("\n# Old title\n", self.claude_out())
        src_mtime = src.stat().st_mtime_ns
        self.db_exec("UPDATE orchestration_v2_projection_threads SET title = 'New title' WHERE thread_id = 'T1'")
        self.assertIn("claude-sessions: 1 written", f.run().stdout)
        self.assertIn('t3_title: "New title"\n', self.claude_out())
        self.assertIn("\n# New title\n", self.claude_out())
        self.assertEqual(src.stat().st_mtime_ns, src_mtime)
        self.assertIn("claude-sessions: 0 written, 1 unchanged", f.run().stdout)

    def test_a_t3_message_change_re_renders_the_marks(self):
        f = self.f
        f.cc([cc_user("plan the work", ts="2026-10-20T10:00:00.050Z")])
        self.use([{"id": "T1", "title": "Fix", "claude": "cc1", "messages": [(ts_at(0), "plan the work", "agent")]}])
        f.run()
        self.assertIn("## agent 2026-10-20T10:00:00.050Z", self.claude_out())
        self.db_exec("UPDATE orchestration_v2_projection_messages SET payload_json = ? WHERE message_id = 'T1-m0'",
                     (json.dumps({"text": "plan the work", "createdBy": "user"}),))
        self.assertIn("claude-sessions: 1 written", f.run().stdout)
        self.assertIn("## owner 2026-10-20T10:00:00.050Z", self.claude_out())

    def test_removing_the_db_re_renders_without_t3_fields(self):
        f = self.f
        f.cc([cc_user("plan the work", ts="2026-10-20T10:00:00.050Z")])
        self.use([{"id": "T1", "title": "Fix", "claude": "cc1", "messages": [(ts_at(0), "plan the work", "agent")]}])
        f.run()
        self.assertIn("t3_title", self.claude_out())
        f.t3db = f.root / "gone.sqlite"
        self.assertIn("claude-sessions: 1 written", f.run().stdout)
        self.assertNotIn("t3_", self.claude_out())
        self.assertIn("## user 2026-10-20T10:00:00.050Z", self.claude_out())

    def test_a_codex_thread_is_not_a_claude_session_and_is_not_exported_twice(self):
        f = self.f
        f.cx([cx_meta("cx1"), cx_msg("user", "plan the work")])
        self.use([{"id": "C1", "title": "Codex thread", "codex": "cx1", "messages": [(ts_at(0), "plan the work", "user")]}])
        f.run()
        self.assertEqual(f.files("codex-sessions"), ["codex-sessions/2026-10-20/cx1.md"])
        self.assertNotIn("t3_", (f.out / "codex-sessions/2026-10-20/cx1.md").read_text())
        self.assertEqual(f.files("claude-sessions"), [])


def load_script():
    """The script as a module, for the matching rules (the black-box tests above cover the files)."""
    loader = importlib.machinery.SourceFileLoader("qmd_export", str(SCRIPT))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader("qmd_export", loader))
    loader.exec_module(module)
    return module


class MarkTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_script()

    def marks(self, turns, messages):
        return self.m.mark_authors([(ts_at(s), t) for s, t in turns], [(ts_at(s), t, who) for s, t, who in messages])

    def test_same_text_after_whitespace_normalisation_in_order(self):
        self.assertEqual(self.marks([(0.05, "Plan   the work"), (60.1, "no, not that the other one")],
                                    [(0, "Plan the work", "agent"), (60, "no,   not that\nthe other one", "owner")]), ["agent", "owner"])

    def test_each_t3_message_is_used_once_and_repeats_pair_by_time(self):
        self.assertEqual(self.marks([(30.1, "yes"), (10.1, "yes")], [(10, "yes", "owner"), (30, "yes", "agent")]), ["agent", "owner"])
        self.assertEqual(self.marks([(10, "yes"), (11, "yes"), (12, "yes")], [(10, "yes", "owner"), (11, "yes", "owner")]),
                         ["owner", "owner", None])

    def test_wrapper_text_around_the_t3_text(self):
        self.assertEqual(self.marks([(5.2, "<system-reminder>\nThe date changed.\n</system-reminder>\ndo the thing please")],
                                    [(5, "do the thing please", "owner")]), ["owner"])

    def test_wrapped_text_far_away_in_time_does_not_match(self):
        self.assertEqual(self.marks([(50, "<system-reminder>x</system-reminder> ok")], [(5, "ok", "owner")]), [None])

    def test_time_fallback_when_the_text_differs(self):
        self.assertEqual(self.marks([(7.4, "Ultrathink: fix it")], [(7, "fix it", "owner")]), ["owner"])
        self.assertEqual(self.marks([(7.4, "Ultrathink: fix that")], [(7, "fix it", "owner")]), ["owner"])

    def test_nothing_fits_stays_unmarked(self):
        self.assertEqual(self.marks([(40, "[Request interrupted by user]"), (41, "something else")], [(0, "Plan the work", "agent")]),
                         [None, None])

    def test_time_fallback_does_not_steal_a_message_another_turn_matches_by_text(self):
        self.assertEqual(self.marks([(10.1, "first"), (10.3, "mystery")], [(10, "first", "owner")]), ["owner", None])

    def test_stamps(self):
        self.assertEqual(self.m.ms_of("2026-10-20T10:00:00.050Z") - self.m.ms_of("2026-10-20T10:00:00.000Z"), 50)
        self.assertEqual(self.m.ms_of("2026-10-20T11:00:00.000+01:00"), self.m.ms_of("2026-10-20T10:00:00.000Z"))
        self.assertIsNone(self.m.ms_of("yesterday"))


if __name__ == "__main__":
    unittest.main()
