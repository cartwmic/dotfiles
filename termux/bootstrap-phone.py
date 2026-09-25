#!/usr/bin/env python3
"""Mac-side, serial-pinned Termux bootstrap. Phone files belong to phone-side chezmoi.

This tool never uninstalls apps, pushes dotfiles through ADB, or reads Android
private-key UI fields. An absent manual approval is an incomplete deployment.
"""
import argparse
from contextlib import contextmanager
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SIGNER = "ec1ab3f5e4d261a4c6c5e2979b4af4f8d0071a951761575a2929ce59dcf1c0c1"
FINGERPRINTS = {
    "homelab": ("SHA256:s1NF+DDqZKlvvy/wDQXBACMs3jb/cjkvy/UpOYbypOQ", "op://developer/cartwmic-homelab ssh key/private key?ssh-format=openssh"),
    "whonix-homelab": ("SHA256:oNPHkrMebH0d0dq6B+gexDeimXdUbDHh38dHf3EGpEE", "op://developer/whonix-homelab/private key?ssh-format=openssh"),
}
PACKAGES = {
    "termux-app.apk": "com.termux",
    "termux-api.apk": "com.termux.api",
    "termux-boot.apk": "com.termux.boot",
}
EXPECTED_VERSIONS = {"com.termux": 1008, "com.termux.api": 1003, "com.termux.boot": 1000}
PLAY_PACKAGES = ("com.wireguard.android", "io.heckel.ntfy", "app.whisperian.client")
REPO = Path(__file__).resolve().parent.parent


class BootstrapError(Exception):
    pass


def run(argv, *, data=None, check=True, timeout=60, env=None):
    try:
        result = subprocess.run(argv, input=data, capture_output=True, timeout=timeout, check=False, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BootstrapError(f"{argv[0]} unavailable or timed out ({type(exc).__name__})") from exc
    if check and result.returncode:
        # In particular, never echo the output of `op`, `ssh`, or `adb` here:
        # an external tool could include key material in a diagnostic.
        raise BootstrapError(f"{Path(argv[0]).name} failed (exit {result.returncode})")
    return result


def adb(serial, *args, check=True, timeout=60):
    return run(["adb", "-s", serial, *args], check=check, timeout=timeout)


def text(result):
    return result.stdout.decode(errors="replace").strip()


def device(serial):
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", serial):
        raise BootstrapError("invalid ADB serial")
    if re.fullmatch(r"emulator-\d+", serial):
        raise BootstrapError("refusing an emulator serial; choose the physical phone from `adb devices`")
    matches = [line.split() for line in text(run(["adb", "devices", "-l"])).splitlines()[1:]
               if line.split() and line.split()[0] == serial]
    if len(matches) != 1 or len(matches[0]) < 2 or matches[0][1] != "device":
        raise BootstrapError(f"ADB serial {serial} is not uniquely authorized and online")
    if not any(part.startswith("usb:") for part in matches[0][2:]):
        raise BootstrapError(f"ADB serial {serial} is not a USB transport; refusing wireless key provisioning")
    model = text(adb(serial, "shell", "getprop", "ro.product.model"))
    api = text(adb(serial, "shell", "getprop", "ro.build.version.sdk"))
    if not api.isdecimal() or int(api) < 24:
        raise BootstrapError(f"unsupported Android API level: {api}")
    return model, api


def uid(serial):
    output = text(adb(serial, "shell", "cmd", "package", "list", "packages", "-U", "com.termux"))
    match = re.search(r"^package:com\.termux uid:(\d+)$", output, re.M)
    if not match:
        raise BootstrapError("Termux is not installed; install the signed APKs first")
    number = int(match.group(1))
    if not 10000 <= number < 19999:
        raise BootstrapError("Termux is not in primary Android user 0; manual setup needed")
    return f"u0_a{number - 10000}"


def apk_tools():
    bt = Path(os.environ.get("ANDROID_BUILD_TOOLS", str(Path.home() / "Android/build-tools/35.0.0")))
    for name in ("aapt", "apksigner"):
        if not (bt / name).is_file():
            raise BootstrapError(f"missing {bt / name}")
    return bt


def apk_info(path, package):
    bt = apk_tools()
    env = os.environ.copy()
    env.setdefault("JAVA_HOME", "/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home")
    cert = text(run([str(bt / "apksigner"), "verify", "--print-certs", str(path)], env=env))
    match = re.search(r"Signer #1 certificate SHA-256 digest: ([0-9a-f]+)", cert)
    if not match or match.group(1) != SIGNER:
        raise BootstrapError(f"signing certificate mismatch: {package}")
    badging = text(run([str(bt / "aapt"), "dump", "badging", str(path)]))
    match = re.search(r"^package: name='([^']+)' versionCode='(\d+)'", badging, re.M)
    if not match or match.group(1) != package:
        raise BootstrapError(f"APK package mismatch: expected {package}")
    return int(match.group(2))


def installed(serial, package):
    result = adb(serial, "shell", "pm", "path", package, check=False)
    lines = [line.removeprefix("package:") for line in text(result).splitlines()
             if line.startswith("package:")]
    if not lines:
        return None
    base = next((line for line in lines if line.endswith("/base.apk")), None)
    if not base:
        raise BootstrapError(f"cannot identify installed base.apk for {package}")
    with tempfile.TemporaryDirectory(prefix="termux-apk-") as temp:
        os.chmod(temp, 0o700)
        copy = Path(temp) / "base.apk"
        adb(serial, "pull", base, str(copy), timeout=90)
        return apk_info(copy, package)


def inspect(args):
    model, api = device(args.serial)
    print(f"device={args.serial} model={model} android_api={api}")
    termux_version = None
    for package in (*PACKAGES.values(), *PLAY_PACKAGES):
        if package in PACKAGES.values():
            try:
                version = installed(args.serial, package)
            except BootstrapError as exc:
                print(f"package={package} INVALID ({exc})")
                raise
            print(f"package={package} versionCode={version if version is not None else 'absent'} signer={'matched' if version is not None else 'n/a'}")
            if package == "com.termux":
                termux_version = version
        else:
            present = text(adb(args.serial, "shell", "pm", "path", package, check=False)).startswith("package:")
            print(f"package={package} installed={str(present).lower()}")
    if termux_version is not None:
        print(f"termux_user={uid(args.serial)} (recheck after any reinstall)")
    print("Android permissions, WireGuard tunnel, ntfy subscription, and Whisperian settings require attended verification.")


def install_apps(args):
    device(args.serial)
    if not args.confirm_install:
        raise BootstrapError("install requires --confirm-install after inspect (never uninstalls or downgrades)")
    directory = Path(args.apks_dir).expanduser()
    actions = []
    # Preflight the entire set before touching any installed package.
    for filename, package in PACKAGES.items():
        path = directory / filename
        if not path.is_file():
            raise BootstrapError(f"missing {path}; run termux/build-apks.sh build")
        wanted = apk_info(path, package)
        if wanted != EXPECTED_VERSIONS[package]:
            raise BootstrapError(f"{package} versionCode {wanted} differs from pinned {EXPECTED_VERSIONS[package]}")
        current = installed(args.serial, package)
        if current is not None and current > wanted:
            raise BootstrapError(f"{package} is newer ({current}>{wanted}); no downgrade or uninstall")
        actions.append((path, package, wanted, current))
    for path, package, wanted, current in actions:
        if current == wanted:
            print(f"already installed: {package} versionCode={wanted}")
            continue
        print(f"installing {package} versionCode={wanted} on {args.serial}; approve any Android prompt on-device")
        result = adb(args.serial, "install", "-r", str(path), check=False, timeout=180)
        if result.returncode or installed(args.serial, package) != wanted:
            raise BootstrapError(f"install incomplete for {package}; approve on-device and rerun; never uninstall to fix a signature conflict")
    print("Three matching Termux packages installed. Launch Termux once and approve Termux:Boot's first launch manually.")


def phone_frontmost(serial):
    top = text(adb(serial, "shell", "dumpsys", "activity", "activities"))
    return any("com.termux/" in line for line in top.splitlines()
               if "mResumedActivity:" in line or "topResumedActivity=" in line)


def terminal_command(serial, command):
    if not phone_frontmost(serial):
        raise BootstrapError("Termux is not the foreground Android app; unlock and focus its terminal")
    # Android input text maps %s to a space. Commands sent here contain no secrets.
    adb(serial, "shell", "input", "text", command.replace(" ", "%s"))
    adb(serial, "shell", "input", "keyevent", "KEYCODE_ENTER")


def phone_ssh(serial, port, user, *command, data=None, check=True):
    key = Path.home() / ".ssh/homelab"
    if not key.is_file():
        raise BootstrapError(f"Mac's {key} is missing; provision the personal profile first")
    known = Path.home() / ".cache/dotfiles-termux/known_hosts"
    known.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    argv = ["ssh", "-F", "/dev/null", "-p", str(port), "-i", str(key),
            "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes",
            "-o", "PasswordAuthentication=no", "-o", "ConnectTimeout=5",
            "-o", "StrictHostKeyChecking=accept-new", "-o", f"UserKnownHostsFile={known}",
            "-o", f"HostKeyAlias=termux-usb-{serial}", f"{user}@127.0.0.1", shlex.join(command)]
    return run(argv, data=data, check=check, timeout=180)


@contextmanager
def usb_connection(serial, start_ui, packages_ready=False):
    user = uid(serial)
    port = text(adb(serial, "forward", "tcp:0", "tcp:8022"))
    if not port.isdecimal():
        raise BootstrapError("ADB failed to allocate a USB-only SSH forward")
    try:
        probe = phone_ssh(serial, port, user, "true", check=False)
        if probe.returncode:
            if b"REMOTE HOST IDENTIFICATION HAS CHANGED" in probe.stderr:
                raise BootstrapError("Termux USB SSH host key changed; verify its new fingerprint on-device, then remove only termux-usb-" + serial + " from ~/.cache/dotfiles-termux/known_hosts")
            if not start_ui:
                raise BootstrapError("phone SSH not ready; rerun provision --start-ui while Termux is foreground")
            # Only public key material crosses Android's input tool. No dotfiles
            # or private keys are pushed to shared storage by ADB.
            pub = (Path.home() / ".ssh/homelab.pub").read_text().strip()
            if not re.fullmatch(r"ssh-ed25519 [A-Za-z0-9+/=]+(?: [^\n]*)?", pub):
                raise BootstrapError("Mac homelab public key is invalid")
            adb(serial, "shell", "am", "start", "-n", "com.termux/.app.TermuxActivity")
            time.sleep(2)
            if not packages_ready:
                terminal_command(serial, "pkg install -y chezmoi git openssh coreutils termux-api")
                raise BootstrapError("PENDING: finish pkg install on the visible Termux terminal and wait for its shell prompt; rerun provision --start-ui --packages-ready")
            terminal_command(serial, "mkdir -p ~/.ssh; chmod 700 ~/.ssh; touch ~/.ssh/authorized_keys")
            # grep by key blob prevents duplicates across reruns. No secret is typed.
            blob = pub.split()[1]
            # Drop the arbitrary comment before typing into a shell; only the
            # validated key blob is needed for authorized_keys.
            terminal_command(serial, f"grep -qF '{blob}' ~/.ssh/authorized_keys || echo 'ssh-ed25519 {blob}' >> ~/.ssh/authorized_keys")
            terminal_command(serial, "chmod 600 ~/.ssh/authorized_keys; sshd -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no -p 8022")
            for _ in range(20):
                if phone_ssh(serial, port, user, "true", check=False).returncode == 0:
                    break
                time.sleep(3)
            else:
                raise BootstrapError("USB SSH not ready; finish package prompts in Termux, check the public-key line, then rerun")
        yield port, user
    finally:
        adb(serial, "forward", "--remove", f"tcp:{port}", check=False)


def key_fingerprint(serial, port, user, name):
    command = "ssh-keygen -lf ~/.ssh/" + name + " 2>/dev/null | awk '{print $2}'"
    return text(phone_ssh(serial, port, user, "sh", "-c", command, check=False))


def install_key(serial, port, user, name, fingerprint, ref):
    old = key_fingerprint(serial, port, user, name)
    if old == fingerprint:
        print(f"key={name} fingerprint=matched (kept)")
        return
    if old:
        raise BootstrapError(f"{name} has an unexpected fingerprint; refusing to overwrite a live key")
    material = run(["op", "read", ref]).stdout
    if not material.startswith(b"-----BEGIN OPENSSH PRIVATE KEY-----"):
        raise BootstrapError(f"1Password did not return an OpenSSH private key for {name}")
    # Fixed filenames and fixed fingerprint; remote temp is mode 0600 and is
    # removed on any validation failure. Key bytes travel only on SSH stdin.
    script = ("set -eu; umask 077; mkdir -p ~/.ssh; chmod 700 ~/.ssh; "
              f"tmp=$(mktemp ~/.ssh/.{name}.XXXXXX); trap 'rm -f \"$tmp\"' EXIT; "
              "cat > \"$tmp\"; "
              "got=$(ssh-keygen -lf \"$tmp\" | awk '{print $2}'); "
              f"[ \"$got\" = {shlex.quote(fingerprint)} ] || exit 21; "
              f"mv \"$tmp\" ~/.ssh/{name}; chmod 600 ~/.ssh/{name}; "
              f"ssh-keygen -y -f ~/.ssh/{name} > ~/.ssh/{name}.pub; "
              f"chmod 644 ~/.ssh/{name}.pub")
    try:
        phone_ssh(serial, port, user, "sh", "-c", script, data=material)
    finally:
        # Python cannot guarantee zeroization, but never formats or logs bytes.
        del material
    print(f"key={name} fingerprint=matched (provisioned over USB SSH)")


def choose_key_source(explicit):
    if explicit:
        return explicit
    if not sys.stdin.isatty():
        raise BootstrapError("choose --key-source mac or --key-source phone on EVERY provision run")
    answer = input("Retrieve SSH keys from 1Password on [m]ac or [p]hone this run? ").strip().lower()
    if answer not in ("m", "p"):
        raise BootstrapError("no key retrieval source selected")
    return "mac" if answer == "m" else "phone"


def provision(args):
    device(args.serial)
    if installed(args.serial, "com.termux") is None:
        raise BootstrapError("install the three matching Termux APKs first")
    source = choose_key_source(args.key_source)
    if source == "phone" and not args.ready_phone_token and args.packages_ready:
        raise BootstrapError("phone-side retrieval needs --ready-phone-token AFTER you copy the service token on-device")
    with usb_connection(args.serial, args.start_ui, args.packages_ready) as (port, user):
        if source == "phone" and not args.ready_phone_token:
            raise BootstrapError("phone-side retrieval needs --ready-phone-token AFTER you copy the service token on-device")
        if source == "mac":
            for name, (fingerprint, ref) in FINGERPRINTS.items():
                install_key(args.serial, port, user, name, fingerprint, ref)
        existing = text(phone_ssh(args.serial, port, user, "sh", "-c",
                                  "test -e ~/.config/chezmoi/chezmoi.yaml && cat ~/.config/chezmoi/chezmoi.yaml || true"))
        if existing and not re.search(r'^\s*profile:\s*["\']?termux["\']?\s*$', existing, re.M):
            raise BootstrapError("existing chezmoi profile is not termux; refusing to replace it")
        if not existing:
            phone_ssh(args.serial, port, user, "sh", "-c",
                      "mkdir -p ~/.config/chezmoi; chmod 700 ~/.config/chezmoi; "
                      "umask 077; printf '%s\\n' 'data:' '  profile: \"termux\"' > ~/.config/chezmoi/chezmoi.yaml")
        print("phone owns its configuration: chezmoi init --apply (HTTPS, profile termux)")
        phone_ssh(args.serial, port, user, "chezmoi", "init", "--apply", "https://github.com/cartwmic/dotfiles.git")
        for name, (fingerprint, _) in FINGERPRINTS.items():
            if key_fingerprint(args.serial, port, user, name) != fingerprint:
                raise BootstrapError(f"{name} is missing/mismatched after apply; a missing phone-side token is only a soft skip")
        for name in ("~/.termux/boot/start-sshd", "~/bin/herdr-jump", "~/.ssh/authorized_keys"):
            phone_ssh(args.serial, port, user, "sh", "-c", f"test -f {name}")
        print(f"provisioned termux_user={user}; SSH keys and managed files verified")
        print("NEXT: launch Termux:Boot once; grant battery/boot permissions on-device; set up WireGuard and Play apps (see termux/README.md).")


def verify(args):
    device(args.serial)
    for package in PACKAGES.values():
        if installed(args.serial, package) is None:
            raise BootstrapError(f"missing matching signed package: {package}")
    with usb_connection(args.serial, False) as (port, user):
        for name, (fingerprint, _) in FINGERPRINTS.items():
            if key_fingerprint(args.serial, port, user, name) != fingerprint:
                raise BootstrapError(f"key fingerprint mismatch: {name}")
        phone_ssh(args.serial, port, user, "sh", "-c",
                  "test -x ~/.termux/boot/start-sshd && test -x ~/bin/herdr-jump && "
                  "test -f ~/.ssh/authorized_keys && "
                  "test \"$(stat -c %a ~/.ssh/authorized_keys)\" = 600")
        # BatchMode and strict known-hosts deliberately cannot auto-trust a new Mac.
        phone_ssh(args.serial, port, user, "ssh", "-o", "BatchMode=yes", "-o", "PasswordAuthentication=no",
                  "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=yes", "macbook",
                  "/bin/zsh -lic 'command -v herdr'")
        print("PASS: signed packages, phone-owned files, key fingerprints, USB key-only SSH, phone -> macbook SSH and Herdr executable")
    missing = [p for p in PLAY_PACKAGES if not text(adb(args.serial, "shell", "pm", "path", p, check=False)).startswith("package:")]
    if missing:
        raise BootstrapError("missing Play apps: " + ", ".join(missing))
    if not args.attest_android:
        raise BootstrapError("PENDING attended Android check: WireGuard tunnel, ntfy test, Whisperian input/Accessibility, Termux->ssh macbook->Herdr pane; rerun --attest-android only after checking")
    print("Operator attested Android/VPN/ntfy/Whisperian/visible Herdr path. Reboot and off-LAN tests remain pending until explicitly run.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    for cmd in ("inspect", "install", "provision", "verify"):
        sub = subs.add_parser(cmd)
        sub.add_argument("--serial", required=True, help="exact `adb devices` serial (never infer an emulator)")
        if cmd == "install":
            sub.add_argument("--apks-dir", required=True)
            sub.add_argument("--confirm-install", action="store_true")
        if cmd == "provision":
            sub.add_argument("--key-source", choices=("mac", "phone"))
            sub.add_argument("--ready-phone-token", action="store_true")
            sub.add_argument("--start-ui", action="store_true", help="type only the initial package command into foreground Termux")
            sub.add_argument("--packages-ready", action="store_true", help="after package install and a visible shell prompt, allow the SSH bootstrap commands")
        if cmd == "verify":
            sub.add_argument("--attest-android", action="store_true")
    args = parser.parse_args()
    try:
        {"inspect": inspect, "install": install_apps, "provision": provision, "verify": verify}[args.command](args)
    except (BootstrapError, OSError) as exc:
        print(f"[bootstrap-phone] {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
