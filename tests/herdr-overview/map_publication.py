"""Scripted real-Pi publication assertions for the owned popup fixture."""
import json
import shlex
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
import proof


def publication(root, state, env, pane_id, workspace_id, receipts, full_disclosure=False):
    summary = proof.SUCCESS_SUMMARY
    failed_prompt = 'SYNTHETIC failed later attempt'
    if full_disclosure:
        summary = '\n'.join(['SYNTHETIC-RECAP-BEGIN'] + [f'RECAP-LINE-{i:03d}' for i in range(65)] + ['ZZZ-END-RECAP-VERIFIED'])
        failed_prompt = '\n'.join(['SYNTHETIC failed later attempt'] + [f'PROMPT-LINE-{i:03d}' for i in range(40)] + ['ZZZ-END-PROMPT-VERIFIED'])
        # Private scripted backend copy; every record still goes through the
        # real prepare/publish path. The shared default backend stays untouched.
        backend = root / 'full-recap-backend.py'
        source = (proof.ROOT / 'tests/herdr-overview/fake_recap_backend.py').read_text()
        source = source.replace('"Recent work is complete. Present state: ready for the next step.\\n"', repr(summary + '\n'))
        backend.write_text(source)
        config = Path(env['XDG_CONFIG_HOME']) / 'session-recap/config.toml'
        config.write_text(config.read_text().replace(str(proof.ROOT / 'tests/herdr-overview/fake_recap_backend.py'), str(backend)))
    provider = proof.ensure_scripted_provider(root, state, env)
    real_pi = shutil.which('pi')
    if not real_pi:
        raise proof.ProofBlocked('Pi executable unavailable')
    extension = root / 'scripted-pi-provider.mjs'
    proof.make_pi_provider_extension(extension)
    proof.write_exec(root / 'bin/pi', '#!/bin/sh\nset -eu\n'
        'IFS= read -r HERDR_OVERVIEW_TEST_PROVIDER_URL < "$HERDR_OVERVIEW_TEST_PROVIDER_URL_FILE"\n'
        'export HERDR_OVERVIEW_TEST_PROVIDER_URL\n'
        f'exec {shlex.quote(real_pi)} "$@"\n')
    Path(env['HERDR_OVERVIEW_TEST_PROVIDER_URL_FILE']).write_text(provider['url'] + '\n')
    Path(env['HERDR_OVERVIEW_PI_REPLY']).write_text(proof.scripted_pi_reply() + '\n')
    recap_index = proof.install_native_recap(root, env, backend if full_disclosure else None)
    # The recap extension publishes only from an interactive TUI session, so the
    # pane runs real Pi directly; agent.start would force RPC mode.
    command = [str(root / 'bin/pi'), '--provider', 'herdr-proof-scripted', '--model', 'scripted-model',
        '--extension', str(proof.ROOT / 'dot_pi/private_agent/extensions/herdr-overview/index.ts'),
        '--extension', str(extension), '--extension', str(recap_index), '--no-skills', '--no-prompt-templates',
        '--no-themes', '--no-context-files', '--no-tools', '--offline', '--session-dir', str(root / 'pi-sessions')]
    launch = 'env ' + ' '.join(shlex.quote(f'{key}={value}') for key, value in env.items()) + ' ' + shlex.join(command)
    proof.herdr_cmd(state, env, 'pane', 'run', pane_id, launch)
    proof.wait_for(lambda: 'Pi can explain its own features' in proof.pane_text(state, env, pane_id, fmt='text', lines=100),
        'interactive Pi to initialize in the native pane', timeout=30)
    data = root / 'data/session-recap'
    prompt = 'Proof request SYNTHETIC-MAP-PROMPT inspect synthetic parser END-PROMPT'
    def send(text):
        proof.herdr_cmd(state, env, 'pane', 'send-text', pane_id, text)
        proof.herdr_cmd(state, env, 'pane', 'send-keys', pane_id, 'enter')
    send(prompt)
    try:
        proof.wait_for(lambda: proof.provider_requests(root), 'scripted provider request', timeout=60)
        current = proof.wait_for(lambda: proof.read_pi_prompt(data, pane_id), 'working prompt')
        if current.get('text') != prompt or current.get('working') is not True:
            raise proof.ProofFailure('working prompt was not separately published')
        Path(provider['release_file']).touch()
        proof.wait_for(lambda: (proof.read_pi_prompt(data, pane_id) or {}).get('working') is False,
            'interactive Pi response settlement', timeout=140)
        good, attempt = proof.wait_for(lambda: (lambda pair: pair if pair[0] and pair[0].get('status') == 'published' else None)(
            proof.read_latest_pi_record(data, pane_id)), 'settled publication', timeout=40)
        if good.get('summary') != summary + '\nObserved request: ' + prompt or good.get('workspace_id') != workspace_id:
            raise proof.ProofFailure('publication summary/workspace attribution mismatch')
        saved = proof.wait_for(lambda: (proof.plugin_state(root).get('recapCoordinator', {}).get('workspaceDeadlines', {}).get(workspace_id)),
            'publication quiet deadline')
        due = datetime.fromisoformat(saved.replace('Z', '+00:00')).timestamp()
        published = datetime.fromisoformat(good['published_at'].replace('Z', '+00:00')).timestamp()
        if abs(due - published - 30) > .002:
            raise proof.ProofFailure('quiet deadline is not publication plus 30 seconds')
        Path(env['FAKE_RECAP_MODE_FILE']).write_text('blank\n')
        send(failed_prompt.replace('\n', ' '))
        later, failed = proof.wait_for(lambda: (lambda pair: pair if pair[1] and pair[1].get('status') == 'failed' else None)(
            proof.read_latest_pi_record(data, pane_id)), 'failed later publication', timeout=40)
        # The recap extension may retry a failed attempt; keep the backend failing
        # until record creation is quiet so the newer failure stays the last attempt.
        def quiet(seen={'count': -1, 'since': 0.0}):
            count = len(list(data.glob('records/*/*.json')))
            if count != seen['count']:
                seen.update(count=count, since=time.monotonic())
            return time.monotonic() - seen['since'] > 6
        proof.wait_for(quiet, 'recap retries to finish', timeout=40)
        later, failed = proof.read_latest_pi_record(data, pane_id)
        Path(env['FAKE_RECAP_MODE_FILE']).write_text('success\n')
        if later['record_id'] != good['record_id']:
            raise proof.ProofFailure('failed publication replaced latest good')
        if proof.plugin_state(root)['recapCoordinator']['workspaceDeadlines'][workspace_id] != saved:
            raise proof.ProofFailure('failure reset quiet deadline')
        time.sleep(max(0, due - time.time() + .8))
        def grouped():
            workspace = proof.latest_entry(data, 'workspace', workspace_id)
            session = proof.latest_entry(data, 'herdr-session', 'active')
            if not workspace or not session:
                return None
            return (proof.find_record(data, workspace['latest_success_id'])[1],
                    proof.find_record(data, session['latest_success_id'])[1])
        workspace, session = proof.wait_for(grouped, 'workspace and session groups', timeout=45)
        # The recap extension may publish again after the failed attempt; the group
        # must name the pane's newest published Pi recap, never the failed attempt.
        records = [proof.read_json(p) for p in sorted(data.glob('records/*/*.json'))]
        pane_good = [r for r in records if r.get('source_kind') == 'pi' and r.get('status') == 'published'
            and r.get('annotations', {}).get('herdr', {}).get('pane_id') == pane_id]
        newest = max(pane_good, key=lambda r: r.get('published_at', ''))
        if failed['record_id'] in workspace.get('member_record_ids', []) \
                or workspace.get('member_record_ids') != [newest['record_id']] \
                or workspace['record_id'] not in session.get('member_record_ids', []):
            proof.json_dump(receipts / 'group-failure-records.json', records)
            raise proof.ProofFailure(f"group member record identity lost: newest={newest['record_id']} "
                f"workspace={workspace.get('member_record_ids')} session={session.get('member_record_ids')}")
        proof.json_dump(receipts / 'publication.json', {'good': good, 'failed': failed,
            'workspace': workspace, 'session': session, 'working_prompt': current,
            'current_prompt': failed_prompt})
        return {'scripted_pi_publication': True, 'publication_plus_exact_30s_deadline': True, 'last_good_preserved': True,
            'failure_deadline_unchanged': True, 'group_member_ids_preserved': True}
    finally:
        proof.json_dump(receipts / 'provider-requests.json', {'requests': proof.provider_requests(root)})
        try:
            (receipts / 'pi-pane.txt').write_text(proof.pane_text(state, env, pane_id, lines=260))
        except Exception as exc:
            (receipts / 'pi-pane-read-error.txt').write_text(str(exc))
        Path(provider['release_file']).touch()
