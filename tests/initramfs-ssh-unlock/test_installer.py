"""run_onchange_after_88_initramfs_ssh_unlock_linux.sh.tmpl: installs the SSH unlock, proves the image before it touches /boot, and rolls back.

The script is rendered with chezmoi (the real source, a throwaway config) and run as it ships. SSH_UNLOCK_ROOT stands in for /, and every command that
would change the machine (sudo, pacman, mkinitcpio, limine-mkinitcpio, limine-entry-tool, dropbearkey) is a stub on PATH that logs its call.
"""
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import BLOB, INSTALLER_TMPL, ROOT, STAGE_SRC, chezmoi, scratch_dir, write_exe  # noqa: E402

LOG = 'echo "$(basename "$0") $*" >> "$STUB_DIR/calls"\n'
STUBS = {
    "sudo": LOG + '[ "$1" = -n ] && shift\nexec "$@"\n',
    "pacman": LOG,
    "dropbearkey": LOG + 'if [ "$1" = -y ]; then echo "Fingerprint: SHA256:abc"; else shift 3; [ -e "$1" ] || echo HOSTKEY > "$1"; fi\n',
    # Builds "an image": a file whose content says whether it has the SSH unlock in it.
    "limine-mkinitcpio": LOG + '[ -n "${STUB_LIMINE_NOOP:-}" ] || echo "ssh rebuilt" > "$SSH_UNLOCK_ROOT/boot/efi/EFI/Linux/omarchy_linux-aurora.efi"\n',
    "limine-entry-tool": LOG + 'conf="$SSH_UNLOCK_ROOT/boot/efi/limine.conf"\nshift 3\n'
                         'echo "comment: $2" >> "$conf"\n[ -z "${STUB_SHIFT_DEFAULT:-}" ] || sed -i "s/^default_entry:.*/default_entry: 3/" "$conf"\n',
}
MKINITCPIO = LOG + 'while [ "$1" != --generate ]; do shift; done\necho "ssh scratch" > "$2"\n'
# The image check: passes for an image that says "ssh" in it, unless this is the image the test wants to fail.
CHECK = LOG + 'case "$1" in *test.img) [ "${STUB_CHECK_FAILS:-}" != scratch ] ;; *) [ "${STUB_CHECK_FAILS:-}" != uki ] && grep -q ssh "$1" ;; esac\n'


class Installer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = scratch_dir()
        cls.script = Path(cls.tmp.name) / "install88.sh"
        r = chezmoi(Path(cls.tmp.name), "personal", "execute-template", stdin=INSTALLER_TMPL.read_text())
        assert r.returncode == 0, r.stderr
        cls.script.write_text(r.stdout)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        t = scratch_dir()
        self.addCleanup(t.cleanup)
        d = Path(t.name)
        self.d = d
        self.root = d / "root"
        self.home = d / "home"
        self.stub = d / "stub"
        for name, body in STUBS.items():
            write_exe(self.stub / "bin" / name, "#!/bin/sh\n" + body)
        write_exe(self.root / "usr" / "bin" / "mkinitcpio", "#!/bin/sh\n" + MKINITCPIO)
        write_exe(self.root / "usr" / "local" / "bin" / "mkinitcpio", "#!/bin/sh\n")
        write_exe(self.stub / "check.sh", "#!/bin/sh\n" + CHECK)
        (self.root / "etc/mkinitcpio.conf.d").mkdir(parents=True)
        (self.root / "etc/mkinitcpio.conf.d/91-omarchy-mac-encrypt.conf").write_text("")
        self.uki = self.root / "boot/efi/EFI/Linux/omarchy_linux-aurora.efi"
        self.uki.parent.mkdir(parents=True)
        self.uki.write_text("old image")
        self.limine = self.root / "boot/efi/limine.conf"
        self.limine.write_text("default_entry: 2\n")
        shutil.copytree(STAGE_SRC, self.home / ".local/share/initramfs-ssh-unlock")
        (self.home / ".ssh").mkdir()
        (self.home / ".ssh/homelab.pub").write_text(f"ssh-ed25519 {BLOB}\n")
        self.env = {"PATH": f"{self.stub / 'bin'}:{os.environ['PATH']}", "HOME": str(self.home), "STUB_DIR": str(self.stub),
                    "SSH_UNLOCK_ROOT": str(self.root), "SSH_UNLOCK_CHECK": str(self.stub / "check.sh"), "TMPDIR": str(d)}

    def run_script(self, **extra):
        return subprocess.run(["/bin/sh", str(self.script)], env={**self.env, **extra}, capture_output=True, text=True, timeout=60)

    def calls(self):
        f = self.stub / "calls"
        return f.read_text().splitlines() if f.exists() else []

    def named(self, prefix):
        return [c for c in self.calls() if c.startswith(prefix)]

    @property
    def dropin(self):
        return self.root / "etc/mkinitcpio.conf.d/zz-ssh-unlock.conf"

    def test_first_run_installs_proves_the_image_then_rebuilds_the_boot_image(self):
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        order = [c.split()[0] for c in self.calls() if not c.startswith("sudo")]
        # pacman, host key, scratch build, check of the scratch image, known-good entry, boot rebuild, check of the boot image.
        self.assertEqual(order, ["pacman", "dropbearkey", "mkinitcpio", "check.sh", "limine-entry-tool", "limine-mkinitcpio", "check.sh", "dropbearkey"])
        self.assertEqual(self.dropin.read_text(), (STAGE_SRC / "mkinitcpio.conf.d/zz-ssh-unlock.conf").read_text())
        self.assertEqual((self.root / "etc/initcpio/install/sd-ssh-unlock").read_text(), (STAGE_SRC / "install/sd-ssh-unlock").read_text())
        keydir = self.root / "etc/initcpio/ssh-unlock"
        for name in ("10-ssh-unlock.network", "ssh-unlock.service", "dropbear_ed25519_host_key"):
            self.assertTrue((keydir / name).is_file(), name)
        self.assertEqual((keydir / "authorized_keys").read_text(),
                         f'command="/usr/bin/systemd-tty-ask-password-agent --watch" ssh-ed25519 {BLOB}\n')
        self.assertEqual((self.root / "var/tmp/ssh-unlock-known-good.efi").read_text(), "old image")
        self.assertEqual(self.uki.read_text(), "ssh rebuilt\n")
        self.assertFalse((self.root / "var/tmp/ssh-unlock-test.img").exists())
        self.assertIn("SHA256:abc", r.stdout)

    def test_a_second_run_does_nothing_and_a_changed_file_reuses_the_host_key_and_the_known_good_entry(self):
        self.assertEqual(self.run_script().returncode, 0)
        before = len(self.calls())
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("nothing to do", r.stdout)
        self.assertEqual([c for c in self.calls()[before:] if not c.startswith(("sudo", "check.sh"))], [])
        net = self.home / ".local/share/initramfs-ssh-unlock/10-ssh-unlock.network"
        net.write_text(net.read_text() + "# changed\n")
        self.assertEqual(self.run_script().returncode, 0)
        self.assertEqual(len(self.named("dropbearkey -t")), 1)          # the host key is made once and kept
        self.assertEqual(len(self.named("limine-entry-tool")), 1)       # the known-good entry is added once
        self.assertEqual(len(self.named("limine-mkinitcpio")), 2)       # the boot image is rebuilt for the change

    def test_a_scratch_image_that_fails_the_check_leaves_the_boot_image_and_the_drop_in_alone(self):
        r = self.run_script(STUB_CHECK_FAILS="scratch")
        self.assertEqual(r.returncode, 1)
        self.assertFalse(self.dropin.exists())                        # rolled back
        self.assertEqual(self.named("limine-"), [])                   # the boot image was never rebuilt, no entry added
        self.assertEqual(self.uki.read_text(), "old image")
        self.assertNotIn("known-good", self.limine.read_text())

    def test_a_boot_image_that_was_not_rebuilt_fails_and_takes_the_drop_in_out(self):
        r = self.run_script(STUB_LIMINE_NOOP="1")                     # limine-mkinitcpio exits 0 without building
        self.assertEqual(r.returncode, 1)
        self.assertIn("was not rebuilt", r.stdout)
        self.assertFalse(self.dropin.exists())

    def test_a_rebuilt_boot_image_that_fails_the_check_takes_the_drop_in_out(self):
        r = self.run_script(STUB_CHECK_FAILS="uki")
        self.assertEqual(r.returncode, 1)
        self.assertFalse(self.dropin.exists())

    def test_the_known_good_entry_must_not_move_the_default_boot_entry(self):
        r = self.run_script(STUB_SHIFT_DEFAULT="1")
        self.assertEqual(r.returncode, 1)
        self.assertIn("default_entry", r.stdout)
        self.assertFalse(self.dropin.exists())
        self.assertEqual(self.named("limine-mkinitcpio"), [])

    def test_a_host_that_is_not_the_apple_silicon_omarchy_box_is_left_alone(self):
        (self.root / "etc/mkinitcpio.conf.d/91-omarchy-mac-encrypt.conf").unlink()
        r = self.run_script()
        self.assertEqual((r.returncode, self.calls()), (0, []))
        self.assertFalse(self.dropin.exists())

    def test_a_homelab_key_that_is_not_the_one_in_authorized_keys_source_stops_before_any_change(self):
        (self.home / ".ssh/homelab.pub").write_text("ssh-ed25519 AAAAsomeotherkey\n")
        r = self.run_script()
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.calls(), [])
        r = self.run_script(HOME=str(self.d / "nohome"))
        self.assertEqual(r.returncode, 1)

    def test_the_script_is_managed_on_personal_and_absent_on_work(self):
        def managed(profile):
            r = chezmoi(Path(self.tmp.name), profile, "managed")
            self.assertEqual(r.returncode, 0, r.stderr)
            return set(r.stdout.split())
        personal, work = managed("personal"), managed("axon-work-computer")
        for name in ("88_initramfs_ssh_unlock_linux.sh", ".local/user_scripts/ssh_unlock_check_image.sh",
                     ".local/share/initramfs-ssh-unlock/install/sd-ssh-unlock",
                     ".local/share/initramfs-ssh-unlock/mkinitcpio.conf.d/zz-ssh-unlock.conf"):
            self.assertIn(name, personal)
            self.assertNotIn(name, work)
        self.assertEqual({p for p in work if "ssh-unlock" in p or "ssh_unlock" in p}, set())


if __name__ == "__main__":
    unittest.main()
