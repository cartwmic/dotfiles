"""Black-box tests for the capability-tier resolver: the real registry template is rendered with chezmoi,
then the real resolve.py runs as a subprocess against scripted quota fixtures. No provider is called.

    python3 -m unittest discover -s tests/capability-tiers -v
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / "dot_local" / "share" / "agent-harness" / "capability-tiers"
TEMPLATE = DIR / "tiers.toml.tmpl"
RESOLVER = DIR / "executable_resolve.py"
NOW = datetime(2026, 10, 21, 12, 0, 0, tzinfo=timezone.utc)

OPUS = "claude-compat/claude-opus-5-5"
SOL = "openai-codex/gpt-6.1-sol"
ASTRA = "openai-codex/gpt-6-astra"
HAIKU = "claude-compat/claude-haiku-5-5"
SONNET = "claude-compat/claude-sonnet-5-5"
LUNA = "openai-codex/gpt-6-luna"


def render(profile):
    with tempfile.TemporaryDirectory() as tmp:
        config = Path(tmp) / "chezmoi.yaml"
        config.write_text("{}\n")  # no hooks from the developer's own config
        result = subprocess.run(
            ["chezmoi", "--source", str(ROOT), "--config", str(config), "execute-template", "--override-data", json.dumps({"profile": profile})],
            input=TEMPLATE.read_text(encoding="utf-8"), capture_output=True, text=True, timeout=120,
        )
    assert result.returncode == 0, result.stderr
    return result.stdout


def window(label, percent, reset_in_hours=24):
    return {"label": label, "usedPercent": percent, "resetAt": (NOW + timedelta(hours=reset_in_hours)).isoformat()}


def pool(*windows, age=5):
    return {"fetchedAt": int((NOW - timedelta(seconds=age)).timestamp() * 1000), "usage": {"windows": list(windows)}}


def healthy():
    return {"anthropic": pool(window("5h", 15), window("Week", 18)), "codex": pool(window("Week", 43))}


@unittest.skipUnless(shutil.which("chezmoi"), "chezmoi not installed")
class ResolverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.registry = cls.dir / "tiers.toml"
        cls.registry.write_text(render("personal"))
        cls.work_registry = cls.dir / "work.toml"
        cls.work_registry.write_text(render("axon-work-computer"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_resolver(self, quota, *args, registry=None):
        qpath = self.dir / "quota.json"
        qpath.write_text(json.dumps(quota))
        cmd = [sys.executable, str(RESOLVER), "--registry", str(registry or self.registry), "--quota", str(qpath),
               "--now", NOW.isoformat(), "--json", *args]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        plan = json.loads(result.stdout) if result.stdout.strip() else None
        return result.returncode, plan, result.stderr

    def by_slot(self, plan):
        return {a["slot"]: a for a in plan["assignments"]}

    # (a) all pools healthy
    def test_healthy_pools_give_the_role_defaults_and_opus_leads_high(self):
        code, plan, _ = self.run_resolver(healthy(), "--slot", "driver", "--slot", "implementer", "--slot", "ordinary-reviewer", "--slot", "challenge-reviewer")
        self.assertEqual(code, 0)
        a = self.by_slot(plan)
        self.assertEqual((a["driver"]["model"], a["driver"]["effort"]), (SONNET, "high"))
        self.assertEqual((a["implementer"]["model"], a["implementer"]["effort"]), (HAIKU, "xhigh"))
        self.assertEqual((a["ordinary-reviewer"]["model"], a["ordinary-reviewer"]["effort"]), (OPUS, "high"))
        # two peer reviewers get different models when the tier allows it
        self.assertEqual((a["challenge-reviewer"]["model"], a["challenge-reviewer"]["effort"]), (SOL, "xhigh"))
        self.assertNotIn("same_model_review", a["ordinary-reviewer"])
        self.assertNotIn("same_model_review", a["challenge-reviewer"])
        self.assertEqual(a["driver"]["tier_origin"], "role default")
        self.assertEqual(plan["registry"]["profile"], "personal")
        self.assertEqual(len(plan["registry"]["sha256"]), 64)

    def test_two_implementers_may_share_a_model_without_a_flag(self):
        code, plan, _ = self.run_resolver(healthy(), "--slot", "T1=implementer", "--slot", "T2=implementer")
        self.assertEqual(code, 0)
        self.assertEqual({a["model"] for a in plan["assignments"]}, {HAIKU})
        self.assertTrue(all("same_model_review" not in a for a in plan["assignments"]))

    # (b) Claude pool exhausted
    def test_claude_exhausted_moves_every_tier_to_the_other_pool_and_records_it(self):
        quota = healthy()
        quota["anthropic"] = pool(window("5h", 40), window("Week", 100, reset_in_hours=30))
        code, plan, _ = self.run_resolver(quota, "--slot", "driver", "--slot", "implementer", "--slot", "ordinary-reviewer", "--slot", "challenge-reviewer")
        self.assertEqual(code, 0)
        a = self.by_slot(plan)
        self.assertEqual((a["driver"]["model"], a["driver"]["effort"]), (SOL, "medium"))
        self.assertEqual(a["driver"]["fallback"]["from"], SONNET + "@high")
        self.assertEqual((a["implementer"]["model"], a["implementer"]["effort"]), (LUNA, "max"))
        self.assertEqual((a["ordinary-reviewer"]["model"], a["ordinary-reviewer"]["effort"]), (SOL, "xhigh"))
        self.assertEqual((a["challenge-reviewer"]["model"], a["challenge-reviewer"]["effort"]), (ASTRA, "high"))
        self.assertEqual(a["ordinary-reviewer"]["fallback"]["from"], OPUS + "@high")
        self.assertIn("exhausted", a["ordinary-reviewer"]["skipped"][0]["reason"])
        self.assertTrue(all(ass["tier"] == t for ass, t in [(a["driver"], "medium"), (a["implementer"], "low")]))

    # (c) Codex exhausted, two reviewers -> same-model review is flagged, not blocked
    def test_codex_exhausted_leaves_one_high_model_and_flags_same_model_review(self):
        quota = healthy()
        quota["codex"] = pool(window("Week", 100, reset_in_hours=50))
        code, plan, _ = self.run_resolver(quota, "--slot", "ordinary-reviewer", "--slot", "challenge-reviewer")
        self.assertEqual(code, 0)
        a = self.by_slot(plan)
        self.assertEqual({x["model"] for x in a.values()}, {OPUS})
        self.assertNotIn("same_model_review", a["ordinary-reviewer"])
        self.assertEqual(a["challenge-reviewer"]["same_model_review"], ["ordinary-reviewer"])
        self.assertTrue(any("same-model review" in w for w in plan["warnings"]))

    # (d) both pools exhausted -> fail closed with the reset time
    def test_all_pools_exhausted_fails_closed_with_earliest_reset(self):
        quota = {"anthropic": pool(window("Week", 100, reset_in_hours=30)), "codex": pool(window("Week", 100, reset_in_hours=10))}
        code, plan, _ = self.run_resolver(quota, "--slot", "ordinary-reviewer")
        self.assertEqual(code, 2)
        a = plan["assignments"][0]
        self.assertEqual(a["status"], "unavailable")
        self.assertNotIn("model", a)
        self.assertEqual(a["earliest_reset"], (NOW + timedelta(hours=10)).isoformat())
        self.assertEqual(a["tier"], "high")  # never fell to a lower tier

    def test_reported_exhaustion_counts_even_when_the_cache_looks_healthy(self):
        code, plan, _ = self.run_resolver(healthy(), "--exhausted", "anthropic", "--slot", "implementer")
        self.assertEqual(code, 0)
        self.assertEqual(plan["assignments"][0]["model"], LUNA)

    # (e) overrides and their origin
    def test_slot_run_and_role_overrides_follow_precedence_and_are_recorded(self):
        code, plan, _ = self.run_resolver(
            healthy(), "--run-tier", "medium", "--run-effort", "low",
            "--slot", "T3=implementer|tier=high|effort=max|reason=touches auth",
            "--slot", "T1=implementer", "--slot", "T2=implementer|effort=xhigh")
        self.assertEqual(code, 0)
        a = self.by_slot(plan)
        self.assertEqual(a["T3"]["tier"], "high")
        self.assertEqual(a["T3"]["tier_origin"], "slot override (touches auth)")
        self.assertEqual((a["T3"]["model"], a["T3"]["effort"], a["T3"]["effort_origin"]), (OPUS, "max", "slot override"))
        self.assertEqual((a["T1"]["tier"], a["T1"]["tier_origin"], a["T1"]["model"], a["T1"]["effort"]), ("medium", "run override", SONNET, "low"))
        self.assertEqual((a["T2"]["effort"], a["T2"]["effort_origin"], a["T2"]["candidate_effort"]), ("xhigh", "slot override", "high"))

    def test_unknown_role_uses_the_default_tier(self):
        code, plan, _ = self.run_resolver(healthy(), "--slot", "spelunker")
        self.assertEqual(code, 0)
        a = plan["assignments"][0]
        self.assertEqual((a["tier"], a["tier_origin"]), ("medium", "global default (role not in registry)"))

    # (f) unknown model id warns
    def test_known_models_list_warns_about_missing_ids(self):
        known = self.dir / "models.txt"
        known.write_text("provider       model   context\nclaude-compat  claude-haiku-5-5  1M\n")
        code, plan, _ = self.run_resolver(healthy(), "--known-models", str(known), "--slot", "implementer", "--slot", "driver")
        self.assertEqual(code, 0)
        self.assertEqual(len(plan["warnings"]), 1)
        self.assertIn(SONNET, plan["warnings"][0])

    # quota staleness and the near-limit hint
    def test_stale_quota_is_unknown_but_still_selectable_with_a_warning(self):
        quota = healthy()
        quota["anthropic"] = pool(window("Week", 100), age=601)
        code, plan, _ = self.run_resolver(quota, "--slot", "driver")
        self.assertEqual(code, 0)
        self.assertEqual(plan["assignments"][0]["model"], SONNET)
        status = {p["pool"]: p for p in plan["quota"]}["anthropic"]
        self.assertEqual(status["status"], "unknown")
        self.assertIn("stale", status["reason"])
        self.assertTrue(any("anthropic" in w for w in plan["warnings"]))

    def test_stale_threshold_is_configurable_and_defaults_to_ten_minutes(self):
        quota = healthy()
        quota["anthropic"] = pool(window("Week", 18), age=300)
        _, plan, _ = self.run_resolver(quota, "--slot", "driver")
        self.assertEqual(plan["stale_after_seconds"], 600)
        self.assertEqual({p["pool"]: p for p in plan["quota"]}["anthropic"]["status"], "ok")
        _, plan, _ = self.run_resolver(quota, "--stale-after", "60", "--slot", "driver")
        self.assertEqual(plan["stale_after_seconds"], 60)
        self.assertEqual({p["pool"]: p for p in plan["quota"]}["anthropic"]["status"], "unknown")

    def test_near_limit_is_a_hint_and_never_excludes_a_candidate(self):
        quota = healthy()
        quota["anthropic"] = pool(window("5h", 99))
        code, plan, _ = self.run_resolver(quota, "--slot", "implementer")
        self.assertEqual(code, 0)
        self.assertEqual(plan["assignments"][0]["model"], HAIKU)
        self.assertEqual({p["pool"]: p for p in plan["quota"]}["anthropic"]["status"], "near-limit")

    def test_a_window_that_already_reset_is_ignored(self):
        quota = healthy()
        quota["anthropic"] = pool(window("5h", 100, reset_in_hours=-1))
        code, plan, _ = self.run_resolver(quota, "--slot", "implementer")
        self.assertEqual(code, 0)
        self.assertEqual(plan["assignments"][0]["model"], HAIKU)

    def test_disabled_provider_is_skipped_by_config_not_by_code(self):
        registry = self.dir / "custom.toml"
        registry.write_text(self.registry.read_text().replace('[providers.openrouter]\npool = "openrouter"\nenabled = false', '[providers.openrouter]\npool = "openrouter"')
                            .replace('"claude-compat/claude-haiku-5-5@xhigh",', '"openrouter/z-ai/glm-5.3-flash@high",\n  "claude-compat/claude-haiku-5-5@xhigh",'))
        quota = healthy()
        quota["openrouter"] = pool({"label": "Credits", "usedPercent": 10})
        code, plan, _ = self.run_resolver(quota, "--slot", "implementer", registry=registry)
        self.assertEqual((code, plan["assignments"][0]["model"]), (0, "openrouter/z-ai/glm-5.3-flash"))
        disabled = self.dir / "disabled.toml"
        disabled.write_text(registry.read_text().replace('[providers.openrouter]\npool = "openrouter"', '[providers.openrouter]\npool = "openrouter"\nenabled = false'))
        code, plan, _ = self.run_resolver(quota, "--slot", "implementer", registry=disabled)
        self.assertEqual((code, plan["assignments"][0]["model"]), (0, HAIKU))
        self.assertEqual(plan["assignments"][0]["skipped"][0]["reason"], "provider disabled in registry")

    # errors
    def test_bad_input_exits_one_with_a_clear_message(self):
        bad = self.dir / "bad.toml"
        bad.write_text(self.registry.read_text().replace('scout = "low"', 'scout = "nope"'))
        code, plan, err = self.run_resolver(healthy(), "--slot", "scout", registry=bad)
        self.assertEqual(code, 1)
        self.assertIn("unknown tier", err)
        for args, text in [(["--run-tier", "nope", "--slot", "driver"], "run-tier"), (["--exhausted", "nope", "--slot", "driver"], "pool"),
                           (["--slot", "driver|effort=huge"], "effort"), (["--slot", "driver|bogus=1"], "bogus")]:
            code, _, err = self.run_resolver(healthy(), *args)
            self.assertEqual(code, 1, args)
            self.assertIn(text, err)

    def test_missing_quota_file_means_unknown_not_failure(self):
        result = subprocess.run([sys.executable, str(RESOLVER), "--registry", str(self.registry), "--quota", str(self.dir / "nope.json"),
                                 "--now", NOW.isoformat(), "--slot", "driver"], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0)
        self.assertIn("unknown", result.stdout)
        self.assertIn(SONNET + "@high", result.stdout)

    def test_the_resolver_writes_nothing(self):
        def snapshot(root):
            return {str(p.relative_to(root)): (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(root.rglob("*")) if p.is_file()}
        qpath = self.dir / "quota.json"
        qpath.write_text(json.dumps(healthy()))
        before_tmp, before_src = snapshot(self.dir), snapshot(DIR)
        for extra in ([], ["--json"], ["--exhausted", "anthropic"]):
            subprocess.run([sys.executable, str(RESOLVER), "--registry", str(self.registry), "--quota", str(qpath), "--now", NOW.isoformat(),
                            "--slot", "driver", "--slot", "ordinary-reviewer", *extra], capture_output=True, text=True, timeout=60,
                           env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin"})
        self.assertEqual(snapshot(self.dir), before_tmp)
        self.assertEqual(snapshot(DIR), before_src)
        self.assertEqual([p for p in DIR.rglob("*") if p.suffix == ".pyc" or p.name == "__pycache__"], [])

    def test_a_fresh_entry_with_no_windows_is_unknown_not_ok(self):
        quota = healthy()
        quota["anthropic"] = pool()
        code, plan, _ = self.run_resolver(quota, "--slot", "driver")
        self.assertEqual(code, 0)
        status = {p["pool"]: p for p in plan["quota"]}["anthropic"]
        self.assertEqual(status["status"], "unknown")
        self.assertEqual(plan["assignments"][0]["model"], SONNET)
        self.assertTrue(any("anthropic" in w for w in plan["warnings"]))

    def test_text_output_shows_fallback_and_same_model_review(self):
        quota = healthy()
        quota["codex"] = pool(window("Week", 100))
        qpath = self.dir / "q2.json"
        qpath.write_text(json.dumps(quota))
        result = subprocess.run([sys.executable, str(RESOLVER), "--registry", str(self.registry), "--quota", str(qpath),
                                 "--now", NOW.isoformat(), "--slot", "a=ordinary-reviewer", "--slot", "b=challenge-reviewer"],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0)
        self.assertIn("same-model review", result.stdout)
        self.assertIn("skipped openai-codex/gpt-6.1-sol@xhigh", result.stdout)

    # the rendered registry per profile
    def test_profiles_render_and_the_work_profile_stays_anthropic_only(self):
        self.assertIn('profile = "personal"', self.registry.read_text())
        work = self.work_registry.read_text()
        self.assertIn('profile = "axon-work-computer"', work)
        self.assertNotIn("openai-codex", work)
        code, plan, _ = self.run_resolver({"anthropic": pool(window("Week", 5))}, "--slot", "driver", "--slot", "ordinary-reviewer", registry=self.work_registry)
        self.assertEqual(code, 0)
        self.assertEqual([a["model"] for a in plan["assignments"]], ["anthropic/claude-sonnet-5-5", "anthropic/claude-opus-5-5"])

    def test_the_example_registry_orders_tiers_as_the_owner_decided(self):
        text = self.registry.read_text()
        high = text[text.index("[tiers.high]"):text.index("[roles]")]
        self.assertLess(high.index("claude-opus-5-5@high"), high.index("gpt-6.1-sol@xhigh"))
        self.assertLess(high.index("gpt-6.1-sol@xhigh"), high.index("gpt-6-astra@high"))
        for line in ("gpt-6-luna@max", "gpt-6.1-sol@medium"):
            self.assertIn(line, text)


if __name__ == "__main__":
    unittest.main()
