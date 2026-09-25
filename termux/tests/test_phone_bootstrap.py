#!/usr/bin/env python3
"""Black-box Mac CLI scenarios with scripted adb/SSH/op/WireGuard backends.

No connected Android device or OPNsense service is touched by these tests.
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CERT = "ec1ab3f5e4d261a4c6c5e2979b4af4f8d0071a951761575a2929ce59dcf1c0c1"
SERIAL = "TEST-MOTO"
PRIVATE = "AQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQE="  # Dummy, never a real credential.
OLD_PRIVATE = base64.b64encode(bytes([4]) * 32).decode()
PUBLIC = "AgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgI="
OLD_PUBLIC = base64.b64encode(bytes([3]) * 32).decode()

STUB = r'''#!/usr/bin/env python3
import base64, json, os, re, sys
from pathlib import Path
name=Path(sys.argv[0]).name; args=sys.argv[1:]
path=Path(os.environ['PHONE_TEST_STATE']); state=json.loads(path.read_text())
def save(): path.write_text(json.dumps(state))
def note(msg): state['calls'].append(msg); save()
def finish(code=0,output=''):
    save(); sys.stdout.write(output); sys.exit(code)
if name=='adb':
    if args==['devices','-l']:
        transport=('transport_id:22' if state.get('tcp_transport') else 'usb:mock-port transport_id:22')
        finish(output=f'List of devices attached\nTEST-MOTO device {transport}\nemulator-5554 device transport_id:23\n')
    if args[:2]!=['-s','TEST-MOTO']: finish(9)
    a=args[2:]; note('adb '+ ' '.join(a[:4]))
    if a[:2]==['shell','getprop']:
        finish(output=('moto test\n' if a[2]=='ro.product.model' else '35\n'))
    if a[:5]==['shell','cmd','package','list','packages']:
        finish(output=('package:com.termux uid:10465\n' if 'com.termux' in state['packages'] else ''))
    if a[:3]==['shell','pm','path']:
        pkg=a[3]
        finish(output=(f'package:/data/app/{pkg}/base.apk\n' if pkg in state['packages'] else ''))
    if a and a[0]=='pull':
        pkg=a[1].split('/')[3]
        value='BAD' if state.get('bad_installed')==pkg else state['packages'][pkg]
        Path(a[2]).write_text(f"{pkg},{value}")
        finish()
    if a[:2]==['install','-r']:
        pkg,version=Path(a[2]).read_text().split(','); state['packages'][pkg]=int(version); finish(output='Success\n')
    if a[:2]==['forward','tcp:0']: finish(output='39000\n')
    if a[:2]==['forward','--remove']: finish()
    if a[:3]==['shell','dumpsys','activity']: finish(output='mResumedActivity: com.termux/.app.TermuxActivity\n')
    if a[:3]==['shell','input','text'] and 'sshd' in a[3]: state['ready']=True
    finish()
if name=='apksigner':
    pkg=Path(args[-1]).read_text()
    cert=('f'*64 if 'BAD' in pkg else os.environ['PHONE_TEST_CERT'])
    finish(output=f'Signer #1 certificate SHA-256 digest: {cert}\n')
if name=='aapt':
    pkg,version=Path(args[-1]).read_text().split(',')
    finish(output=f"package: name='{pkg}' versionCode='{version}' versionName='test'\n")
if name=='ssh':
    if 'root@10.19.1.1' in args:
        source=sys.stdin.read()
        if 'PHONE_SPEC_B64=' in source:
            encoded=re.search(r'PHONE_SPEC_B64=([A-Za-z0-9+/=]+)',source).group(1)
            spec=json.loads(base64.b64decode(encoded)); action=spec['action']; mode=spec['mode']
            old=dict(uuid='old-uuid',name='cartwmic-ssh-phone',public_key=state['old_public'],address='10.21.1.7/32')
            oldmap=dict(mac=state.get('old_mac','5e:51:a2:24:38:79'),lan='10.19.1.88',hostname='ssh-phone')
            candidate=(dict(uuid='new-uuid',name='cartwmic-ssh-phone-candidate',public_key=state['new_public'],address=state['new_address']) if state.get('staged') else None)
            newmap=(dict(mac=state['new_mac'],lan=state['new_lan'],hostname='ssh-phone-candidate') if state.get('staged') else None)
            summary=dict(fingerprint=('after-stage' if state.get('staged') else 'before-stage'),server_public_key=os.environ['PHONE_TEST_PUBLIC'],old_peer=old,old_reservation=oldmap,candidate_peer=candidate,candidate_reservation=newmap)
            if action=='plan': summary.update(mode=mode,proposed=dict(mac=spec['mac'],lan=spec['lan'],address=spec['address'],public_key=spec['public_key']),changes=['stage candidate'])
            if action=='apply':
                if spec['expected_fingerprint']!=summary['fingerprint']: finish(2)
                if mode=='restore':
                    changed=state.get('old_mac','5e:51:a2:24:38:79')!=spec['mac']
                    state['old_mac']=spec['mac']
                else:
                    changed=True
                    state.update(staged=True,new_mac=spec['mac'],new_lan=spec['lan'],new_address=spec['address'],new_public=spec['public_key'])
                summary.update(changed=changed,backup='/conf/backup/config-phone-test.xml' if changed else None)
                note('router config write' if changed else 'router no config change')
            finish(output=json.dumps(summary)+'\n')
        note('router '+source.strip().replace('\n',' | '))
        if 'wg show wg1 allowed-ips' in source:
            finish(output=state['new_public']+'\t'+state['new_address']+'\n')
        finish(output='OK\n')
    if '-G' in args: finish(output='hostname 10.21.1.8\nuser u0_a999\n')
    command=args[-1]; note('phone ssh '+('key-stream' if 'cat >' in command else ('macbook_login' if 'zsh -lic' in command else command[:65])))
    if command=='true' and not state['ready']: finish(255)
    if 'ssh-keygen -lf ~/.ssh/' in command:
        key=re.search(r'ssh-keygen -lf ~/.ssh/([\w-]+)',command).group(1)
        finish(output=(state['keys'].get(key,'')+'\n' if key in state['keys'] else ''))
    if 'cat >' in command and 'ssh-keygen -lf' in command:
        key=re.search(r'\.ssh/\.([\w-]+)\.XXXXXX',command).group(1)
        state['keys'][key]=os.environ['PHONE_TEST_HOMELAB'] if key=='homelab' else os.environ['PHONE_TEST_WHONIX']
        _secret=sys.stdin.read(); finish()
    if 'chezmoi.yaml' in command and 'cat ~/.config' in command:
        finish(output=('data:\n  profile: "termux"\n' if state['profile'] else ''))
    if 'printf' in command and 'chezmoi.yaml' in command: state['profile']=True; finish()
    if 'chezmoi' in command and 'init' in command:
        state['profile']=True
        if os.environ.get('PHONE_TEST_PHONE_TOKEN')=='1':
            state['keys']['homelab']=os.environ['PHONE_TEST_HOMELAB']
            state['keys']['whonix-homelab']=os.environ['PHONE_TEST_WHONIX']
        finish()
    if 'macbook' in command:
        login=('zsh -lic' in command and 'command -v herdr' in command)
        finish(0 if login else 1, '/mock/herdr\n' if login else '')
    finish(0 if state['ready'] else 1)
if name=='op':
    note('op '+ ('item create' if 'create' in args else ('item edit' if 'edit' in args else ('read ref' if 'read' in args else 'metadata'))))
    if args[:2]==['item','get']:
        found=(state.get('candidate_item') if 'Candidate WireGuard' in args[2] else state.get('retired_exists',False))
        finish(0 if found else 2, '{"title":"existing"}\n' if found else '')
    if args[:2]==['item','edit']:
        if 'Candidate WireGuard' in args[2]:
            if state.get('fail_candidate_edit_once'):
                state['fail_candidate_edit_once']=False; finish(2)
            state['active_public']=os.environ['PHONE_TEST_PUBLIC']; state['active_exists']=True; state['candidate_item']=False
        else:
            state['retired_exists']=True; state['active_exists']=False
        finish(output='edited\n')
    if args[:3]==['item','template','get']:
        finish(output=json.dumps(dict(title='',category='SECURE_NOTE',fields=[dict(id='notesPlain',label='notesPlain',value='')]))+'\n')
    if args[:2]==['item','create']:
        body=json.loads(sys.stdin.read()); state['op_item_fields']=[f['label'] for f in body['fields']]; state['candidate_item']=True; finish(output='created\n')
    if args[:1]==['read'] and 'WireGuard' in args[-1]:
        candidate='Candidate WireGuard' in args[-1]
        if (candidate and not state.get('candidate_item')) or (not candidate and not state['active_exists']): finish(2)
        if 'Private' in args[-1]: finish(output=(os.environ['PHONE_TEST_PRIVATE'] if candidate else os.environ['PHONE_TEST_OLD_PRIVATE'])+'\n')
        finish(output=(os.environ['PHONE_TEST_PUBLIC'] if candidate else state['active_public'])+'\n')
    if args[:1]==['read']: finish(output='-----BEGIN OPENSSH PRIVATE KEY-----\ndummy\n')
    finish(output='2.31.1\n')
if name=='wg':
    if 'genkey' in args: finish(output=os.environ['PHONE_TEST_PRIVATE']+'\n')
    value=sys.stdin.read().strip()
    finish(output=(os.environ['PHONE_TEST_OLD_PUBLIC'] if value==os.environ['PHONE_TEST_OLD_PRIVATE'] else os.environ['PHONE_TEST_PUBLIC'])+'\n')
if name=='qrencode':
    note('qrencode private QR (bytes not logged)')
    Path(args[args.index('-o')+1]).write_bytes(b'PNG-stub')
    finish()
finish(98)
'''


class PhoneCLITest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="phone-cli-test-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        self.home.mkdir()
        bin_dir = Path(self.temp.name) / "bin"
        bin_dir.mkdir()
        for name in ("adb", "ssh", "op", "wg", "qrencode", "aapt", "apksigner", "zipalign"):
            file = bin_dir / name
            file.write_text(STUB)
            file.chmod(0o755)
        (self.home / ".ssh").mkdir()
        (self.home / ".ssh/homelab").write_text("dummy-Mac-private-key")
        (self.home / ".ssh/homelab.pub").write_text("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDummyPublicKeyForTestAAAA== mac\n")
        self.bt = bin_dir
        self.apks = Path(self.temp.name) / "apks"
        self.apks.mkdir()
        for file, pkg, code in (("termux-app.apk", "com.termux", 1008),
                                ("termux-api.apk", "com.termux.api", 1003),
                                ("termux-boot.apk", "com.termux.boot", 1000)):
            (self.apks / file).write_text(f"{pkg},{code}")
        self.state_path = Path(self.temp.name) / "state.json"
        self.state = dict(packages={p: 1 for p in ("com.wireguard.android", "io.heckel.ntfy", "app.whisperian.client")},
                          ready=False, profile=False, keys={}, calls=[], old_public=OLD_PUBLIC, active_public=OLD_PUBLIC, active_exists=True, staged=False)
        self.save()
        self.env = dict(os.environ, HOME=str(self.home), PATH=str(bin_dir) + os.pathsep + os.environ["PATH"],
                        ANDROID_BUILD_TOOLS=str(bin_dir), PHONE_TEST_STATE=str(self.state_path),
                        PHONE_TEST_CERT=CERT, PHONE_TEST_PUBLIC=PUBLIC, PHONE_TEST_PRIVATE=PRIVATE,
                        PHONE_TEST_OLD_PUBLIC=OLD_PUBLIC, PHONE_TEST_OLD_PRIVATE=OLD_PRIVATE,
                        PHONE_TEST_HOMELAB="SHA256:s1NF+DDqZKlvvy/wDQXBACMs3jb/cjkvy/UpOYbypOQ",
                        PHONE_TEST_WHONIX="SHA256:oNPHkrMebH0d0dq6B+gexDeimXdUbDHh38dHf3EGpEE")

    def save(self):
        self.state_path.write_text(json.dumps(self.state))

    def invoke(self, file, *args):
        result = subprocess.run([sys.executable, str(ROOT / "termux" / file), *args], env=self.env,
                                capture_output=True, text=True, timeout=60)
        self.state = json.loads(self.state_path.read_text())
        self.assertNotIn(PRIVATE, result.stdout + result.stderr)
        self.assertNotIn(OLD_PRIVATE, result.stdout + result.stderr)
        return result

    def test_fresh_phone_installs_provisions_and_requires_attended_proof(self):
        inspect = self.invoke("bootstrap-phone.py", "inspect", "--serial", SERIAL)
        self.assertEqual(inspect.returncode, 0, inspect.stderr)
        self.assertIn("package=com.termux versionCode=absent", inspect.stdout)
        install = self.invoke("bootstrap-phone.py", "install", "--serial", SERIAL,
                              "--apks-dir", str(self.apks), "--confirm-install")
        self.assertEqual(install.returncode, 0, install.stderr)
        packages = self.invoke("bootstrap-phone.py", "provision", "--serial", SERIAL,
                               "--key-source", "mac", "--start-ui")
        self.assertEqual(packages.returncode, 2)
        self.assertIn("PENDING: finish pkg install", packages.stderr)
        self.assertFalse(self.state['ready'])
        provision = self.invoke("bootstrap-phone.py", "provision", "--serial", SERIAL,
                                "--key-source", "mac", "--start-ui", "--packages-ready")
        self.assertEqual(provision.returncode, 0, provision.stderr)
        pending = self.invoke("bootstrap-phone.py", "verify", "--serial", SERIAL)
        self.assertEqual(pending.returncode, 2)
        self.assertIn("PENDING attended Android check", pending.stderr)
        done = self.invoke("bootstrap-phone.py", "verify", "--serial", SERIAL, "--attest-android")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Operator attested", done.stdout)
        self.assertEqual(self.state['packages']['com.termux.boot'], 1000)
        self.assertEqual(len([x for x in self.state['calls'] if x.startswith('op read ref')]), 2)
        self.assertIn('phone ssh macbook_login', self.state['calls'])
        self.assertFalse(any('uninstall' in x for x in self.state['calls']))

    def test_phone_side_1password_choice_is_explicit(self):
        installed = self.invoke("bootstrap-phone.py", "install", "--serial", SERIAL,
                                "--apks-dir", str(self.apks), "--confirm-install")
        self.assertEqual(installed.returncode, 0)
        missing_choice = self.invoke("bootstrap-phone.py", "provision", "--serial", SERIAL, "--start-ui")
        self.assertEqual(missing_choice.returncode, 2)
        self.assertIn("choose --key-source", missing_choice.stderr)
        packages = self.invoke("bootstrap-phone.py", "provision", "--serial", SERIAL,
                               "--key-source", "phone", "--start-ui")
        self.assertEqual(packages.returncode, 2)
        self.assertIn("PENDING: finish pkg install", packages.stderr)
        missing_token = self.invoke("bootstrap-phone.py", "provision", "--serial", SERIAL,
                                    "--key-source", "phone", "--start-ui", "--packages-ready")
        self.assertEqual(missing_token.returncode, 2)
        self.assertIn("--ready-phone-token", missing_token.stderr)
        self.env['PHONE_TEST_PHONE_TOKEN'] = '1'
        done = self.invoke("bootstrap-phone.py", "provision", "--serial", SERIAL,
                           "--key-source", "phone", "--ready-phone-token", "--start-ui", "--packages-ready")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse(any(x == 'op read ref' for x in self.state['calls']))

    def test_signed_apk_set_check_is_an_outer_cli(self):
        jdk = self.home / 'jdk/bin'
        jdk.mkdir(parents=True)
        java = jdk / 'java'
        java.write_text('#!/bin/sh\nexit 0\n')
        java.chmod(0o755)
        env = dict(self.env, JAVA_HOME=str(jdk.parent))
        result = subprocess.run(['bash', str(ROOT / 'termux/build-apks.sh'), 'check',
                                 '--app', str(self.apks / 'termux-app.apk'),
                                 '--api', str(self.apks / 'termux-api.apk'),
                                 '--boot', str(self.apks / 'termux-boot.apk')],
                                capture_output=True, text=True, env=env, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('verified app=', result.stdout)

    def test_refuse_tcp_adb_even_with_explicit_serial(self):
        self.state['tcp_transport'] = True
        self.save()
        result = self.invoke("bootstrap-phone.py", "inspect", "--serial", SERIAL)
        self.assertEqual(result.returncode, 2)
        self.assertIn("not a USB transport", result.stderr)
        self.assertFalse(any(x.startswith('adb install') for x in self.state['calls']))

    def test_refuse_bad_certificate_before_any_install(self):
        (self.apks / "termux-api.apk").write_text("com.termux.api,BAD")
        result = self.invoke("bootstrap-phone.py", "install", "--serial", SERIAL,
                             "--apks-dir", str(self.apks), "--confirm-install")
        self.assertEqual(result.returncode, 2)
        self.assertFalse(any(x.startswith('adb install') for x in self.state['calls']))

    def test_refuse_existing_differently_signed_termux_without_uninstall(self):
        self.state['packages']['com.termux'] = 1008
        self.state['bad_installed'] = 'com.termux'
        self.save()
        result = self.invoke("bootstrap-phone.py", "install", "--serial", SERIAL,
                             "--apks-dir", str(self.apks), "--confirm-install")
        self.assertEqual(result.returncode, 2)
        self.assertIn('signing certificate mismatch', result.stderr)
        self.assertFalse(any(x.startswith('adb install') or 'uninstall' in x for x in self.state['calls']))

    def test_router_plan_requires_separate_confirmation_and_preserves_old_peer(self):
        result = self.invoke("router-phone.py", "plan", "--mode", "stage", "--mac", "5e:51:a2:24:38:7a",
                             "--lan", "10.19.1.89", "--address", "10.21.1.8/32", "--public-key", PUBLIC)
        self.assertEqual(result.returncode, 0, result.stderr)
        path = next(line.removeprefix('PLAN: ').split('. Review', 1)[0]
                    for line in result.stdout.splitlines() if line.startswith('PLAN: '))
        denied = self.invoke("router-phone.py", "apply", "--plan", path, "--confirm", "NO")
        self.assertEqual(denied.returncode, 2)
        self.assertFalse(self.state['staged'])
        applied = self.invoke("router-phone.py", "apply", "--plan", path, "--confirm", "STAGE-SSH-PHONE")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertTrue(self.state['staged'])
        self.assertEqual(self.state['old_public'], OLD_PUBLIC)
        calls = self.state['calls']
        reload = next(i for i, value in enumerate(calls) if 'configctl template reload OPNsense/Wireguard' in value)
        configure = next(i for i, value in enumerate(calls) if 'configctl wireguard configure' in value)
        self.assertEqual(reload, configure)  # Both in one set -eu script; ordering checked below.
        self.assertLess(calls[reload].index('template reload'), calls[reload].index('wireguard configure'))
        self.assertIn('configctl dhcpd restart', ' '.join(calls))

    def test_wiped_phone_reuses_existing_wireguard_key_and_mapping(self):
        qr = self.invoke("wireguard-phone.py", "prepare", "--mode", "restore", "--serial", SERIAL,
                         "--address", "10.21.1.7/32", "--server-key", PUBLIC)
        self.assertEqual(qr.returncode, 0, qr.stderr)
        self.assertIn('mode=restore', qr.stdout)
        self.assertIn('public_key=' + OLD_PUBLIC, qr.stdout)
        plan = self.invoke("router-phone.py", "plan", "--mode", "restore", "--mac", "5e:51:a2:24:38:7b",
                           "--lan", "10.19.1.88", "--address", "10.21.1.7/32", "--public-key", OLD_PUBLIC)
        self.assertEqual(plan.returncode, 0, plan.stderr)
        path = next(line.removeprefix('PLAN: ').split('. Review', 1)[0]
                    for line in plan.stdout.splitlines() if line.startswith('PLAN: '))
        applied = self.invoke("router-phone.py", "apply", "--plan", path, "--confirm", "RESTORE-SSH-PHONE")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(self.state['old_public'], OLD_PUBLIC)
        self.assertEqual(self.state['old_mac'], '5e:51:a2:24:38:7b')

    def test_wireguard_candidate_saved_without_echoing_secret(self):
        result = self.invoke("wireguard-phone.py", "prepare", "--mode", "replace", "--serial", SERIAL,
                             "--address", "10.21.1.8/32", "--server-key", PUBLIC)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Private key', self.state['op_item_fields'])
        png = self.home / '.cache/dotfiles-termux/wg-import/TEST-MOTO.png'
        self.assertTrue(png.exists())
        self.assertEqual(png.stat().st_mode & 0o777, 0o600)
        cleanup = self.invoke("wireguard-phone.py", "cleanup", "--serial", SERIAL)
        self.assertEqual(cleanup.returncode, 0)
        self.assertFalse(png.exists())

    def test_promote_requires_router_retirement_and_keeps_old_item(self):
        prepare = self.invoke("wireguard-phone.py", "prepare", "--mode", "replace", "--serial", SERIAL,
                              "--address", "10.21.1.8/32", "--server-key", PUBLIC)
        self.assertEqual(prepare.returncode, 0, prepare.stderr)
        early = self.invoke("wireguard-phone.py", "promote", "--serial", SERIAL,
                            "--expected-public-key", PUBLIC, "--confirm-promote")
        self.assertEqual(early.returncode, 2)
        self.assertFalse(any(x == 'op item edit' for x in self.state['calls']))
        self.state['old_public'] = PUBLIC  # scripted router reports retirement completed
        self.state['fail_candidate_edit_once'] = True
        self.save()
        partial = self.invoke("wireguard-phone.py", "promote", "--serial", SERIAL,
                              "--expected-public-key", PUBLIC, "--confirm-promote")
        self.assertEqual(partial.returncode, 2)
        self.assertFalse(self.state['active_exists'])
        self.assertTrue(self.state['candidate_item'])
        promoted = self.invoke("wireguard-phone.py", "promote", "--serial", SERIAL,
                               "--expected-public-key", PUBLIC, "--confirm-promote")
        self.assertEqual(promoted.returncode, 0, promoted.stderr)
        self.assertIn("resuming a partially completed promotion", promoted.stdout)
        self.assertEqual(self.state['active_public'], PUBLIC)
        self.assertFalse(self.state['candidate_item'])
        repeat = self.invoke("wireguard-phone.py", "promote", "--serial", SERIAL,
                             "--expected-public-key", PUBLIC, "--confirm-promote")
        self.assertEqual(repeat.returncode, 0, repeat.stderr)

    @unittest.skipUnless(shutil.which("chezmoi"), "chezmoi is required to render the phone profile")
    def test_phone_apply_refuses_to_replace_unexpected_existing_key(self):
        rendered = subprocess.run(["chezmoi", "--override-data", '{"profile":"termux"}',
                                   "execute-template", "-f", str(ROOT / "run_after_05_provision_ssh_keys.sh.tmpl")],
                                  capture_output=True, text=True, check=True)
        script = Path(self.temp.name) / "phone-key.sh"
        script.write_text(rendered.stdout)
        key = self.home / ".ssh/homelab"
        key.write_text("wrong key, not a credential\n")
        result = subprocess.run(["bash", str(script)], env=self.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 1)
        self.assertIn("refusing to overwrite", result.stderr)
        self.assertEqual(key.read_text(), "wrong key, not a credential\n")
        self.assertFalse(any(x.startswith('op read') for x in self.state['calls']))


if __name__ == "__main__":
    unittest.main()
