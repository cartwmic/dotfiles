#!/usr/bin/env python3
"""Read-only worktree preview. Captured output is never echoed (may be secret)."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
PREFIX='dot_pi/private_agent/extensions/learnings-monitor/'

def run(args, env=None):
    result=subprocess.run(args,capture_output=True,env=env,timeout=60)
    if result.returncode:
        raise RuntimeError(f'prerequisite/check failed: {args[0]} {args[1] if len(args)>1 else ""} (exit {result.returncode}); output suppressed')
    return result.stdout

def digest(data): return hashlib.sha256(data).hexdigest()

def main():
    config=Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))/'chezmoi/chezmoi.yaml'
    if not config.is_file(): raise RuntimeError('prerequisite: effective chezmoi YAML config unavailable; do not provision it')
    text=config.read_text()
    if 'read-source-state' in text:
        if '.install-password-manager.sh' not in text: raise RuntimeError('prerequisite: unfamiliar read-source hook needs owner inspection')
        if not shutil.which('op'): raise RuntimeError('prerequisite: op unavailable; hook could install/provision')
    # Inspect persistent removals before targeted dry-runs; never apply them.
    removals=(ROOT/'.chezmoiremove').read_bytes()
    command=['chezmoi','--source',str(ROOT),'--config',str(config)]
    profile=run(command+['execute-template','{{ .profile }}']).decode().strip()
    if profile not in ('personal','axon-work-computer'): raise RuntimeError('prerequisite: desktop profile required')
    if profile=='personal':
        env=dict(os.environ)
        token=Path.home()/'.config/agent-harness/op-service-token'
        try:
            auth=subprocess.run(['op','read','op://developer/RustDesk/password'],capture_output=True,env=env,timeout=30)
            authenticated=auth.returncode==0
            del auth
        except subprocess.TimeoutExpired:
            authenticated=False
        if not authenticated and token.is_file():
            if token.stat().st_mode & 0o077: raise RuntimeError('prerequisite: service token must be mode 0600')
            env['OP_SERVICE_ACCOUNT_TOKEN']=token.read_text().strip()
            auth=subprocess.run(['op','read','op://developer/RustDesk/password'],capture_output=True,env=env,timeout=30)
            authenticated=auth.returncode==0
            del auth
        if not authenticated: raise RuntimeError('prerequisite: owner 1Password access unavailable; do not provision')
    changed=run(['git','diff','--name-only','HEAD']).decode().splitlines()
    changed+=run(['git','ls-files','--others','--exclude-standard']).decode().splitlines()
    results=[]
    for source in sorted(set(changed)):
        if not source.startswith(PREFIX): continue
        relative=source.removeprefix('dot_pi/private_agent/')
        dest=Path.home()/'.pi/agent'/relative
        mapped=run(command+['source-path',str(dest)]).decode().strip()
        if Path(mapped).resolve()!= (ROOT/source).resolve(): raise RuntimeError(f'mapping mismatch: {source}')
        rendered=run(command+['cat',str(dest)])
        live=dest.read_bytes() if dest.is_file() else None
        run(command+['apply','--dry-run','--verbose',str(dest)])
        results.append({'source':source,'destination':str(dest),'renderedSha256':digest(rendered),'liveSha256':digest(live) if live is not None else None,'dryRun':'passed'})
    managed=run(command+['managed']).decode().splitlines()
    if any(x.lstrip('./').startswith('tests/') for x in managed): raise RuntimeError('tests no longer ignored')
    print(json.dumps({'source':str(ROOT),'profile':profile,'configSha256':digest(config.read_bytes()),'removalsSha256':digest(removals),'files':results,'testsIgnored':True,'applied':False},indent=2))

if __name__=='__main__':
    try: main()
    except Exception as error:
        print(str(error),file=sys.stderr); sys.exit(1)
