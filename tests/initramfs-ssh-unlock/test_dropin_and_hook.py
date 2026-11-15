"""zz-ssh-unlock.conf (sourced the way mkinitcpio sources its drop-ins) and the sd-ssh-unlock hook's build() with mkinitcpio's helpers stubbed."""
import os
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import DROPIN, HOOK, scratch_dir, write_exe  # noqa: E402

# Stand-ins for what omarchy's drop-ins do to HOOKS and MODULES before ours is sourced.
OMARCHY_BASE = "HOOKS=(base systemd plymouth autodetect keyboard sd-vconsole block)\n"
OMARCHY_ADD = "HOOKS+=(omarchy-mac-encrypt sd-encrypt filesystems fsck)\nHOOKS+=(aurora-vendor-order)\nMODULES+=(hid_apple)\n"
MODINFO = '#!/bin/sh\ncase "$5" in dwc3_apple|r8152|r8153_ecm|cdc_ether|usbnet) echo /lib/modules/x/$5.ko ;; mii) echo "(builtin)" ;; *) exit 1 ;; esac\n'


class DropIn(unittest.TestCase):
    def setUp(self):
        t = scratch_dir()
        self.addCleanup(t.cleanup)
        self.d = Path(t.name)
        write_exe(self.d / "bin" / "modinfo", MODINFO)
        (self.d / "dropbear").write_text("#!/bin/sh\n")
        (self.d / "dropbear").chmod(0o755)

    def sourced(self, prelude, times=1, dropbear=True):
        env = {"PATH": f"{self.d / 'bin'}:/usr/bin:/bin", "SSH_UNLOCK_DROPBEAR": str(self.d / ("dropbear" if dropbear else "missing"))}
        body = prelude + (f"source {DROPIN}\n" * times) + 'echo "HOOKS=${HOOKS[*]}"; echo "MODULES=${MODULES[*]}"\n'
        r = subprocess.run(["bash", "-c", body], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = dict(line.split("=", 1) for line in r.stdout.splitlines())
        return out["HOOKS"].split(), out["MODULES"].split(), r.stderr

    def test_appends_the_hook_once_after_every_omarchy_hook_and_keeps_their_order(self):
        base = ["base", "systemd", "plymouth", "autodetect", "keyboard", "sd-vconsole", "block",
                "omarchy-mac-encrypt", "sd-encrypt", "filesystems", "fsck", "aurora-vendor-order"]
        # mkinitcpio sources the drop-ins, then the systemd hook sources them again: still one hook.
        hooks, modules, _ = self.sourced(OMARCHY_BASE + OMARCHY_ADD, times=2)
        self.assertEqual(hooks, base + ["sd-ssh-unlock"])
        # Only modules modinfo finds as a file are added (mii is built in here, so it is left out); the others stay.
        self.assertEqual(modules, ["hid_apple", "dwc3_apple", "r8152", "r8153_ecm", "cdc_ether", "usbnet"])

    def test_a_busybox_initramfs_or_a_missing_dropbear_changes_nothing(self):
        busybox = "HOOKS=(base udev plymouth keyboard autodetect modconf block encrypt filesystems fsck)\nMODULES=()\n"
        hooks, modules, _ = self.sourced(busybox)
        self.assertEqual((hooks, modules), (busybox.split("(")[1].split(")")[0].split(), []))
        hooks, modules, err = self.sourced(OMARCHY_BASE + "MODULES=()\n", dropbear=False)
        self.assertNotIn("sd-ssh-unlock", hooks)
        self.assertEqual(modules, [])
        self.assertIn("dropbear is not installed", err)


class Hook(unittest.TestCase):
    def setUp(self):
        t = scratch_dir()
        self.addCleanup(t.cleanup)
        self.d = Path(t.name)
        self.keys, self.etc, self.build = self.d / "keys", self.d / "etc", self.d / "buildroot"
        for p in (self.keys, self.etc, self.build / "etc"):
            p.mkdir(parents=True)
        for name in ("10-ssh-unlock.network", "ssh-unlock.service", "authorized_keys", "dropbear_ed25519_host_key"):
            (self.keys / name).write_text(name)
        for f in ("passwd", "shadow", "group"):
            (self.etc / f).write_text("root:x:0\nsystemd-network:x:977:977:net\n")
            (self.build / "etc" / f).write_text("root:x:0\n")
        (self.build / "var" / "log").mkdir(parents=True)   # add_dir is a stub; the hook then writes var/log/lastlog

    def run_build(self, **extra):
        lib = ('calls=%s\nadd_binary() { echo "add_binary $*" >> $calls; }\nadd_systemd_unit() { echo "add_systemd_unit $*" >> $calls; }\n'
               'add_file() { echo "add_file $*" >> $calls; }\nadd_symlink() { echo "add_symlink $*" >> $calls; }\nadd_dir() { echo "add_dir $*" >> $calls; }\n'
               'error() { printf "ERROR: $1\\n" "${@:2}" >&2; }\nBUILDROOT=%s\nsource %s\nbuild\n') % (self.d / "calls", self.build, HOOK)
        env = {"PATH": "/usr/bin:/bin", "SSH_UNLOCK_DIR": str(self.keys), "SSH_UNLOCK_ETC": str(self.etc), "SSH_UNLOCK_DROPBEAR": "/opt/dropbear", **extra}
        r = subprocess.run(["bash", "-c", lib], env=env, capture_output=True, text=True, timeout=30)
        calls = (self.d / "calls").read_text().splitlines() if (self.d / "calls").exists() else []
        return r, calls

    def test_build_adds_the_server_network_service_keys_and_the_network_user(self):
        r, calls = self.run_build()
        self.assertEqual(r.returncode, 0, r.stderr)
        k = str(self.keys)
        for want in ("add_binary /opt/dropbear /usr/bin/dropbear", "add_binary networkctl", "add_systemd_unit systemd-networkd.service",
                     f"add_file {k}/10-ssh-unlock.network /etc/systemd/network/10-ssh-unlock.network 644",
                     f"add_file {k}/ssh-unlock.service /usr/lib/systemd/system/ssh-unlock.service 644",
                     "add_symlink /usr/lib/systemd/system/initrd.target.wants/ssh-unlock.service ../ssh-unlock.service",
                     f"add_file {k}/dropbear_ed25519_host_key /etc/ssh-unlock/dropbear_ed25519_host_key 600",
                     "add_dir /root/.ssh 700", f"add_file {k}/authorized_keys /root/.ssh/authorized_keys 600"):
            self.assertIn(want, calls)
        for f in ("passwd", "shadow", "group"):
            self.assertEqual((self.build / "etc" / f).read_text(), "root:x:0\nsystemd-network:x:977:977:net\n")
        self.assertTrue((self.build / "var/log/lastlog").is_file())

    def test_build_does_not_add_the_network_user_twice(self):
        (self.build / "etc/passwd").write_text("root:x:0\nsystemd-network:x:977:977:net\n")
        self.run_build()
        self.assertEqual((self.build / "etc/passwd").read_text().count("systemd-network"), 1)

    def test_a_missing_staged_file_or_network_user_fails_the_build_and_names_it(self):
        (self.keys / "authorized_keys").unlink()
        r, _ = self.run_build()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("authorized_keys is missing", r.stderr)
        (self.keys / "authorized_keys").write_text("x")
        (self.etc / "shadow").write_text("root:*:::::::\n")
        r, _ = self.run_build()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no systemd-network entry in", r.stderr)


if __name__ == "__main__":
    unittest.main()
