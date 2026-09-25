#!/usr/bin/env python3
"""Preview/apply only the managed personal ssh-phone block, after testing the candidate.

This edits chezmoi SOURCE, not ~/.ssh/config directly. `daily-phone` is untouched.
"""
import argparse
import difflib
import ipaddress
import re
import subprocess
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent / "private_dot_ssh/modify_config.tmpl"
PATTERN = re.compile(r"^# ssh-phone \([^\n]+\).*?^    IdentitiesOnly yes\n", re.M | re.S)


def block(wg, lan, user):
    return f'''# ssh-phone (current Termux device; stage replacements before switching).
# Prefer the WireGuard path, then the reserved home Wi-Fi address.
Match host ssh-phone exec "/usr/bin/nc -z -G 1 -w 1 {wg} 8022 >/dev/null 2>&1"
    HostName {wg}

Match host ssh-phone exec "/usr/bin/nc -z -G 1 -w 1 {lan} 8022 >/dev/null 2>&1"
    HostName {lan}

Host ssh-phone
    HostName {wg}
    Port 8022
    User {user}
    IdentityFile ~/.ssh/homelab
    IdentitiesOnly yes
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("plan", "apply"))
    p.add_argument("--wg", required=True, help="new WireGuard IPv4 (without /32)")
    p.add_argument("--lan", required=True, help="new DHCP-reserved LAN IPv4")
    p.add_argument("--user", required=True, help="Termux user from bootstrap-phone.py inspect")
    p.add_argument("--attest-candidate", action="store_true", help="confirm new phone reached Herdr via direct SSH")
    p.add_argument("--confirm-alias", action="store_true", help="allow source edit and targeted Mac chezmoi apply")
    args = p.parse_args()
    try:
        wg = ipaddress.IPv4Address(args.wg)
        lan = ipaddress.IPv4Address(args.lan)
        if wg not in ipaddress.IPv4Network("10.21.1.0/24") or lan not in ipaddress.IPv4Network("10.19.1.0/24"):
            raise ValueError("addresses must be in the existing home/WireGuard subnets")
        if not re.fullmatch(r"u0_a\d{1,5}", args.user):
            raise ValueError("user must be Termux's actual u0_aNNN from this install")
        before = SOURCE.read_text()
        after, count = PATTERN.subn(lambda _: block(wg, lan, args.user), before)
        if count != 1:
            raise ValueError("expected exactly one managed ssh-phone source block")
        diff = ''.join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                             fromfile=str(SOURCE), tofile=str(SOURCE) + " (planned)"))
        if not diff:
            print("ssh-phone source already matches; no edit")
            return 0
        print(diff, end="")
        if args.action == "plan":
            print("PLAN only. Keep old ssh-phone alias until the candidate's direct SSH/Herdr path works.")
            return 0
        if not args.attest_candidate or not args.confirm_alias:
            raise ValueError("apply needs --attest-candidate AND --confirm-alias after reviewing the diff")
        # Refuse a concurrent source edit between read and write.
        if SOURCE.read_text() != before:
            raise ValueError("SSH source changed during plan; retry")
        SOURCE.write_text(after)
        dest = str(Path.home() / ".ssh/config")
        dry = subprocess.run(["chezmoi", "apply", "--dry-run", "--verbose", dest], capture_output=True)
        if dry.returncode:
            raise ValueError("source edited but targeted chezmoi dry-run failed; inspect source/live before retry")
        real = subprocess.run(["chezmoi", "apply", dest], capture_output=True)
        if real.returncode:
            raise ValueError("source edited but Mac apply failed (possibly non-TTY drift); resolve live/source explicitly")
        print("Updated managed SSH source and applied ~/.ssh/config; verify `ssh -G ssh-phone` before router retirement.")
    except (OSError, ValueError) as exc:
        print(f"[update-phone-alias] {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
