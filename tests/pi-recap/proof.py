#!/usr/bin/env python3
"""Source-only recap proof dispatcher. PASS applies only to named observations.

No live apply, provider credentials, owner socket or phone receipt is used.
Public lifecycle cases drive disposable Pi rather than infer outcomes from helper tests.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / 'dot_local/share/session-recap'
RECAP = ROOT / 'dot_pi/private_agent/extensions/recap'
OVERVIEW = ROOT / 'tests/herdr-overview/proof.py'


def execute(name, criteria, argv, timeout=180):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
    try:
        p = subprocess.run([str(x) for x in argv], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=timeout)
        return dict(case=name, criteria=criteria, status='PASS' if p.returncode == 0 else
                    ('BLOCKED' if p.returncode == 2 else 'FAIL'), command=[str(x) for x in argv],
                    exit_code=p.returncode, stdout=p.stdout, stderr=p.stderr)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return dict(case=name, criteria=criteria, status='BLOCKED', reason=str(exc))


def profiles():
    # Explicit empty config: no read-source-state hook and no host config replacement.
    with tempfile.TemporaryDirectory(prefix='recap-profile-') as temporary:
        base = Path(temporary)
        config = base / 'chezmoi.json'
        expected = {'.pi/agent/extensions/recap/index.ts', '.local/bin/session-recap',
                    '.local/share/session-recap/session_recap.py', '.config/session-recap/config.toml'}
        observations = []
        for profile in ('personal', 'axon-work-computer', 'termux'):
            home = base / profile
            home.mkdir(mode=0o700)
            config.write_text(json.dumps({'data': {'profile': profile}}))
            config.chmod(0o600)
            argv = ['chezmoi', '--config', str(config), '--source', str(ROOT), '--destination', str(home), 'managed']
            p = subprocess.run(argv, text=True, capture_output=True, timeout=60)
            if p.returncode:
                raise RuntimeError(p.stderr)
            paths = set(p.stdout.splitlines())
            present = expected & paths
            assert present == (set() if profile == 'termux' else expected), (profile, present)
            assert not any(x.startswith('tests/') or 'automation-fixture' in x or x.endswith('.test.ts') and '/recap/' in x for x in paths)
            assert not list(home.iterdir()), 'managed must not materialize destinations'
            observations.append({'profile': profile, 'recap_destinations': sorted(present), 'no_apply': True})
        return dict(case='hook-free-profile-mapping', criteria=['AC-4', 'AC-5', 'AC-7'], status='PASS', observations=observations,
                    cleanup='TemporaryDirectory removes only this fixture; native touched-destination previews remain driver-owned')


def overview():
    rows = []
    # macOS's default /var/folders root exceeds sockaddr_un's path limit.
    # Keep the isolated socket path short; TemporaryDirectory remains private.
    with tempfile.TemporaryDirectory(prefix='ro-', dir='/tmp') as temporary:
        base = [sys.executable, OVERVIEW]
        state = ['--state-base', temporary]
        prepared = execute('overview-prepare', ['AC-4'], base + ['herdr-prepare'] + state)
        rows.append(prepared)
        try:
            receipt = json.loads(prepared.get('stdout', '').splitlines()[-1])
            run_id = receipt.get('run_id')
        except (ValueError, IndexError):
            run_id = None
        if run_id:
            try:
                if prepared['status'] == 'PASS':
                    for scenario in ('herdr-wide', 'pi-grouped'):
                        row = execute(scenario, ['AC-4'], base + [scenario, '--run-id', run_id] + state, 300)
                        rows.append(row)
                        if row['status'] != 'PASS':
                            break
            finally:
                rows.append(execute('overview-cleanup', ['AC-4'], base + ['herdr-cleanup', '--run-id', run_id] + state))
        elif prepared['status'] == 'PASS':
            rows.append(dict(case='overview-receipt', status='FAIL', reason='prepare did not provide a run_id'))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('section', choices=['cli', 'backend', 'tui', 'lifecycle', 'overview-isolated', 'profiles'])
    parser.add_argument('--case', help='run one named case from this existing section')
    args = parser.parse_args()
    if args.case and args.section not in ("cli", "backend", "tui", "lifecycle"):
        parser.error("--case supports cli, backend, tui and lifecycle only")
    def execute_case(name, criteria, argv, timeout=180):
        if args.case and args.case != name:
            return None
        return execute(name, criteria, argv, timeout)
    # Filter dispatch, not receipts: unselected processes are never started.
    py = sys.executable
    if args.section == 'cli':
        rows = [execute_case('native-cli-timezone-public', ['UX-timezone'], [py, CLI / 'test_timezone.py']),
                execute_case('retired-pi-commands-rejected-no-mutation-legacy-list-read-public', ['AC-5'],
                        [py, '-c', 'import sys,unittest; sys.path.insert(0, ' + repr(str(CLI)) + '); import test_session_recap; unittest.main(module=test_session_recap, argv=["proof", "SessionRecapCliTests.test_retired_commands_rejected_without_mutation_and_legacy_history_readable"], verbosity=2)']),
                execute_case('generic-cli-public', ['AC-5'], [py, OVERVIEW, 'recap']),
                execute_case('fenced-requests-recursion-safe-record-fields', ['AC-5', 'AC-8', 'AC-11', 'AC-12'],
                        [py, '-m', 'unittest', 'discover', '-s', CLI, '-p', 'test_requests.py', '-v'])]
    elif args.section == 'backend':
        rows = [execute_case('sdk-boundary-backend', ['AC-7'], ['node', '--test', RECAP / 'backend.test.mjs'])]
        rows.append(execute_case('installed-sdk-auth-virtual-provider', ['AC-7', 'AC-8'],
                            [py, ROOT / 'tests/pi-recap/backend.py']))
        rows.append(execute_case('installed-sdk-unfinished-output-safe-retry', ['AC-7', 'AC-8', 'AC-11'],
                            ['env', 'RECAP_PROOF_FINISH=length', py, ROOT / 'tests/pi-recap/backend.py']))
    elif args.section == 'tui':
        rows = [execute_case('unsaved-warning-editor-preservation-public', ['UX-unsaved', 'UX-view', 'UX-editor'], [py, ROOT / 'tests/pi-recap/ux_unsaved.py'], 120),
                execute_case('recap-discovery-running-public', ['UX-discovery', 'UX-running', 'AC-11', 'AC-12'], [py, ROOT / 'tests/pi-recap/discovery.py'], 240),
                execute_case('defaults-quiet-view-current-model-timezone-public', ['UX-defaults', 'UX-view', 'UX-model', 'UX-timezone'], [py, ROOT / 'tests/pi-recap/ux_followup.py'], 240),
                execute_case('history-viewer-phone-wide-width-public', ['AC-3'], [py, ROOT / 'tests/pi-recap/viewer_width.py']),
                execute_case('large-retained-history-public', ['AC-1', 'AC-2', 'AC-3', 'AC-6', 'AC-7', 'AC-10', 'AC-12', 'AC-13'], [py, ROOT / 'tests/pi-recap/history_transport.py'], 240),
                execute_case('empty-cancel-history-public', ['AC-1', 'AC-3'], [py, RECAP / 'tui-smoke.py']),
                execute_case('active-progress-final-cadence-compaction-public', ['AC-2', 'AC-6', 'AC-13'], [py, RECAP / 'automation-pty.py']),
                execute_case('automatic-full-silent-tool-no-new-status-counts-public', ['AC-3', 'AC-6'], ['env', 'RECAP_PROOF_MODE=full', py, RECAP / 'automation-pty.py']),
                *[execute_case('virtual-metadata-gated-native-' + case + '-compaction-public', ['AC-7', 'AC-11', 'AC-13'], [py, ROOT / 'tests/pi-recap/compaction.py', case]) for case in ('manual', 'automatic')]]
    elif args.section == 'lifecycle':
        rows = [*[execute_case('supervised-preflight-' + case + '-public', ['AC-7', 'AC-11', 'AC-12'], [py, ROOT / 'tests/pi-recap/preflight.py', case]) for case in ('switch', 'reload', 'shutdown', 'cancel', 'newer', 'deadline')],
                *[execute_case('virtual-compaction-preflight-'  + case + '-public', ['AC-7', 'AC-11', 'AC-12', 'AC-13'], [py, ROOT / 'tests/pi-recap/compaction.py', 'guard-' + case]) for case in ('switch', 'reload', 'cancel', 'shutdown', 'newer', 'failure-current', 'failure-stale')],
                execute_case('compatible-python-explicit-control-detached-public', ['AC-1', 'AC-5', 'AC-7'], [py, ROOT / 'tests/pi-recap/limits.py', 'python-explicit']),
                execute_case('compatible-python-mise-fallback-control-detached-public', ['AC-1', 'AC-5', 'AC-7'], [py, ROOT / 'tests/pi-recap/limits.py', 'python-fallback']),
                *[execute_case('unfinished-' + stage + '-pending-safe-followup-public', ['AC-1', 'AC-8', 'AC-11'], [py, ROOT / 'tests/pi-recap/limits.py', 'length-' + stage]) for stage in ('final', 'reduction')],
                *[execute_case('selected-small-model-' + case + '-budgets-off-on-public', ['AC-1', 'AC-7', 'AC-8', 'AC-11'], [py, ROOT / 'tests/pi-recap/limits.py', 'budget-' + case]) for case in ('physical-default', 'physical-explicit', 'virtual-default', 'virtual-explicit', 'virtual-preflight', 'refusal')],execute_case('busy-manual-full-input-derived-narrative-public', ['AC-1', 'AC-6', 'AC-11'], [py, ROOT / 'tests/pi-recap/busy.py']),
                execute_case('available-original-ui-generated-unsaved-public', ['AC-1', 'AC-11', 'AC-12'], ['env', 'RECAP_PROOF_UNSAVED=visible', py, ROOT / 'tests/pi-recap/lifecycle.py']),
                execute_case('manual-incremental-first-setup-timeout-history-settings-resume-branches-public', ['AC-1', 'AC-3', 'AC-6', 'AC-7', 'AC-8', 'AC-9', 'AC-10', 'AC-12'], [py, ROOT / 'tests/pi-recap/manual.py']),
                execute_case('gated-cancel-reasoning-privacy-public', ['AC-1', 'AC-7', 'AC-12'], [py, ROOT / 'tests/pi-recap/lifecycle.py']),
                execute_case('buffered-generated-unsaved-cancel-consumption-public', ['AC-1', 'AC-11', 'AC-12'], ['env', 'RECAP_PROOF_UNSAVED=1', py, ROOT / 'tests/pi-recap/lifecycle.py']),
                execute_case('pi-settings-oversized-manual-automatic-recursion-deadline-followup-public', ['AC-1', 'AC-7', 'AC-8', 'AC-11', 'AC-12'], [py, ROOT / 'tests/pi-recap/recursion.py']),
                execute_case('surviving-old-job-new-original-session-supersession-public', ['AC-1', 'AC-7', 'AC-9', 'AC-12'], [py, ROOT / 'tests/pi-recap/supersession.py']),
                execute_case('captured-host-departure-original-resume-public', ['AC-1', 'AC-7', 'AC-9', 'AC-12'], [py, ROOT / 'tests/pi-recap/departure.py']),
                execute_case('coverage-settings-helper-contract', ['AC-9', 'AC-10'], ['node', '--test', RECAP / 'helpers.test.ts']),
                execute_case('runtime-auth-live-error-privacy-public', ['AC-1', 'AC-7', 'AC-8', 'AC-12'], [py, ROOT / 'tests/pi-recap/auth_error.py'])]
    elif args.section == 'overview-isolated':
        rows = overview()
    else:
        try:
            rows = [profiles()]
        except (AssertionError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
            rows = [dict(case='hook-free-profile-mapping', status='FAIL', reason=str(exc))]
    rows = [r for r in rows if r is not None]
    if args.case and not rows:
        rows = [dict(case=args.case, status='FAIL', reason='unknown case in selected section')]
    status = 'FAIL' if any(r['status'] == 'FAIL' for r in rows) else 'BLOCKED' if any(r['status'] == 'BLOCKED' for r in rows) else 'PASS'
    print(json.dumps(dict(section=args.section, status=status, cases=rows), indent=2))
    return {'PASS': 0, 'FAIL': 1, 'BLOCKED': 2}[status]


if __name__ == '__main__':
    raise SystemExit(main())
