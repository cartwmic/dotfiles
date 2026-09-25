#!/usr/bin/env python3
"""Preview, then explicitly apply a staged ssh-phone DHCP/WireGuard cutover.

OPNsense is only accessed over pinned-host-key root SSH. The password comes
from 1Password at authentication time; only public peer details enter plans.
"""
import argparse
import base64
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

PHP = Path(__file__).with_name("opnsense-phone.php")
PLANS = Path.home() / ".cache/dotfiles-termux/router-plans"
PASSWORD_REF = "op://developer/opnsense/password"


class Failed(Exception):
    pass


def router(command):
    with tempfile.TemporaryDirectory(prefix="phone-router-") as temp:
        askpass = Path(temp) / "askpass"
        askpass.write_text("#!/bin/sh\nset -eu\n"
                           'export OP_SERVICE_ACCOUNT_TOKEN="$(cat "$HOME/.config/agent-harness/op-service-token")"\n'
                           f"exec op read {shlex.quote(PASSWORD_REF)}\n")
        askpass.chmod(0o700)
        env = os.environ.copy()
        env.update(SSH_ASKPASS=str(askpass), SSH_ASKPASS_REQUIRE="force", DISPLAY=":0")
        args = ["ssh", "-o", "StrictHostKeyChecking=yes", "-o", "PreferredAuthentications=password",
                "-o", "PubkeyAuthentication=no", "-o", "NumberOfPasswordPrompts=1",
                "-o", "ConnectTimeout=8", "root@10.19.1.1", "sh -s"]
        try:
            result = subprocess.run(args, input=command.encode(), capture_output=True, env=env, timeout=45)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Failed(f"router SSH unavailable/timed out ({type(exc).__name__})") from exc
    if result.returncode:
        # Never dump router stdout/stderr: a future error might contain config.xml.
        raise Failed(f"router command failed (exit {result.returncode}); no success asserted")
    return result.stdout.decode()


def call_php(spec):
    encoded = base64.b64encode(json.dumps(spec, separators=(",", ":")).encode()).decode()
    script = PHP.read_text()
    if "\nPHONE_PHP\n" in script:
        raise Failed("invalid PHP delimiter in source")
    payload = f"PHONE_SPEC_B64={shlex.quote(encoded)} php <<'PHONE_PHP'\n{script}\nPHONE_PHP\n"
    try:
        value = json.loads(router(payload))
    except (ValueError, json.JSONDecodeError) as exc:
        raise Failed("router did not return a structured plan") from exc
    if not isinstance(value, dict) or "fingerprint" not in value:
        raise Failed("router plan is incomplete")
    return value


def print_summary(summary):
    print(json.dumps(summary, indent=2, sort_keys=True))


def inspect(_args):
    print_summary(call_php({"action": "inspect", "mode": "inspect"}))


def plan(args):
    spec = {"mode": args.mode, "mac": args.mac.lower(), "lan": args.lan,
            "address": args.address, "public_key": args.public_key}
    summary = call_php({"action": "plan", **spec})
    PLANS.mkdir(parents=True, exist_ok=True, mode=0o700)
    PLANS.chmod(0o700)
    # A stable name makes rerunning an unchanged plan harmless. No private key.
    import hashlib
    identifier = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:12]
    path = PLANS / f"{args.mode}-{identifier}.json"
    record = {"spec": spec, "expected_fingerprint": summary["fingerprint"], "summary": summary}
    with tempfile.NamedTemporaryFile(mode="w", dir=PLANS, prefix=".plan-", delete=False) as tmp:
        os.chmod(tmp.name, 0o600)
        json.dump(record, tmp, indent=2)
        tmp.write("\n")
        temp_path = Path(tmp.name)
    temp_path.replace(path)
    print_summary(summary)
    print(f"PLAN: {path}. Review old and proposed identifiers. Apply is a separate command.")
    print("Router backup stays on OPNsense; template reload MUST precede WireGuard configure.")


def verify_runtime(spec, old_public):
    if spec["mode"] == "restore":
        return
    # The permitted output includes only peer public keys and tunnel IPs.
    output = router("wg show wg1 allowed-ips\n")
    expected = spec["public_key"] + "\t" + spec["address"]
    if not any(line.strip().split() == expected.split() for line in output.splitlines()):
        raise Failed("router config saved but new peer is absent from wg1 runtime; inspect backup/reload before proceeding")
    if spec["mode"] == "retire" and any(line.split() and line.split()[0] == old_public for line in output.splitlines()):
        raise Failed("old peer remains on wg1 after retirement; inspect router runtime")


def alias_is_candidate(spec, user):
    source = Path(__file__).resolve().parent.parent / "private_dot_ssh/modify_config.tmpl"
    content = source.read_text()
    match = re.search(r"# ssh-phone \([^\n]*\).*?Host ssh-phone\n(.*?\n)    IdentityFile ~/.ssh/homelab", content, re.S)
    if not match or spec["address"].removesuffix("/32") not in match.group(0) or spec["lan"] not in match.group(0) or f"User {user}" not in match.group(0):
        raise Failed("Mac managed SSH source is not cut over to the candidate; run update-phone-alias.py first")
    result = subprocess.run(["ssh", "-G", "ssh-phone"], capture_output=True, timeout=10)
    if result.returncode:
        raise Failed("Mac generated ssh-phone alias is invalid; apply the managed source first")
    fields = dict(line.split(" ", 1) for line in result.stdout.decode().splitlines() if " " in line)
    if fields.get("hostname") not in (spec["address"].removesuffix("/32"), spec["lan"]) or fields.get("user") != user:
        raise Failed("Mac live ssh-phone alias still targets old hardware; do not retire its router peer")


def apply(args):
    path = Path(args.plan).expanduser().resolve()
    if not path.is_file() or path.parent != PLANS.resolve():
        raise Failed("apply requires a plan generated under the private router-plans directory")
    record = json.loads(path.read_text())
    spec = record["spec"]
    mode = spec["mode"]
    if args.confirm != {"stage": "STAGE-SSH-PHONE", "restore": "RESTORE-SSH-PHONE",
                        "retire": "RETIRE-OLD-SSH-PHONE"}[mode]:
        raise Failed(f"type --confirm {mode.upper()}-SSH-PHONE (see docs; retirement has a distinct phrase)")
    if mode == "retire":
        if not args.attest_candidate or not (args.attest_off_lan or args.defer_off_lan):
            raise Failed("retire requires --attest-candidate plus --attest-off-lan (or explicit --defer-off-lan)")
        if not args.new_user:
            raise Failed("retire requires --new-user from bootstrap-phone.py inspect")
        alias_is_candidate(spec, args.new_user)
    expected = record["expected_fingerprint"]
    if expected != record["summary"]["fingerprint"]:
        raise Failed("plan file was edited; regenerate it")
    summary = call_php({"action": "apply", **spec, "expected_fingerprint": expected})
    backup = summary.get("backup", "none (no config change)")
    try:
        if mode != "restore":
            # Also heal a previous save whose runtime configure step failed.
            router("set -eu\nconfigctl template reload OPNsense/Wireguard\nconfigctl wireguard configure\n")
        # A previous apply may have saved config but failed during DHCP reload.
        # Re-running an explicitly confirmed plan must repair that runtime state.
        router("set -eu\nconfigctl dhcpd restart\n")
        verify_runtime(spec, record["summary"]["old_peer"]["public_key"])
        final = call_php({"action": "inspect", "mode": "inspect"})
        peer = final["old_peer"] if mode in ("restore", "retire") else final["candidate_peer"]
        mapping = final["old_reservation"] if mode in ("restore", "retire") else final["candidate_reservation"]
        if peer["public_key"] != spec["public_key"] or peer["address"] != spec["address"] or mapping["mac"] != spec["mac"] or mapping["lan"] != spec["lan"]:
            raise Failed("router persisted values do not match the plan")
    except Failed as exc:
        raise Failed(f"config write may have succeeded; backup on router: {backup}; service/runtime incomplete: {exc}") from exc
    print(f"APPLIED {mode}: router backup={backup}; relevant services configured and wg1 checked")
    if mode == "stage":
        print("Old peer/alias still work. Validate new phone over LAN AND external network before planning retirement.")
    if mode == "retire" and args.defer_off_lan:
        print("WARNING: off-home-network check deferred; run it before treating replacement as fully verified.")


def reconcile(args):
    if args.confirm != "RELOAD-ROUTER-SERVICES":
        raise Failed("inspect current peer metadata first; reconcile requires --confirm RELOAD-ROUTER-SERVICES")
    snapshot = call_php({"action": "inspect", "mode": "inspect"})
    router("set -eu\nconfigctl template reload OPNsense/Wireguard\nconfigctl wireguard configure\nconfigctl dhcpd restart\n")
    output = router("wg show wg1 allowed-ips\n")
    peers = [snapshot["old_peer"]]
    if snapshot["candidate_peer"]:
        peers.append(snapshot["candidate_peer"])
    for peer in peers:
        if not any(line.split() == [peer["public_key"], peer["address"]] for line in output.splitlines()):
            raise Failed("services reloaded, but an expected peer is absent from wg1 runtime")
    print("Router services reconciled; old/current and any staged candidate appear on wg1. No config.xml write.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("inspect")
    preview = subs.add_parser("plan")
    preview.add_argument("--mode", choices=("stage", "restore", "retire"), required=True)
    preview.add_argument("--mac", required=True, help="new device Wi-Fi MAC for THIS network")
    preview.add_argument("--lan", required=True, help="candidate reserved LAN IPv4 (current for restore)")
    preview.add_argument("--address", required=True, help="client WireGuard address with /32")
    preview.add_argument("--public-key", required=True, help="client public key from wireguard-phone.py")
    update = subs.add_parser("apply")
    update.add_argument("--plan", required=True)
    update.add_argument("--confirm", required=True, help="STAGE-SSH-PHONE, RESTORE-SSH-PHONE or RETIRE-OLD-SSH-PHONE")
    update.add_argument("--attest-candidate", action="store_true")
    update.add_argument("--attest-off-lan", action="store_true")
    update.add_argument("--defer-off-lan", action="store_true")
    update.add_argument("--new-user", help="new Termux username; required at retirement")
    recovery = subs.add_parser("reconcile", help="re-run service reload after an incomplete router apply")
    recovery.add_argument("--confirm", required=True)
    args = parser.parse_args()
    try:
        {"inspect": inspect, "plan": plan, "apply": apply, "reconcile": reconcile}[args.command](args)
    except (Failed, OSError, KeyError, TypeError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print(f"[router-phone] {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
