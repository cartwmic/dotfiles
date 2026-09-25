#!/usr/bin/env python3
"""Prepare a private Mac-side QR import for the ssh-phone WireGuard client.

Never displays a private key or places the configuration on Android shared
storage. The phone owner scans the PNG from the Android WireGuard app.
"""
import argparse
import base64
import hashlib
import ipaddress
import json
import os
import re
import subprocess
import sys
from pathlib import Path

CACHE = Path.home() / ".cache/dotfiles-termux"


class Failed(Exception):
    pass


def run(args, data=None, check=True):
    try:
        result = subprocess.run(args, input=data, capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Failed(f"{args[0]} unavailable/timed out ({type(exc).__name__})") from exc
    if check and result.returncode:
        # Do not echo stdout, stderr, argv, or private material from op/wg.
        raise Failed(f"{args[0]} failed (exit {result.returncode})")
    return result


def key_ok(key):
    try:
        return len(base64.b64decode(key, validate=True)) == 32
    except (ValueError, base64.binascii.Error):
        return False


def read_item(vault, title):
    # Field labels match the existing `ssh-phone WireGuard` item.
    ref = f"op://{vault}/{title}/"
    secret = run(["op", "read", ref + "Private key"]).stdout.strip()
    public = run(["op", "read", ref + "Public key"]).stdout.strip()
    if not key_ok(secret) or not key_ok(public):
        raise Failed("1Password WireGuard fields have invalid key format")
    return secret, public


def derive(secret):
    public = run(["wg", "pubkey"], data=secret + b"\n").stdout.strip()
    if not key_ok(public):
        raise Failed("wg returned an invalid public key")
    return public


def prepare(args):
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", args.serial):
        raise Failed("invalid ADB serial")
    if not key_ok(args.server_key.encode()):
        raise Failed("server public key must be a 32-byte base64 WireGuard key")
    address = ipaddress.ip_interface(args.address)
    if address.version != 4 or address.network.prefixlen != 32:
        raise Failed("client address must be a single IPv4 /32")
    title = ("ssh-phone WireGuard" if args.mode == "restore"
             else f"ssh-phone Candidate WireGuard {args.serial}")
    for program, probe in (("op", ["op", "--version"]), ("wg", ["wg", "--version"]), ("qrencode", ["qrencode", "--version"])):
        try:
            run(probe, check=False)
        except Failed:
            raise Failed(f"missing {program}; on macOS: brew install wireguard-tools qrencode; authenticate op first")
    if args.mode == "restore":
        secret, public = read_item(args.vault, title)
    else:
        found = run(["op", "item", "get", title, "--vault", args.vault, "--format", "json"], check=False)
        if found.returncode == 0:
            secret, public = read_item(args.vault, title)
            print("candidate 1Password item already exists; reusing it (no rotation)")
        else:
            secret = run(["wg", "genkey"]).stdout.strip()
            if not key_ok(secret):
                raise Failed("wg returned an invalid private key")
            public = derive(secret)
            template = json.loads(run(["op", "item", "template", "get", "Secure Note"]).stdout)
            template["title"] = title
            template["fields"].extend([
                {"id": "wg_private", "type": "CONCEALED", "label": "Private key", "value": secret.decode()},
                {"id": "wg_public", "type": "STRING", "label": "Public key", "value": public.decode()},
            ])
            template["fields"][0]["value"] = "Candidate ssh-phone peer; do not retire the old peer until verified."
            run(["op", "item", "create", "--vault", args.vault, "-"], data=json.dumps(template).encode())
            # No printed JSON: op's response can contain field values.
            print(f"created 1Password item: {title}")
    if derive(secret) != public:
        raise Failed("stored 1Password public and private WireGuard keys disagree")

    # The only plaintext private-key artifact is a short-lived, mode-0600 QR
    # image on this Mac. Nothing is copied into Android Downloads/MediaStore.
    folder = CACHE / "wg-import"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(folder, 0o700)
    name = re.sub(r"[^A-Za-z0-9_-]", "_", args.serial)
    image = folder / f"{name}.png"
    if image.exists():
        raise Failed(f"existing QR at {image}; import then run cleanup before another prepare")
    contents = (f"[Interface]\nPrivateKey = {secret.decode()}\n"
                f"Address = {address}\nDNS = 10.19.1.1\n\n"
                f"[Peer]\nPublicKey = {args.server_key}\n"
                "AllowedIPs = 10.19.1.0/24, 10.21.1.0/24\n"
                "Endpoint = cartwmic.com:61583\nPersistentKeepalive = 25\n")
    try:
        run(["qrencode", "-o", str(image)], data=contents.encode())
        os.chmod(image, 0o600)
    except Exception:
        image.unlink(missing_ok=True)
        raise
    print(f"mode={args.mode} address={address} public_key={public.decode()} item={title}")
    print(f"Private QR: {image} (0600). Open it on the Mac; on Android, WireGuard > + > Scan from QR code.")
    print("Give the tunnel a name, enable it, select always-on VPN without lockdown, then run cleanup. Never screenshot or publish the QR.")


def promote(args):
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", args.serial) or not key_ok(args.expected_public_key.encode()):
        raise Failed("valid serial and candidate public key required")
    candidate = f"ssh-phone Candidate WireGuard {args.serial}"
    active = "ssh-phone WireGuard"
    def public(title):
        result = run(["op", "read", f"op://{args.vault}/{title}/Public key"], check=False)
        if result.returncode:
            return None
        value = result.stdout.strip().decode()
        if not key_ok(value.encode()):
            raise Failed(f"invalid public key in 1Password item: {title}")
        return value
    candidate_pub = public(candidate)
    active_pub = public(active)
    if candidate_pub is None and active_pub == args.expected_public_key:
        print("active WireGuard 1Password item already matches the new peer; no change")
        return
    if candidate_pub != args.expected_public_key:
        raise Failed("candidate 1Password item is missing or differs from the router's new public key")
    if active_pub == args.expected_public_key:
        raise Failed("active and candidate items duplicate the new key; resolve titles manually")
    if not args.confirm_promote:
        raise Failed("preview: rename old 1Password item, then promote candidate; rerun with --confirm-promote after router retirement")
    # A title change is only safe after OPNsense really retired the old peer.
    inspect = subprocess.run([sys.executable, str(Path(__file__).with_name("router-phone.py")), "inspect"],
                             capture_output=True, timeout=60)
    if inspect.returncode:
        raise Failed("cannot verify router retirement; no 1Password title changed")
    snapshot = json.loads(inspect.stdout)
    if snapshot["old_peer"]["public_key"] != args.expected_public_key or snapshot["candidate_peer"] is not None:
        raise Failed("router still has the old peer/candidate; do not promote the 1Password item yet")
    if active_pub is not None:
        retired = "ssh-phone WireGuard retired " + hashlib.sha256(active_pub.encode()).hexdigest()[:10]
        collision = run(["op", "item", "get", retired, "--vault", args.vault, "--format", "json"], check=False)
        if collision.returncode == 0:
            raise Failed("retired item title already exists; resolve the collision before promotion")
        run(["op", "item", "edit", active, "--vault", args.vault, "--title", retired])
        print(f"renamed old item to {retired} (kept for rollback)")
    else:
        print("canonical item missing; resuming a partially completed promotion")
    run(["op", "item", "edit", candidate, "--vault", args.vault, "--title", active])
    if public(active) != args.expected_public_key:
        raise Failed("1Password rename returned without the expected active public key; inspect item titles")
    print("promoted candidate to ssh-phone WireGuard; a future wipe now restores the current peer")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--mode", choices=("replace", "restore"), required=True)
    prep.add_argument("--serial", required=True)
    prep.add_argument("--address", required=True, help="candidate/new or existing /32, after router plan")
    prep.add_argument("--server-key", required=True, help="public key from OPNsense wg1, not its private key")
    prep.add_argument("--vault", default="developer")
    clean = sub.add_parser("cleanup")
    clean.add_argument("--serial", required=True)
    promotion = sub.add_parser("promote", help="after router retirement, make the new 1Password item restorable")
    promotion.add_argument("--serial", required=True)
    promotion.add_argument("--expected-public-key", required=True, help="from router-phone.py inspect after retirement")
    promotion.add_argument("--vault", default="developer")
    promotion.add_argument("--confirm-promote", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            prepare(args)
        elif args.action == "promote":
            promote(args)
        else:
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", args.serial):
                raise Failed("invalid ADB serial")
            image = CACHE / "wg-import" / (re.sub(r"[^A-Za-z0-9_-]", "_", args.serial) + ".png")
            image.unlink(missing_ok=True)
            print(f"removed temporary QR: {image} (1Password item is kept)")
    except (Failed, OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
        print(f"[wireguard-phone] {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
