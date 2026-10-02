"""Real-adapter identity, passive digest disclosure and TUI lifecycle probes.

Callable contract: identity(root, state, env, pane_id, receipts, clients,
open_map, log_digest, publication_outcomes=None). Reuses completed publication.
Lifecycle failures retain fresh native bindings and frames before owned cleanup.
Identity completes independently; the combined integration gate remains T4c.
"""
import json
import os
import re
from pathlib import Path
import proof
from map_publication import publication

UUID = re.compile(r'^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$', re.I)


def verified_metadata(snapshot, records, socket_path):
    """Validate actual bridge records against unique current native terminals."""
    result = []
    for pane in snapshot.get('panes', []):
        terminal = pane.get('terminal_id')
        if not terminal or sum(p.get('terminal_id') == terminal for p in snapshot['panes']) != 1:
            continue
        matches = [r for r in records if r.get('socketPath') == socket_path and r.get('terminalId') == terminal]
        if len(matches) != 1:
            continue
        record = matches[0]
        if record.get('schemaVersion') != 1 or not UUID.fullmatch(record.get('sessionId', '')):
            continue
        pid = record.get('publisherPid')
        if type(pid) is not int or pid <= 0:
            continue
        try:
            os.kill(pid, 0)
        except OSError:
            continue
        native = [pane.get('agent_session')] + [a.get('agent_session') for a in snapshot.get('agents', []) if a.get('pane_id') == pane['pane_id']]
        if any(s is not None and (not isinstance(s, dict) or s.get('agent') != 'pi' or s.get('kind') != 'id' or s.get('value') != record['sessionId']) for s in native):
            continue
        result.append((pane, record))
    return result


def rendered_text(output):
    """Reconstruct Herdr's absolute-position cell updates, not ANSI substrings.

    This bounded fixture decoder supports CUP, erase and CR/LF; unsupported
    cursor-moving sequences fail closed rather than invent a screen.
    """
    text = output.decode('utf-8', errors='replace')
    cells = {}; row = column = 1
    tokens = re.findall(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]|[^\x1b]', text)
    for token in tokens:
        if token.startswith('\x1b]'):
            continue
        if token.startswith('\x1b['):
            command = token[-1]; args = token[2:-1]
            if command in ('H', 'f'):
                values = [int(x or 1) for x in args.split(';')]
                row, column = (values + [1])[:2]
            elif command == 'J' and args in ('2', '3'):
                cells.clear()
            elif command == 'K':
                for key in list(cells):
                    if key[0] == row and (args == '2' or key[1] >= column):
                        del cells[key]
            elif command not in ('m', 'h', 'l', 'J', 'u', 'n', 'c', 't'):
                raise proof.ProofFailure(f'unsupported fixture terminal sequence {token!r}')
            continue
        if token == '\r': column = 1
        elif token == '\n': row += 1
        elif token >= ' ':
            cells[row, column] = token; column += 1
    return '\n'.join(''.join(cells.get((r, c), ' ') for c in range(1, 241)) for r in range(1, 33))


def current_metadata(state, env, pane_id):
    directory = Path(env['XDG_STATE_HOME']) / 'herdr-overview/pi-sessions'
    records = []
    for file in directory.glob('*.json'):
        try:
            records.append(json.loads(file.read_text()))
        except (ValueError, OSError):
            continue
    return next((pair for pair in verified_metadata(proof.snapshot(state), records, state['socket_path']) if pair[0]['pane_id'] == pane_id), None)


from map_frames import wait_frame, contains, canvas


def own_section(frame, pane_subject, marker, sibling_subjects=()):
    """Body follows its own human pane heading in its own workspace box."""
    rows = frame.splitlines()
    own = ''.join(pane_subject.split())
    body = ''.join(marker.split())
    siblings = [''.join(label.split()) for label in sibling_subjects]
    for n, line in enumerate(rows):
        segments = [(m.start()+1, m.end()-1, m.group(1)) for m in re.finditer(r'│([^│]*)│', line)] if '│' in line else [(0,len(line),line)]
        for left,right,heading in segments:
            if ''.join(heading.strip().removeprefix('›').split()) != own:
                continue
            text = ''
            for current in rows[n+1:]:
                section = current[left:right] if '│' in line else current
                clean = ''.join(section.strip().removeprefix('›').split())
                if clean in siblings:
                    break
                text += clean
            if body in text:
                return True
    return False


def wait_native_frame(client, *markers, timeout=20):
    def ready():
        frame = client.frame()
        text = ''.join(frame.replace('│','').split())
        return frame if all(''.join(marker.split()) in text for marker in markers) else None
    return proof.wait_for(ready, 'current native Pi frame: ' + ', '.join(markers), timeout=timeout)


def ready_map(client, open_map):
    open_map()
    # The key legend is emitted by the Node viewer, unlike the native border.
    return wait_frame(client, 'arrows/hjkl select', 'n blocked')


def identity(root, state, env, pane_id, receipts, clients, open_map, log_digest,
             publication_outcomes=None):
    pane = next(p for p in proof.snapshot(state)['panes'] if p['pane_id'] == pane_id)
    outcomes = dict(publication_outcomes) if publication_outcomes is not None else publication(
        root, state, env, pane_id, pane['workspace_id'], receipts)
    pane, metadata = proof.wait_for(lambda: current_metadata(state, env, pane_id),
        'genuine current adapter UUID and unique native terminal', timeout=20)
    proof.json_dump(receipts / 'identity-current.json', {'native': pane, 'adapter': metadata})
    directory = Path(env['HOME']) / '.pi/session-search/digests'
    directory.mkdir(parents=True, exist_ok=True)
    file = directory / (metadata['sessionId'] + '.json')
    wrong = directory / '00000000-0000-0000-0000-000000000000.json'
    wrong.write_text(json.dumps({'schemaVersion': 1, 'generatedAt': '2026-09-29T12:00:00Z', 'body': 'WRONG-SESSION-EXCLUDED'}))
    body = '\n'.join(['SYNTHETIC-DIGEST-BEGIN'] + [f'SYNTHETIC-DIGEST-LINE-{i:03d}' for i in range(65)] + ['ZZZ-END-DIGEST-VERIFIED'])
    generated = '2026-09-30T12:34:56Z'
    file.write_text(json.dumps({'schemaVersion': 1, 'generatedAt': generated, 'body': body}))
    baseline = log_digest(root)
    provider_before = len(proof.provider_requests(root))
    clients[1].close()  # One native PTY geometry; wide disclosure first.
    client = clients[0]
    client.resize(120)
    offset = len(client.output)
    ready_map(client, open_map)
    client.key(b'd')
    wait_frame(client, generated, 'SYNTHETIC-DIGEST-BEGIN')
    if current_metadata(state,env,pane_id)[1]['sessionId'] != metadata['sessionId']:
        raise proof.ProofFailure('digest source is not current native adapter UUID')
    for _ in range(75):
        client.key(b'j')
    if not contains(client.frame(), 'ZZZ-END-DIGEST-VERIFIED'):
        raise proof.ProofFailure('current terminal frame does not show complete digest end marker')
    (receipts / 'digest-end-frame.txt').write_text(client.frame())
    if b'WRONG-SESSION-EXCLUDED' in client.output[offset:]:
        raise proof.ProofFailure('wrong-session digest attached to current pane')
    client.key(b'\x1b')
    cases = []
    for name, contents in [('missing', None), ('malformed', '{malformed')]:
        if contents is None:
            file.unlink()
        else:
            file.write_text(contents)
        offset = len(client.output)
        client.key(b'r'); client.key(b'd')
        frame = wait_frame(client, 'Unavailable')
        if current_metadata(state,env,pane_id)[1]['sessionId'] != metadata['sessionId']:
            raise proof.ProofFailure(f'{name} digest lost current native adapter UUID metadata')
        (receipts / f'digest-{name}-frame.txt').write_text(frame)
        if 'WRONG-SESSION-EXCLUDED' in frame or 'ZZZ-END-DIGEST-VERIFIED' in frame:
            raise proof.ProofFailure(f'{name} digest leaked wrong or previous body')
        client.key(b'\x1b')
        cases.append(name)
    client.key(b'q')
    file.write_text(json.dumps({'schemaVersion': 1, 'generatedAt': generated, 'body': body}))
    client.resize(40)
    ready_map(client, open_map); client.key(b'd')
    wait_frame(client, 'SYNTHETIC-DIGEST-BEGIN')
    for _ in range(16):
        client.key(b'jjjjj')
    (receipts / 'digest-narrow-end-frame.txt').write_text(wait_frame(client, 'ZZZ-END-DIGEST-VERIFIED'))
    client.key(b'q'); client.resize(180)
    if log_digest(root) != baseline or len(proof.provider_requests(root)) != provider_before:
        raise proof.ProofFailure('digest read/scroll/refresh generated backend calls')
    proof.json_dump(receipts / 'identity-digest.json', {'session_id': metadata['sessionId'],
        'terminal_id': pane['terminal_id'], 'generated_at': generated, 'end_marker': 'ZZZ-END-DIGEST-VERIFIED',
        'unavailable_cases': cases, 'excluded': 'WRONG-SESSION-EXCLUDED', 'backend_before': baseline,
        'backend_after': log_digest(root), 'provider_before': provider_before,
        'provider_after': len(proof.provider_requests(root))})
    outcomes.update(verified_current_adapter_identity=True, complete_dated_digest_scroll=True,
        wrong_session_missing_malformed_excluded=True, digest_view_passive=True)
    outcomes.update(disclosure(root, state, env, pane_id, receipts, client, open_map, log_digest))
    outcomes.update(lifecycle(root, state, env, pane_id, receipts, client, open_map, log_digest))
    try:
        outcomes.update(native_identity(root, state, env, pane_id, receipts, client, open_map, log_digest))
    except Exception:
        (receipts / 'native-identity-failure-frame.txt').write_text(client.frame())
        proof.json_dump(receipts / 'native-identity-failure.json', {'native': proof.snapshot(state),
            'plugin': proof.plugin_state(root), 'bridge': current_metadata(state, env, pane_id)})
        raise
    return outcomes


def lifecycle(root, state, env, pane_id, receipts, client, open_map, log_digest):
    """Drive real Pi TUI commands, retaining fresh bridge and popup observations."""
    def bound():
        return current_metadata(state, env, pane_id)
    old_pane, old = proof.wait_for(bound, 'initial lifecycle bridge')
    directory = Path(env['HOME']) / '.pi/session-search/digests'
    def digest(record, marker):
        (directory / (record['sessionId'] + '.json')).write_text(json.dumps({
            'schemaVersion': 1, 'generatedAt': '2026-10-01T01:02:03Z', 'body': marker}))
    digest(old, 'OLD-LIFECYCLE-DIGEST')
    baseline = log_digest(root)
    provider_before = len(proof.provider_requests(root))
    def command(text):
        # Paste is atomic at the Pi editor; clear only after the preceding
        # command's actual completion has been observed.
        client.key(b'\x15' + b'\x1b[200~' + text.encode() + b'\x1b[201~')
        client.key(b'\r')
    command('/new')
    wait_native_frame(client, 'New session started', 'scripted-model')
    new_pane, new = proof.wait_for(lambda: (lambda pair: pair if pair and pair[1]['sessionId'] != old['sessionId'] else None)(bound()),
        'real TUI new_session distinct adapter UUID', timeout=30)
    digest(new, 'NEW-LIFECYCLE-DIGEST')
    command('/name Synthetic stable lifecycle subject')
    try:
        wait_native_frame(client, 'Session name set: Synthetic stable lifecycle subject', 'scripted-model')
        new_pane, new = proof.wait_for(lambda: (lambda pair: pair if pair and pair[1].get('sessionName') == 'Synthetic stable lifecycle subject' else None)(bound()),
            'real TUI stable session name', timeout=30)
    except proof.ProofFailure:
        (receipts / 'stable-name-failure-frame.txt').write_text(client.frame())
        proof.json_dump(receipts / 'stable-name-failure.json', {'old': old, 'new': new,
            'current': bound(), 'native': proof.snapshot(state), 'command': '/name Synthetic stable lifecycle subject'})
        raise
    generation = new['generation']
    command('/reload')
    reloaded_pane, reloaded = proof.wait_for(lambda: (lambda pair: pair if pair and pair[1]['generation'] != generation else None)(bound()),
        'real TUI reload fresh bridge generation', timeout=30)
    if reloaded['sessionId'] != new['sessionId']:
        raise proof.ProofFailure('reload changed current session UUID')
    wait_native_frame(client, 'Reloaded', 'scripted-model')
    ready_map(client, open_map)
    client.key(b'd')
    frame = wait_frame(client, 'NEW-LIFECYCLE-DIGEST')
    (receipts / 'replacement-reload-frame.txt').write_text(frame)
    if 'NEW-LIFECYCLE-DIGEST' not in frame or 'OLD-LIFECYCLE-DIGEST' in frame:
        raise proof.ProofFailure('replacement/reload popup attached wrong digest')
    client.key(b'q')
    if log_digest(root) != baseline or len(proof.provider_requests(root)) != provider_before:
        raise proof.ProofFailure('lifecycle commands/view generated model or recap calls')
    proof.json_dump(receipts / 'identity-lifecycle.json', {'old': old, 'new': new,
        'reloaded': reloaded, 'native': reloaded_pane, 'backend_before': baseline,
        'backend_after': log_digest(root), 'provider_before': provider_before,
        'provider_after': len(proof.provider_requests(root))})
    if new['generation'] == old['generation'] or new_pane['terminal_id'] != old_pane['terminal_id']:
        raise proof.ProofFailure('replacement did not replace generation on same terminal')
    if reloaded_pane.get('label') != 'Synthetic stable lifecycle subject':
        raise proof.ProofFailure('name did not automatically update native pane')
    tab = next(t for t in proof.snapshot(state)['tabs'] if t['tab_id'] == reloaded_pane['tab_id'])
    if tab.get('label') != 'Synthetic stable lifecycle subject':
        raise proof.ProofFailure('name did not automatically update native tab')
    return {'real_session_replacement_reload': True}


def disclosure(root, state, env, pane_id, receipts, client, open_map, log_digest):
    published = json.loads((receipts / 'publication.json').read_text())
    baseline = log_digest(root)
    provider_before = len(proof.provider_requests(root))
    frames = []
    for width in (180, 40):
        client.resize(width)
        ready_map(client, open_map)
        client.key(b'\r')
        first = wait_frame(client, 'Latest good recap')
        seen = first
        current = [first]
        for _ in range(65):
            client.key(b'jjjjj')
            frame = client.frame()
            current.append(frame)
            seen += '\n' + frame
            if contains(frame, 'ZZZ-END-PROMPT-VERIFIED'):
                break
        for marker in ('SYNTHETIC-RECAP-BEGIN', 'ZZZ-END-RECAP-VERIFIED',
                       'Newer attempt failed', 'Supplied prompt', 'ZZZ-END-PROMPT-VERIFIED'):
            if not any(contains(frame,marker) for frame in current):
                raise proof.ProofFailure(f'{width}-column disclosure missing {marker}')
        # Narrow wrapping can split dates; remove only native border/spacing
        # for date comparison, never accept an old ANSI stream.
        (receipts / f'full-disclosure-{width}-frames.txt').write_text(seen)
        compact = ''.join(seen.replace('│', '').replace('┃', '').split())
        for date in (published['good']['published_at'], published['failed']['created_at']):
            if date not in seen and ''.join(date.split()) not in compact:
                raise proof.ProofFailure(f'{width}-column disclosure missing date {date}')
        file = receipts / f'full-disclosure-{width}.json'
        proof.json_dump(file, {'pane_id': pane_id, 'frames': current,
            'good_record': published['good']['record_id'], 'failed_record': published['failed']['record_id']})
        frames.append(str(file))
        client.key(b'q')
    if baseline != log_digest(root) or len(proof.provider_requests(root)) != provider_before:
        raise proof.ProofFailure('recap/prompt disclosure generated backend calls')
    proof.json_dump(receipts / 'disclosure-passive.json', {'backend_before': baseline,
        'backend_after': log_digest(root), 'provider_before': provider_before,
        'provider_after': len(proof.provider_requests(root))})
    client.resize(180)
    return {'wide_narrow_full_dated_last_good_failure_prompt': True}


def native_identity(root, state, env, pane_id, receipts, client, open_map, log_digest):
    """Native naming/membership, unique rekey and actual reader rejection paths."""
    def reconcile():
        proof.api_request(state, 'plugin.action.invoke', {'action_id': 'overview.refresh_names'})
        ids = {p['pane_id'] for p in proof.snapshot(state)['panes']}
        proof.wait_for(lambda: set(model()['panes']) == ids, 'passive current native membership')
    def model():
        return proof.plugin_state(root)['model']
    def labels():
        snap = proof.snapshot(state)
        return {kind: {item[kind + '_id']: item.get('label') for item in snap[kind + 's']}
                for kind in ('pane', 'tab')}
    def named(kind, id, expected):
        return proof.wait_for(lambda: (lambda s: s if s[kind].get(id) == expected else None)(labels()),
            f'native {kind} {id} = {expected}', timeout=20)
    original, record = current_metadata(state, env, pane_id)
    # Report the genuine live SDK UUID through Herdr's supported public API.
    baseline_native = log_digest(root)
    requests_native = len(proof.provider_requests(root))
    report_sequence = 0
    def report(value):
        nonlocal report_sequence
        report_sequence += 1
        proof.api_request(state, 'pane.report_agent_session', {'pane_id': pane_id,
            'source': 'herdr:pi', 'agent': 'pi', 'agent_session_id': value,
            'seq': report_sequence, 'session_start_source': 'resume'})
        reconcile()
    directory = Path(env['HOME']) / '.pi/session-search/digests'
    (directory / (record['sessionId'] + '.json')).write_text(json.dumps({
        'schemaVersion': 1, 'generatedAt': '2026-10-01T01:02:03Z', 'body': 'TYPED-NATIVE-DIGEST-END'}))
    report(record['sessionId'])
    typed = proof.snapshot(state)
    typed_pane = next(p for p in typed['panes'] if p['pane_id'] == pane_id)
    if typed_pane.get('agent_session', {}).get('value') != record['sessionId']:
        raise proof.ProofFailure('public native report did not store genuine UUID')
    ready_map(client, open_map); client.key(b'd')
    frame = wait_frame(client, '2026-10-01T01:02:03Z', 'TYPED-NATIVE-DIGEST-END')
    (receipts / 'typed-native-matching.txt').write_text(frame)
    client.key(b'q')
    report('00000000-0000-0000-0000-000000000000')
    proof.wait_for(lambda: model()['panes'][pane_id].get('piSession') is None, 'typed conflict rejects bridge')
    ready_map(client, open_map); client.key(b'd')
    frame = wait_frame(client, 'Unavailable')
    if 'TYPED-NATIVE-DIGEST-END' in frame:
        raise proof.ProofFailure('typed conflict leaked previous digest')
    (receipts / 'typed-native-conflicting.txt').write_text(frame)
    client.key(b'f')
    proof.wait_for(lambda: proof.snapshot(state)['focused_pane_id'] == pane_id, 'conflicting identity preserves native focus')
    report(record['sessionId'])
    proof.json_dump(receipts / 'typed-native.json', {'session_id': record['sessionId'], 'snapshot': typed,
        'backend_before': baseline_native, 'backend_after': log_digest(root),
        'provider_before': requests_native, 'provider_after': len(proof.provider_requests(root))})
    if baseline_native != log_digest(root) or requests_native != len(proof.provider_requests(root)):
        raise proof.ProofFailure('typed native disclosure generated calls')
    before = labels()
    baseline = log_digest(root)
    requests = len(proof.provider_requests(root))
    # Body-only changes and redraws must not affect any native name.
    directory = Path(env['HOME']) / '.pi/session-search/digests'
    digest_file = directory / (record['sessionId'] + '.json')
    for body in ('BODY-NOT-A-SUBJECT-ONE', 'BODY-NOT-A-SUBJECT-TWO'):
        digest_file.write_text(json.dumps({'schemaVersion': 1, 'generatedAt': '2026-10-01T01:02:03Z', 'body': body}))
        ready_map(client, open_map)
        client.key(b'r')
        client.key(b'd')
        wait_frame(client, body)
        client.key(b'q')
        reconcile()
        if labels() != before:
            raise proof.ProofFailure('digest body/redraw caused naming churn')
    evidence = {'one_pi': before, 'body_only_zero_churn': labels()}
    tab_id = original['tab_id']
    # Manual edits win both stable metadata refresh and explicit redraw.
    for kind, id, label in (('pane', pane_id, 'OWNER PANE'), ('tab', tab_id, 'OWNER TAB')):
        proof.herdr_cmd(state, env, kind, 'rename', id, label)
    reconcile()
    named('pane', pane_id, 'OWNER PANE'); named('tab', tab_id, 'OWNER TAB')
    ready_map(client, open_map); client.key(b'r'); client.key(b'q')
    named('pane', pane_id, 'OWNER PANE'); named('tab', tab_id, 'OWNER TAB')
    for subject in ('Synthetic manual boundary subject', record['sessionName']):
        client.key(b'\x15\x1b[200~' + ('/name ' + subject).encode() + b'\x1b[201~')
        client.key(b'\r')
        wait_native_frame(client, 'Session name set: ' + subject)
        proof.wait_for(lambda: (current_metadata(state, env, pane_id) or (None, {}))[1].get('sessionName') == subject,
            'real manual-boundary session metadata')
        reconcile()
        named('pane', pane_id, 'OWNER PANE'); named('tab', tab_id, 'OWNER TAB')
    evidence['manual_wins'] = labels()
    for kind, id in (('pane', pane_id), ('tab', tab_id)):
        proof.invoke_auto_name(state, kind, id)
    named('pane', pane_id, record['sessionName']); named('tab', tab_id, record['sessionName'])
    # Real shell foreground/native subjects; never claim shell is a Pi UUID.
    workdir = root / 'generic-native-work'; workdir.mkdir()
    proof.herdr_cmd(state, env, 'pane', 'split', pane_id, '--direction', 'right', '--cwd', str(workdir), '--no-focus')
    snap = proof.snapshot(state)
    shell = next(p for p in snap['panes'] if p['tab_id'] == tab_id and p['pane_id'] != pane_id)
    reconcile()
    shell_subject = proof.wait_for(lambda: model()['panes'].get(shell['pane_id'], {}).get('subject'), 'generic native shell subject')
    if model()['panes'][shell['pane_id']].get('piSession'):
        raise proof.ProofFailure('generic shell attached Pi session')
    # Use actual terminal OSC to supply a short native subject for two cards.
    proof.herdr_cmd(state, env, 'pane', 'run', shell['pane_id'], "printf '\\033]0;Native Shell Subject\\007'")
    proof.wait_for(lambda: 'Native Shell Subject' in proof.pane_text(state, env, shell['pane_id'], lines=5)
        or next(p for p in proof.snapshot(state)['panes'] if p['pane_id'] == shell['pane_id']).get('terminal_title') == 'Native Shell Subject', 'native OSC subject')
    reconcile()
    named('pane', shell['pane_id'], 'Native Shell Subject')
    named('tab', tab_id, record['sessionName'] + ' + Native Shell Subject')
    evidence['two_mixed'] = labels()
    proof.herdr_cmd(state, env, 'pane', 'split', shell['pane_id'], '--direction', 'down', '--cwd', str(workdir), '--no-focus')
    reconcile()
    named('tab', tab_id, record['sessionName'] + ' + 2 more')
    evidence['large_mixed'] = labels()
    # Generic single-pane tab, then native membership move/rekey of real Pi.
    proof.herdr_cmd(state, env, 'tab', 'create', '--workspace', original['workspace_id'], '--cwd', str(workdir), '--no-focus')
    reconcile()
    generic = next(t for t in proof.snapshot(state)['tabs'] if t['tab_id'] != tab_id)
    generic_pane = next(p for p in proof.snapshot(state)['panes'] if p['tab_id'] == generic['tab_id'])
    generic_subject = proof.wait_for(lambda: model()['panes'].get(generic_pane['pane_id'], {}).get('subject'), 'generic single subject')
    named('tab', generic['tab_id'], generic_subject)
    evidence['generic_single'] = labels()
    proof.herdr_cmd(state, env, 'workspace', 'create', '--cwd', str(workdir), '--label', 'SYNTHETIC-MOVE-TARGET')
    target = next(w for w in proof.snapshot(state)['workspaces'] if w['workspace_id'] != original['workspace_id'])
    output = proof.herdr_cmd(state, env, 'pane', 'move', pane_id, '--new-tab', '--workspace', target['workspace_id'], '--no-focus')
    moved = json.loads(output.stdout)['result']['move_result']['pane']
    moved_id = moved['pane_id']
    if moved_id == pane_id or moved['terminal_id'] != original['terminal_id']:
        raise proof.ProofFailure('native move did not uniquely rekey same terminal')
    reconcile()
    proof.wait_for(lambda: (model()['panes'].get(moved_id, {}).get('piSession') or {}).get('sessionId') == record['sessionId'], 'current bridge follows native rekey')
    if pane_id in model()['panes']:
        raise proof.ProofFailure('old pane persisted after native rekey')
    named('pane', moved_id, record['sessionName']); named('tab', moved['tab_id'], record['sessionName'])
    named('tab', tab_id, 'Native Shell Subject + ' + model()['panes'][next(p['pane_id'] for p in proof.snapshot(state)['panes'] if p['tab_id'] == tab_id and p['pane_id'] != shell['pane_id'])]['subject'])
    evidence['move'] = {'old': original, 'new': moved, 'model': model(), 'labels': labels()}
    # Focus selected moved pane through public viewer keys, not a fake context.
    proof.api_request(state, 'pane.focus', {'pane_id': moved_id})
    ready_map(client, open_map); client.key(b'd')
    wait_frame(client, 'BODY-NOT-A-SUBJECT-TWO')
    client.key(b'f')
    proof.wait_for(lambda: proof.snapshot(state)['focused_pane_id'] == moved_id, 'exact moved terminal focus')
    # Actual reader negative paths: retain the genuine publisher record and
    # corrupt only owned files temporarily. No invented accepted identity.
    bridge_dir = Path(env['XDG_STATE_HOME']) / 'herdr-overview/pi-sessions'
    bridge = next(p for p in bridge_dir.glob('*.json') if json.loads(p.read_text()).get('sessionId') == record['sessionId'])
    original_bytes = bridge.read_bytes()
    cases = []
    for case in ('wrong-socket', 'unmatched-terminal', 'dead-publisher', 'duplicate', 'old-generation'):
        duplicate = bridge_dir / 'negative-duplicate.json'
        bad = json.loads(original_bytes)
        if case == 'wrong-socket': bad['socketPath'] += '.wrong'
        elif case == 'unmatched-terminal': bad['terminalId'] += '.wrong'
        elif case == 'dead-publisher': bad['publisherPid'] = 2147483647
        elif case == 'duplicate': duplicate.write_bytes(original_bytes)
        elif case == 'old-generation':
            # A retained old lifecycle record alongside the current one cannot
            # override the unique current binding: both are rejected as ambiguous.
            bad_old = json.loads((receipts / 'identity-lifecycle.json').read_text())['old']
            duplicate.write_text(json.dumps(bad_old))
        bridge.write_text(json.dumps(bad))
        try:
            reconcile()
            proof.wait_for(lambda: model()['panes'][moved_id].get('piSession') is None,
                f'{case} actual reader rejection', timeout=20)
            ready_map(client, open_map); client.key(b'd')
            frame = wait_frame(client, 'Unavailable')
            if 'BODY-NOT-A-SUBJECT-TWO' in frame:
                raise proof.ProofFailure(f'{case} disclosed prior body')
            (receipts / f'identity-negative-{case}.txt').write_text(frame)
            client.key(b'q')
            cases.append(case)
        finally:
            duplicate.unlink(missing_ok=True)
            bridge.write_bytes(original_bytes)
            reconcile()
    if log_digest(root) != baseline or len(proof.provider_requests(root)) != requests:
        raise proof.ProofFailure('native naming/membership/view commands generated backend calls')
    proof.json_dump(receipts / 'identity-native.json', {'evidence': evidence, 'negative_cases': cases,
        'backend_before': baseline, 'backend_after': log_digest(root), 'provider_requests': requests})
    # One explicit user model turn verifies current publication attribution after
    # rekey. It is separate from all passive/name counter baselines above.
    stable_labels = labels()
    backend = root / 'full-recap-backend.py'
    source = (proof.ROOT / 'tests/herdr-overview/fake_recap_backend.py').read_text()
    source = source.replace('"Recent work is complete. Present state: ready for the next step.\\n"', repr('RECAP BODY CHANGED NOT A SUBJECT\n'))
    backend.write_text(source)
    prompt = 'SYNTHETIC POST MOVE CURRENT SESSION END-POST-MOVE-PROMPT'
    proof.herdr_cmd(state, env, 'agent', 'prompt', 'synthetic-map-pi', prompt, timeout=20)
    data = root / 'data/session-recap'
    def current_publication():
        good, _ = proof.read_latest_pi_record(data, moved_id)
        return good if good and good.get('source_id') == record['sessionId'] else None
    good = proof.wait_for(current_publication, 'real moved current-session publication', timeout=40)
    if good.get('pane_id') != moved_id or good.get('workspace_id') != target['workspace_id']:
        raise proof.ProofFailure('current publication attributed to old/wrong native membership')
    proof.wait_for(lambda: (proof.read_pi_prompt(data, moved_id) or {}).get('text') == prompt,
        'real moved current supplied prompt')
    proof.wait_for(lambda: good['record_id'] in proof.plugin_state(root).get('recapCoordinator', {}).get('processedRecordIds', []),
        'explicit publication coordinator completion', timeout=20)
    reconcile()
    # processedRecordIds is persisted mid-reconcile, before the policy probe
    # finishes. Observe the final model write and released owned coordinator
    # lock before measuring passive viewing; keep the real 30s deadline alive.
    lock = proof.overview_state_path(root).parent / '.overview.lock'
    proof.wait_for(lambda: not lock.exists() and
        (model()['panes'].get(moved_id, {}).get('recap', {}).get('latest') or {}).get('record_id') == good['record_id'],
        'completed explicit publication final model and released lock', timeout=20)
    if labels() != stable_labels:
        raise proof.ProofFailure('recap body update caused native name churn')
    after_publication = log_digest(root)
    after_requests = len(proof.provider_requests(root))
    ready_map(client, open_map); client.key(b'\r')
    wait_frame(client, 'RECAP BODY CHANGED NOT A SUBJECT')
    client.key(b'q')
    if log_digest(root) != after_publication or len(proof.provider_requests(root)) != after_requests:
        raise proof.ProofFailure('post-move viewer generated backend work')
    proof.json_dump(receipts / 'identity-post-move-publication.json', {'record': good,
        'prompt': proof.read_pi_prompt(data, moved_id), 'labels_before': stable_labels, 'labels_after': labels(),
        'explicit_provider_calls_before': requests, 'explicit_provider_calls_after': after_requests,
        'viewer_backend_before': after_publication, 'viewer_backend_after': log_digest(root)})
    # Multi-pane disclosure uses two genuinely published, distinct sources.
    proof.herdr_cmd(state, env, 'pane', 'split', moved_id, '--direction', 'right', '--cwd', str(workdir), '--no-focus')
    companion = next(p for p in proof.snapshot(state)['panes'] if p['tab_id'] == moved['tab_id'] and p['pane_id'] != moved_id)
    reconcile()
    if model()['panes'][companion['pane_id']]['recap'].get('latest') is not None:
        raise proof.ProofFailure('new generic pane borrowed Pi recap')
    backend.write_text(source.replace(repr('RECAP BODY CHANGED NOT A SUBJECT\n'), repr('SHELL OWN RECAP END-SHELL-RECAP\n')))
    manual_id = proof.cli_recap(Path(env['HOME']), env, 'create', '--kind', 'single', '--source-id', companion['pane_id'],
        '--label', 'Synthetic manual source', stdin='Synthetic shell-only work.\n').stdout.strip()
    reconcile()
    proof.wait_for(lambda: (model()['panes'][companion['pane_id']]['recap'].get('latest') or {}).get('record_id') == manual_id,
        'manual shell own recap association')
    if model()['panes'][moved_id]['recap']['latest']['record_id'] != good['record_id']:
        raise proof.ProofFailure('manual shell recap replaced Pi own record')
    own_baseline = log_digest(root); own_requests = len(proof.provider_requests(root))
    proof.api_request(state, 'pane.focus', {'pane_id': moved_id})
    ready_map(client, open_map); client.key(b'\r')
    own_frames = [wait_frame(client, 'RECAP BODY CHANGED NOT A SUBJECT')]
    own_label = model()['panes'][moved_id]['label']
    peer_label = model()['panes'][companion['pane_id']]['label']
    if not own_section(own_frames[0], own_label, 'RECAP BODY CHANGED NOT A SUBJECT', [peer_label]):
        raise proof.ProofFailure('Pi recap body not under own visible pane header')
    for _ in range(6):
        frame = client.frame(); own_frames.append(frame)
        if own_section(frame, peer_label, 'SHELL OWN RECAP END-SHELL-RECAP', [own_label]):
            break
        client.key(b'jjjjj')
    if not any(own_section(frame, peer_label, 'SHELL OWN RECAP END-SHELL-RECAP', [own_label]) for frame in own_frames):
        raise proof.ProofFailure('multi-pane disclosure omitted shell own human heading/recap')
    client.key(b'q')
    if own_baseline != log_digest(root) or own_requests != len(proof.provider_requests(root)):
        raise proof.ProofFailure('multi-pane reading generated backend work')
    proof.json_dump(receipts / 'identity-own-pane-disclosure.json', {'pi_pane': moved_id,
        'pi_record': good['record_id'], 'shell_pane': companion['pane_id'], 'shell_record': manual_id,
        'model': model(), 'frames': own_frames, 'backend_before': own_baseline, 'backend_after': log_digest(root)})
    return {'native_manual_automatic_membership_names': True, 'body_redraw_zero_name_churn': True,
        'native_unique_terminal_rekey_focus': True, 'actual_reader_old_wrong_duplicate_dead_rejected': True,
        'multi_pane_own_recap_attribution': True, 'current_rekey_publication_attribution': True}
