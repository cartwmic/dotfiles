"""ssh_unlock_check_image.sh: passes an image that has every SSH-unlock piece and every original unlock piece, and names the first piece that is missing.

lsinitcpio is a stub that lists and extracts a fixture directory standing in for the image, so no real mkinitcpio output is needed.
"""
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import BLOB, CHECK_SCRIPT, scratch_dir, write_exe  # noqa: E402

LSINITCPIO = """#!/bin/sh
case "$1" in
  -l) (cd "$STUB_IMAGE" && find . -mindepth 1 | sed 's|^\\./||') ;;
  -x) cp -a "$STUB_IMAGE/." . ;;
esac
"""
PIECES = [
    "usr/lib/systemd/system/systemd-networkd.service", "usr/lib/systemd/system/ssh-unlock.service",
    "usr/lib/systemd/system/initrd.target.wants/ssh-unlock.service", "etc/systemd/network/10-ssh-unlock.network", "usr/bin/dropbear",
    "etc/ssh-unlock/dropbear_ed25519_host_key", "root/.ssh/authorized_keys",
    "usr/lib/modules/7.0/kernel/drivers/usb/dwc3/dwc3-apple.ko", "usr/lib/modules/7.0/kernel/drivers/net/usb/r8152.ko", "usr/lib/modules/7.0/kernel/drivers/net/usb/r8153_ecm.ko",
    "usr/lib/modules/7.0/kernel/drivers/net/usb/cdc_ether.ko", "usr/lib/modules/7.0/kernel/drivers/net/usb/usbnet.ko",
    "usr/lib/modules/7.0/kernel/drivers/net/mii.ko",
    # the pieces that were there before
    "usr/bin/systemd-tty-ask-password-agent", "usr/lib/systemd/system/systemd-ask-password-plymouth.service",
    "usr/lib/systemd/system/omarchy-mac-encrypt.service", "usr/bin/systemd-cryptsetup", "usr/bin/plymouth",
]
NETWORK = "[Match]\nType=ether\nDriver=r8152 r8153_ecm\n\n[Network]\nDHCP=ipv4\nKeepConfiguration=no\n"
AUTH = f'command="/usr/bin/systemd-tty-ask-password-agent --watch" ssh-ed25519 {BLOB}\n'


class CheckImage(unittest.TestCase):
    def setUp(self):
        t = scratch_dir()
        self.addCleanup(t.cleanup)
        d = Path(t.name)
        self.image, self.keys = d / "image", d / "keys"
        for rel in PIECES:
            f = self.image / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("")
        (self.image / "etc/systemd/network/10-ssh-unlock.network").write_text(NETWORK)
        (self.image / "etc/ssh-unlock/dropbear_ed25519_host_key").write_text("HOSTKEY")
        (self.image / "root/.ssh/authorized_keys").write_text(AUTH)
        for f in ("passwd", "shadow", "group"):
            (self.image / "etc" / f).write_text("root:x:0\nsystemd-network:x:977\n")
        self.keys.mkdir()
        (self.keys / "dropbear_ed25519_host_key").write_text("HOSTKEY")
        (self.keys / "authorized_keys").write_text(AUTH)
        write_exe(d / "bin" / "lsinitcpio", LSINITCPIO)
        write_exe(d / "bin" / "systemd-analyze", '#!/bin/sh\necho "$*" > "$STUB_DIR/verify"\n[ -z "${STUB_VERIFY_FAILS:-}" ]\n')
        write_exe(d / "bin" / "sudo", '#!/bin/sh\n[ "$1" = -n ] && shift\nexec "$@"\n')
        self.env = {"PATH": f"{d / 'bin'}:/usr/bin:/bin", "STUB_IMAGE": str(self.image), "STUB_DIR": str(d), "SSH_UNLOCK_DIR": str(self.keys), "TMPDIR": str(d), "HOME": str(d)}
        self.d = d

    def check(self):
        return subprocess.run(["/bin/sh", str(CHECK_SCRIPT), "the.img"], env=self.env, capture_output=True, text=True, timeout=60)

    def test_an_image_with_every_piece_passes(self):
        r = self.check()
        self.assertEqual((r.returncode, "ok:" in r.stdout), (0, True), r.stdout + r.stderr)

    def test_a_missing_file_fails_and_is_named(self):
        for rel in PIECES:
            with self.subTest(missing=rel):
                shutil.copytree(self.image, self.d / "backup")
                (self.image / rel).unlink()
                try:
                    r = self.check()
                    self.assertEqual(r.returncode, 1, r.stdout)
                    self.assertIn(rel.split("/")[-1].replace(".ko", ""), r.stdout)
                finally:
                    shutil.rmtree(self.image)
                    shutil.move(self.d / "backup", self.image)

    def test_wrong_content_fails_and_is_named(self):
        def edit(rel, text, expect):
            with self.subTest(expect=expect):
                f = self.image / rel
                old = f.read_text()
                f.write_text(text)
                try:
                    r = self.check()
                    self.assertEqual(r.returncode, 1, r.stdout)
                    self.assertIn(expect, r.stdout)
                finally:
                    f.write_text(old)
        edit("etc/systemd/network/10-ssh-unlock.network", NETWORK.replace("KeepConfiguration=no\n", ""), "KeepConfiguration=no")
        edit("etc/systemd/network/10-ssh-unlock.network", NETWORK.replace("Driver=r8152 r8153_ecm\n", ""), "Driver=")
        edit("root/.ssh/authorized_keys", f"ssh-ed25519 {BLOB}\n", "forced command")
        edit("etc/ssh-unlock/dropbear_ed25519_host_key", "OTHERKEY", "stored host key")
        edit("etc/passwd", "root:x:0\n", "etc/passwd")
        edit("etc/shadow", "root:x:0\n", "etc/shadow")
        edit("etc/group", "root:x:0\n", "etc/group")

    def test_a_failing_unit_verify_fails_the_check(self):
        self.env["STUB_VERIFY_FAILS"] = "1"
        r = self.check()
        self.assertEqual(r.returncode, 1)
        self.assertIn("systemd-analyze verify", r.stdout)
        self.assertIn("ssh-unlock.service", (self.d / "verify").read_text())     # it verifies the new unit, against the extracted image

    def test_an_image_that_cannot_be_read_fails(self):
        shutil.rmtree(self.image)
        r = self.check()
        self.assertNotEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
