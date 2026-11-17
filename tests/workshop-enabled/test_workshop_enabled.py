"""workshop.enabled: a personal Mac with no Workshop SSD drops every Workshop piece; with no key set nothing changes.

.chezmoiignore is rendered with chezmoi.os forced to darwin, so these run on Linux CI too. The template itself is rendered for the
three states (no key, true, false) and for bad values.
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CHEZMOI = shutil.which("chezmoi")

WORKSHOP_ONLY = {
    ".config/pnpm", "Library/Preferences/pnpm", ".config/agent-scratch", "81_agent_scratch_workshop.sh", "80_spotlight_off_workshop.sh",
    ".local/user_scripts/agent_tmp_move.py", ".local/share/agent-scratch", ".config/heavy-gate/volumes",
}


def render(path_or_text, data, is_file=True):
    text = (REPO / path_or_text).read_text() if is_file else path_or_text
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp) / "c.yaml"
        cfg.write_text("{}\n")
        return subprocess.run([CHEZMOI, "--source", str(REPO), "--config", str(cfg), "execute-template", "--override-data", json.dumps(data)],
                              input=text, text=True, capture_output=True, timeout=60)


def ignored(profile, os_name, workshop=None):
    data = {"profile": profile, "chezmoi": {"os": os_name, "arch": "arm64", "homeDir": "/h", "hostname": "h", "username": "u", "sourceDir": str(REPO)}}
    if workshop is not None:
        data["workshop"] = workshop
    r = render(".chezmoiignore", data)
    if r.returncode:
        raise AssertionError(r.stderr)
    return {line.strip() for line in r.stdout.splitlines() if line.strip() and not line.startswith("#")}


def config(workshop):
    data = {"profile": "personal", "chezmoi": {"os": "darwin", "homeDir": "/h"}}
    if workshop is not None:
        data["workshop"] = workshop
    return render('{{ includeTemplate "workshop_config" . }}', data, is_file=False)


@unittest.skipUnless(CHEZMOI, "chezmoi is required")
class WorkshopEnabledTests(unittest.TestCase):
    def test_no_key_and_true_both_mean_enabled(self):
        self.assertEqual(json.loads(config(None).stdout), {"enabled": True})
        self.assertEqual(json.loads(config({"enabled": True}).stdout), {"enabled": True})
        self.assertEqual(json.loads(config({"enabled": False}).stdout), {"enabled": False})

    def test_a_typo_or_bad_value_fails_the_render(self):
        for bad in ({"enable": False}, {"enabled": "maybe"}, "yes"):
            r = config(bad)
            self.assertNotEqual(r.returncode, 0, bad)

    def test_personal_macos_without_the_key_keeps_every_workshop_piece(self):
        # Nothing in the set is ignored on the machine that has the SSD (the MacBook), and nothing changed on it.
        got = ignored("personal", "darwin")
        self.assertFalse(WORKSHOP_ONLY & got, WORKSHOP_ONLY & got)
        self.assertEqual(got, ignored("personal", "darwin", {"enabled": True}))

    def test_personal_macos_with_the_key_false_drops_every_workshop_piece(self):
        got = ignored("personal", "darwin", {"enabled": False})
        self.assertLessEqual(WORKSHOP_ONLY, got)

    def test_the_key_changes_nothing_else_in_the_ignore_list(self):
        on, off = ignored("personal", "darwin"), ignored("personal", "darwin", {"enabled": False})
        self.assertEqual(on - off, set())
        self.assertEqual({p for p in off - on if not p.endswith("/**")}, WORKSHOP_ONLY)

    def test_other_profiles_and_linux_are_unchanged_by_the_key(self):
        for profile, os_name in (("axon-work-computer", "darwin"), ("personal", "linux"), ("axon-work-computer", "linux")):
            self.assertEqual(ignored(profile, os_name), ignored(profile, os_name, {"enabled": False}), (profile, os_name))

    def test_t3_worktrees_and_coordinator_checkout_follow_the_key(self):
        data = {"profile": "personal", "chezmoi": {"os": "darwin", "homeDir": "/h"}}
        arg = lambda w: dict(data, **({"workshop": w} if w is not None else {}))
        repo = '{{ includeTemplate "instance_repo" (dict "root" . "name" "coordinator") }}'
        self.assertEqual(render(repo, arg(None), False).stdout, "/Volumes/Workshop/macbook/git/coordinator")
        self.assertEqual(render(repo, arg({"enabled": False}), False).stdout, "/h/git/coordinator")
        self.assertIn("/Volumes/Workshop/macbook/t3-worktrees", self.t3_dir(arg(None)))
        self.assertIn("/h/t3-worktrees", self.t3_dir(arg({"enabled": False})))

    def t3_dir(self, data):
        r = render("dot_t3/private_userdata/modify_settings.json.tmpl", dict(data, container={}, t3Hub={}), True)
        self.assertEqual(r.returncode, 0, r.stderr)
        line = [l for l in r.stdout.splitlines() if l.startswith("WORKTREES_DIR=")]
        return line[0] if line else r.stdout


if __name__ == "__main__":
    unittest.main()
