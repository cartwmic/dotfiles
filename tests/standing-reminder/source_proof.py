#!/usr/bin/env python3
"""Read-only profile mapping and exact source-scoped, unforced destination preview.

Rendered and live content is read separately; only hashes/paths are printed.
Unknown hooks or missing op block before any source-state command can run.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HOME = Path.home()
RUNTIME = '.pi/agent/extensions/standing-reminder/'
FILES = ['index.ts','config.ts','create_config.json','README.md']
DESTINATIONS = [HOME/(RUNTIME+name.replace('create_','')) for name in FILES]
DESTINATIONS += [HOME/'.local/share/pi-patches/standing-reminder-origin/README.md']

class Blocked(RuntimeError): pass

def digest(data): return hashlib.sha256(data).hexdigest()

def invoke(args):
    result=subprocess.run(args,capture_output=True,text=True,timeout=90)
    if result.returncode:
        # These commands target only reminder content; never dump general rendered source.
        raise Blocked(f'command failed ({result.returncode}): {args!r}; {result.stderr[-1800:]}')
    return result.stdout


def preflight(config):
    if not config.is_file(): raise Blocked(f'effective config missing: {config}')
    # dump-config reads configuration, not source state; inspect hook before managed/cat/apply.
    effective=json.loads(invoke(['chezmoi','--config',str(config),'dump-config','--format','json']))
    hook=effective.get('hooks',{}).get('read-source-state',{}).get('pre')
    if hook:
        command=hook.get('command') if isinstance(hook,dict) else None
        if command != '.local/share/chezmoi/.install-password-manager.sh':
            raise Blocked('unknown read-source-state.pre hook; owner must review before source read')
        if hook.get('args'): raise Blocked('unexpected read-source hook arguments')
        script=HOME/command
        expected=(ROOT/'.install-password-manager.sh').read_bytes()
        if not script.is_file() or script.read_bytes()!=expected:
            raise Blocked('effective hook differs from inspected install-password-manager source')
        utils=HOME/'.local/share/chezmoi/utils.sh'
        if not utils.is_file() or utils.read_bytes()!=(ROOT/'utils.sh').read_bytes():
            raise Blocked('effective hook utils.sh differs from inspected function-only source')
        if not shutil.which('op'):
            raise Blocked('op missing: read-source hook could install software/create WSL symlink')
        print(f'Preflight: known hook sha256={digest(expected)}; op={shutil.which("op")} (no install)')
    return effective.get('data',{}).get('profile')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=Path(os.environ.get('CHEZMOI_CONFIG_FILE',str(HOME/'.config/chezmoi/chezmoi.yaml'))))
    args=parser.parse_args()
    try:
        if not shutil.which('chezmoi'): raise Blocked('chezmoi unavailable')
        profile=preflight(args.config)
        if profile not in ('personal','axon-work-computer'): raise Blocked(f'desktop preview requires desktop profile, got {profile}')
        removals=(ROOT/'.chezmoiremove').read_text()
        for dest in DESTINATIONS:
            if str(dest.relative_to(HOME)) in [s.strip() for s in removals.splitlines() if not s.startswith('#')]:
                raise Blocked(f'touched destination is scheduled for removal: {dest}')
        base=['chezmoi','--config',str(args.config),'--source',str(ROOT)]
        for test_profile in ('personal','axon-work-computer','termux'):
            managed=invoke(base+['--override-data',json.dumps({'profile':test_profile}),'managed','--include','files'])
            paths={line.removeprefix(str(HOME)+'/') for line in managed.splitlines()}
            for name in FILES:
                dest=RUNTIME+name.replace('create_','')
                if (dest in paths) != (test_profile!='termux'): raise Blocked(f'{test_profile}: wrong mapping for {dest}')
            if RUNTIME+'AGENTS.md' in paths or any(s.startswith('tests/') for s in paths):
                raise Blocked(f'{test_profile}: source-only instructions/tests are managed')
            if test_profile=='termux' and any(s.startswith('.pi/') for s in paths):
                raise Blocked('termux unexpectedly includes Pi')
            print(f'PASS mapping {test_profile}: runtime/README/config gate; AGENTS/tests ignored')
        for dest in DESTINATIONS:
            source=invoke(base+['source-path',str(dest)]).strip()
            if not Path(source).resolve().is_relative_to(ROOT): raise Blocked(f'wrong source for {dest}: {source}')
            rendered=invoke(base+['cat',str(dest)]).encode()
            live=dest.read_bytes() if dest.exists() else None
            print(f'Independent reads: {source} -> {dest}; rendered={digest(rendered)} live={digest(live) if live is not None else "absent"}')
        command=base+['apply','--dry-run','--verbose']+[str(d) for d in DESTINATIONS]
        print('Unforced exact targeted preview:', ' '.join(command))
        preview=invoke(command)
        print(f'PASS source preview profile={profile}; preview sha256={digest(preview.encode())}; no apply/force')
        return 0
    except (Blocked,OSError,ValueError,subprocess.TimeoutExpired) as exc:
        print(f'BLOCKED: {exc}',file=sys.stderr); return 2

if __name__=='__main__': raise SystemExit(main())
