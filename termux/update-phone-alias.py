#!/usr/bin/env python3
"""Print the local chezmoi data for the ssh-phone alias after the candidate phone is tested.

The ssh-phone host values are not in this public repo: they are the local chezmoi data key
`sshHosts.sshPhone` (docs/profiles.md, "Local data keys"). This tool checks the new addresses
against the home subnets (HOMELAB_LAN_CIDR, HOMELAB_WG_CIDR, see homelab_env.py) and prints
the replacement entry. It edits nothing. `daily-phone` is untouched.

Put the printed entry under `sshHosts.sshPhone` in ~/.config/chezmoi/chezmoi.yaml, run
`chezmoi apply ~/.ssh/config`, then check `ssh -G ssh-phone`.
"""
import argparse
import ipaddress
import re
import sys

import homelab_env


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--wg", required=True, help="new WireGuard IPv4 (without /32)")
    p.add_argument("--lan", required=True, help="new DHCP-reserved LAN IPv4")
    p.add_argument("--user", required=True, help="Termux user from bootstrap-phone.py inspect")
    args = p.parse_args()
    try:
        wg = ipaddress.IPv4Address(args.wg)
        lan = ipaddress.IPv4Address(args.lan)
        if wg not in homelab_env.network("HOMELAB_WG_CIDR") or lan not in homelab_env.network("HOMELAB_LAN_CIDR"):
            raise ValueError("addresses must be in the existing home/WireGuard subnets")
        if not re.fullmatch(r"u0_a\d{1,5}", args.user):
            raise ValueError("user must be Termux's actual u0_aNNN from this install")
    except (ValueError, RuntimeError) as exc:
        print(f"[update-phone-alias] {exc}", file=sys.stderr)
        return 2
    print("sshHosts:\n  sshPhone:\n"
          f"    wgAddress: {wg}\n    lanAddress: {lan}\n    user: {args.user}")
    print("\nKeep the old entry until the candidate's direct SSH/Herdr path works.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
