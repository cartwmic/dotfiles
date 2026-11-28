"""Shared helpers for the SSH-unlock tests: paths into the source tree and stub commands. Nothing here touches the real system."""
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "support"))
import source_tree  # noqa: E402  (the repo's source with its archive URLs pointed at local stand-ins: chezmoi downloads nothing)
STAGE_SRC = ROOT / "dot_local" / "share" / "initramfs-ssh-unlock"
HOOK = STAGE_SRC / "install" / "sd-ssh-unlock"
DROPIN = STAGE_SRC / "mkinitcpio.conf.d" / "zz-ssh-unlock.conf"
CHECK_SCRIPT = ROOT / "dot_local" / "user_scripts" / "executable_ssh_unlock_check_image.sh"
INSTALLER_TMPL = ROOT / "run_onchange_after_88_initramfs_ssh_unlock_linux.sh.tmpl"
# The homelab key is written down in one place; the tests read it from there too.
BLOB = re.search(r"BLOB='([^']+)'", (ROOT / "private_dot_ssh" / "modify_private_authorized_keys.tmpl").read_text()).group(1)


def write_exe(path: Path, body: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def chezmoi_config(tmp: Path, profile: str) -> Path:
    cfg = tmp / f"chezmoi-{profile}.yaml"
    cfg.write_text("data:\n  profile: %s\n" % profile)
    return cfg


def chezmoi(tmp: Path, profile: str, *args: str, stdin: str = None):
    home = tmp / f"home-{profile}"
    home.mkdir(exist_ok=True)
    return subprocess.run(["chezmoi", "--source", str(source_tree.source()), "--config", str(chezmoi_config(tmp, profile)), "--config-format", "yaml",
                           "--destination", str(home), *args], input=stdin, capture_output=True, text=True,
                          env=source_tree.chezmoi_env(home), timeout=120)


def scratch_dir():
    return tempfile.TemporaryDirectory()
