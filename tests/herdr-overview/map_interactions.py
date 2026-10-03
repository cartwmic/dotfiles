"""Owned native interaction assertions; all frames are current pyte screens."""
import time
import proof


from map_frames import selected_in_frame as selected_card, canvas, contains, card


def selected_in_frame(frame, target, snapshot):
    return selected_card(frame, target, snapshot)


def native_interactions(root, state, env, receipts, clients, open_map, log_digest):
    baseline = log_digest(root)
    live = proof.snapshot(state)
    workspace = live['workspaces'][-1]
    workdir = root / 'synthetic-work'
    for label in ('SYN-A', 'SYN-B'):
        proof.herdr_cmd(state, env, 'tab', 'create', '--workspace', workspace['workspace_id'],
            '--cwd', str(workdir), '--label', label, '--no-focus')
    proof.api_request(state, 'workspace.rename', {'workspace_id': workspace['workspace_id'], 'label': 'SYN-WS-A'})
    proof.herdr_cmd(state, env, 'workspace', 'create', '--cwd', str(workdir),
        '--label', 'SYN-WS-B')
    live = proof.snapshot(state)
    first = next(p for p in live['panes'] if p['workspace_id'] == workspace['workspace_id'])
    proof.herdr_cmd(state, env, 'pane', 'split', first['pane_id'], '--direction', 'right',
        '--cwd', str(workdir), '--no-focus')
    live = proof.snapshot(state)
    for number, pane in enumerate(live['panes'], 1):
        proof.api_request(state, 'pane.rename', {'pane_id': pane['pane_id'], 'label': f'SYN-PANE-{number}'})
    live = proof.snapshot(state)
    ids = [p['pane_id'] for w in live['workspaces'] for t in live['tabs']
        if t['workspace_id'] == w['workspace_id'] for p in live['panes'] if p['tab_id'] == t['tab_id']]
    proof.json_dump(receipts / 'interaction-native-fixture.json', live)
    client = clients[0]
    if len(live['workspaces']) < 2:
        raise proof.ProofFailure('interaction fixture must contain multiple workspaces')
    # A native singleton popup has one PTY geometry, not an independent
    # viewport per attached client. Concurrent shared behavior was proved
    # above; detach the narrow peer for actual wide layout, then resize.
    clients[1].close()
    client.drain(3)  # Observe native detach before allocating a new popup PTY.
    grid_evidence = []
    for width in (180, 40):
        client.resize(width); client.drain(3); open_map(); client.drain(2)
        frame = client.frame()
        (receipts / f'native-grid-{width}-initial.txt').write_text(frame)
        current_canvas = canvas(frame)
        positions = {name: [(row, line.index(name)) for row, line in enumerate(current_canvas)
                           if name in line] for name in ('SYN-A', 'SYN-B', 'SYN-WS-A', 'SYN-WS-B')}
        # Higher padded cards legitimately put singleton rows below the first
        # viewport. Reach their actual native-order selection, then assert the
        # whole adjacent card pair, not the earlier raw headings alone.
        singleton = next(p['pane_id'] for p in live['panes'] if p['tab_id'] == next(t['tab_id'] for t in live['tabs'] if t.get('label') == 'SYN-A'))
        for _ in range(len(ids)):
            if selected_in_frame(client.frame(), singleton, live):
                break
            client.key(b']')
        else:
            raise proof.ProofFailure('singleton card row unreachable')
        pair = canvas(client.frame())
        for name in ('SYN-A', 'SYN-B'):
            positions[name] = [(row,line.index(name)) for row,line in enumerate(pair) if name in line]
        (receipts / f'native-grid-{width}-card-pair.txt').write_text(client.frame())
        for name in ('SYN-A', 'SYN-B'):
            for row,col in positions[name]:
                left = pair[row].rfind('│',0,col)
                right = pair[row].find('│',col)
                if left < 0 or right < 0 or not any('┌' in line[left:right+1] and '┐' in line[left:right+1] for line in pair[:row]) or not any('NO AGENT' in line[left:right+1] for line in pair[row:]) or not any('└' in line[left:right+1] and '┘' in line[left:right+1] for line in pair[row:]):
                    raise proof.ProofFailure(f'incomplete adjacent native card {name} at {width}')
        if width < 80:
            for _ in range(len(ids)):
                if contains(client.frame(), 'SYN-WS-B'):
                    break
                client.key(b']')
            else:
                raise proof.ProofFailure('narrow second workspace unreachable in native order')
            (receipts / f'native-grid-{width}-second-workspace.txt').write_text(client.frame())
            positions['SYN-WS-B'] = [(row,line.index('SYN-WS-B')) for row,line in enumerate(canvas(client.frame())) if 'SYN-WS-B' in line]
        if any(not positions[name] for name in positions):
            raise proof.ProofFailure(f'native grid missing labeled card/workspace at {width}: {positions}')
        if not any(a[0] == b[0] and a[1] != b[1]
                   for a in positions['SYN-A'] for b in positions['SYN-B']):
            raise proof.ProofFailure(f'native one-pane tabs do not share a card row at {width}')
        if width == 180 and not any(a[0] == b[0] and a[1] != b[1]
                                    for a in positions['SYN-WS-A'] for b in positions['SYN-WS-B']):
            (receipts / 'native-wide-workspace-layout-counterexample.txt').write_text(frame)
            raise proof.ProofFailure('wide workspaces do not use the approved column layout')
        (receipts / f'native-grid-{width}.txt').write_text(frame)
        grid_evidence.append({'width': width, 'positions': positions})
        client.key(b'q')
    proof.json_dump(receipts / 'native-grid-evidence.json', grid_evidence)
    client.resize(180)
    for target in ids:
        open_map(); client.drain(1)
        # Every pane is reachable with native-order traversal, even offscreen.
        for step in range(len(ids)):
            frame = client.frame()
            if selected_in_frame(frame, target, proof.snapshot(state)):
                break
            client.key(b']')
        else:
            raise proof.ProofFailure(f'native pane not selectable: {target}')
        (receipts / f'selection-{target}.txt').write_text(frame)
        client.key(b'f'); time.sleep(.5)
        actual = proof.snapshot(state)
        if actual['focused_pane_id'] != target:
            proof.json_dump(receipts / 'interaction-focus-counterexample.json', {'target': target, 'actual': actual, 'frame': frame})
            raise proof.ProofFailure(f'exact focus failed for {target}')
    open_map(); client.drain(1)
    client.key(b'\r'); client.key(b'k'*100)
    frame = client.frame()
    original_width = client.screen.columns
    client.resize(40); client.resize(original_width); client.key(b'r')
    if client.frame() != frame:
        raise proof.ProofFailure('native resize/refresh lost selected detail position')
    (receipts / 'native-resize-detail.txt').write_text(frame)
    client.key(b'\x1b')
    # Ownership belongs to the tab focused at open, not the selected card.
    client.key(b'q')
    live = proof.snapshot(state)
    owner = live['focused_pane_id']
    owner_tab = next(p['tab_id'] for p in live['panes'] if p['pane_id'] == owner)
    target = next(p for p in live['panes'] if p['tab_id'] != owner_tab)
    open_map(); client.drain(1)
    for _ in range(len(ids)):
        if selected_in_frame(client.frame(), target['pane_id'], proof.snapshot(state)):
            break
        client.key(b']')
    else:
        raise proof.ProofFailure('non-owner target not selectable')
    before_close = proof.snapshot(state)
    proof.json_dump(receipts / 'native-selected-target-before-close.json', {
        'owner_pane_id': owner, 'owner_tab_id': owner_tab,
        'target_tab_id': target['tab_id'], 'selected_pane_id': target['pane_id'],
        'selected_terminal_id': target.get('terminal_id'),
        'snapshot': before_close, 'frame': client.frame()})
    from map_journey import require_busy, popup_busy
    require_busy(state, receipts, 'native-before-selected-target-close-busy')
    proof.api_request(state, 'pane.close', {'pane_id': target['pane_id']})
    time.sleep(1)
    after_close = proof.snapshot(state)
    proof.json_dump(receipts / 'native-selected-target-closed.json', after_close)
    (receipts / 'native-after-selected-target-close-frame.txt').write_text(client.frame())
    require_busy(state, receipts, 'native-after-selected-target-close-popup')
    client.key(b'f')
    notice = client.frame()
    (receipts / 'native-closed-target-notice.txt').write_text(notice)
    if 'Cannot focus: selected terminal vanished' not in notice:
        raise proof.ProofFailure('real closed non-owner target did not show vanished selection notice')
    if proof.snapshot(state)['focused_pane_id'] != after_close['focused_pane_id']:
        raise proof.ProofFailure('real closed target caused unrelated focus')
    client.key(b'q')
    # Distinct native lifetime case: delete OWNER TAB, never type into shell.
    open_map(); client.drain(1)
    require_busy(state, receipts, 'native-before-owner-delete-busy')
    proof.json_dump(receipts / 'native-owner-before-delete.json', {
        'owner_tab_id': owner_tab, 'owner_pane_id': owner,
        'snapshot': proof.snapshot(state), 'frame': client.frame()})
    proof.api_request(state, 'tab.close', {'tab_id': owner_tab})
    time.sleep(1)
    dismissed = proof.snapshot(state)
    frame = client.frame()
    (receipts / 'native-owner-deleted-frame.txt').write_text(frame)
    proof.json_dump(receipts / 'native-owner-deleted.json', dismissed)
    if 'Herdr Overview' in frame:
        raise proof.ProofFailure('owner deletion retained stale viewer frame')
    busy, response = popup_busy(state)
    proof.json_dump(receipts / 'native-owner-deleted-probe.json', response)
    if busy:
        raise proof.ProofFailure('owner deletion did not dismiss native popup')
    client.drain(1); client.key(b'q')  # Only the successfully allocated probe.
    if proof.snapshot(state)['focused_pane_id'] != dismissed['focused_pane_id']:
        raise proof.ProofFailure('owner dismissal/probe made unrelated focus')
    open_map(); client.drain(1)
    require_busy(state, receipts, 'native-owner-survivor-reopen-busy')
    if not selected_in_frame(client.frame(), dismissed['focused_pane_id'], proof.snapshot(state)):
        raise proof.ProofFailure('survivor reopen selected stale owner')
    (receipts / 'native-owner-survivor-reopen-frame.txt').write_text(client.frame())
    client.key(b'f'); time.sleep(.5)
    if proof.snapshot(state)['focused_pane_id'] != dismissed['focused_pane_id']:
        raise proof.ProofFailure('survivor reopen focus selected wrong pane')
    busy, response = popup_busy(state)
    proof.json_dump(receipts / 'native-owner-survivor-focus-closed.json', response)
    if busy:
        raise proof.ProofFailure('survivor focus did not close popup')
    client.drain(1); client.key(b'q')  # Only probe popup, not restored shell.
    if log_digest(root) != baseline:
        raise proof.ProofFailure('native traversal generated backend calls')
    proof.json_dump(receipts / 'interaction-passive-logs.json', {'before': baseline, 'after': log_digest(root)})
    return {'native_multiworkspace_single_tab_grid_wide_narrow': True,
        'native_every_pane_selectable_exact_focus': True,
        'native_resize_refresh_selection_preserved': True,
        'native_closed_target_notice_no_unrelated_focus': True,
        'native_owner_tab_dismissal_survivor_reopen_focus': True}


def scripted_interactions(root, env, receipts, Client):
    """Scripted protocol-22 statuses; actual public viewer CLI, not detection."""
    import json
    import socketserver
    import threading
    fixture = root / 'scripted-interactions'; fixture.mkdir()
    state_dir = fixture / 'state'; state_dir.mkdir()
    socket_path = str(fixture / 'api.sock')
    snapshot = {'protocol': 22, 'version': '0.9.1', 'focused_workspace_id': 'w',
        'focused_tab_id': 't1', 'focused_pane_id': 'p1',
        'workspaces': [{'workspace_id': 'w', 'label': 'SCRIPTED workspace', 'active_tab_id': 't1'}],
        'tabs': [{'tab_id': f't{i}', 'workspace_id': 'w', 'label': ('LONG TITLE ' + 'title ' * 30 + 'TITLE-END') if i == 1 else f'SCRIPTED tab {i}', 'number': i} for i in (1,2,3)],
        'panes': [{'pane_id': f'p{i}', 'terminal_id': f'terminal{i}', 'tab_id': f't{min(i,3)}',
            'workspace_id': 'w', 'label': f'SCRIPTED subject {i}', 'title': 'LONG TITLE ' + 'title ' * 30 + 'TITLE-END',
            'agent': 'pi' if i < 4 else None, 'agent_status': 'blocked' if i == 3 else 'working'} for i in (1,2,3,4)],
        'agents': [], 'layouts': []}
    requests = []
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            message = json.loads(self.rfile.readline()); requests.append(message)
            if message['method'] == 'session.snapshot':
                result = {'snapshot': snapshot}
            elif message['method'] == 'pane.focus':
                result = {}
            else:
                self.wfile.write((json.dumps({'id': message['id'], 'error': {'code': 'unexpected', 'message': message['method']}})+'\n').encode()); return
            self.wfile.write((json.dumps({'id': message['id'], 'result': result})+'\n').encode())
    server = socketserver.ThreadingUnixStreamServer(socket_path, Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    scripted_env = dict(env, HERDR_SOCKET_PATH=socket_path, HERDR_PLUGIN_STATE_DIR=str(state_dir),
        XDG_DATA_HOME=str(fixture / 'data'))
    data = fixture / 'data/session-recap'; records = data / 'records/2026-09-30'; records.mkdir(parents=True)
    prompts = data / 'prompts'; prompts.mkdir()
    (data / 'latest.json').write_text(json.dumps({'sources': [{'source_kind': 'manual', 'source_id': 'p1', 'latest_success_id': 'good', 'last_attempt_id': 'bad'}]}))
    (records / 'good.json').write_text(json.dumps({'record_id': 'good', 'source_kind': 'manual', 'source_id': 'p1', 'status': 'published', 'published_at': '2026-09-30T00:00:00Z', 'summary': '\n'.join(['RECAP-BEGIN'] + [f'RECAP-LINE-{i:03d}' for i in range(70)] + ['RECAP-END'])}))
    (records / 'bad.json').write_text(json.dumps({'record_id': 'bad', 'source_kind': 'manual', 'source_id': 'p1', 'status': 'failed', 'created_at': '2026-09-30T01:00:00Z', 'failure': {'message': 'ERROR-BEGIN\n' + 'error\n'*35 + 'ERROR-END'}}))
    (prompts / 'p1.json').write_text(json.dumps({'schema_version': 1, 'session_id': 'synthetic-session', 'pane_id': 'p1', 'text': 'PROMPT-BEGIN\n' + 'prompt\n'*35 + 'PROMPT-END'}))
    client = None
    try:
        client = Client({}, scripted_env, 120, ['node', str(proof.ROOT / 'dot_local/share/herdr-overview/index.mjs'), 'overview'])
        client.drain(1)
        def current():
            # A repaint can briefly clear the PTY; wait for the next completed canvas.
            deadline = time.monotonic() + 10
            while True:
                frame = client.frame()
                try:
                    canvas(frame); return frame
                except proof.ProofFailure:
                    if time.monotonic() > deadline: raise
        def capture(name):
            frame = current(); (receipts / f'scripted-{name}.txt').write_text(frame); return frame
        frame = capture('initial')
        if 'SCRIPTED' not in frame or 'BLOCKED' not in frame:
            raise proof.ProofFailure('scripted status fixture did not render')
        client.key(b'n')
        frame = capture('next-blocked')
        if not selected_in_frame(frame, 'p3', snapshot):
            raise proof.ProofFailure('next-blocked selected wrong pane')
        client.key(b']'); client.key(b']')
        client.key(b'\r'); client.key(b'k'*100)
        seen = set(); reading = None
        for i in range(220):
            frame = current()
            (receipts / 'scripted-current-detail.txt').write_text(frame)
            for marker in ('TITLE-END','RECAP-END','ERROR-END','PROMPT-END'):
                if contains(frame, marker):
                    seen.add(marker)
                    (receipts / f'scripted-wide-{marker}.txt').write_text(frame)
            if i == 40:
                reading = frame
                client.key(b'r')
                if current() != reading:
                    raise proof.ProofFailure('refresh changed reading position')
                client.resize(40)
                capture('narrow-reading')
                client.resize(120)
                restored = capture('wide-restored-reading')
                (receipts / 'scripted-wide-before-resize.txt').write_text(reading)
                if restored != reading:
                    raise proof.ProofFailure('resize round trip changed reading position')
            client.key(b'j')
        capture('detail-end')
        client.resize(40); client.key(b'k'*250)
        narrow_seen = set()
        # Batched key writes still drive the real input parser; take a fresh
        # current frame after each batch, never search accumulated output.
        for _ in range(80):
            frame = current()
            (receipts / 'scripted-current-detail.txt').write_text(frame)
            for marker in ('TITLE-END','RECAP-END','ERROR-END','PROMPT-END'):
                if contains(frame, marker):
                    narrow_seen.add(marker)
                    (receipts / f'scripted-narrow-{marker}.txt').write_text(frame)
            client.key(b'j'*3)
        capture('narrow-detail-end')
        if narrow_seen != {'TITLE-END','RECAP-END','ERROR-END','PROMPT-END'}:
            raise proof.ProofFailure(f'narrow detail markers not reachable: {narrow_seen}')
        client.resize(120)
        if seen != {'TITLE-END','RECAP-END','ERROR-END','PROMPT-END'}:
            raise proof.ProofFailure(f'full detail markers not reachable: {seen}')
        client.key(b'd')
        if not contains(capture('digest-disclosure'), 'Session digest'):
            raise proof.ProofFailure('digest disclosure did not open')
        client.key(b'\x1b'); client.key(b'k'*250)
        if not contains(capture('escape-digest-to-detail'), 'TITLE-END'):
            raise proof.ProofFailure('Escape did not unwind digest to detail')
        client.key(b'\x1b')
        escaped = capture('escape-detail-to-map')
        first, second = card(escaped, 'p1', snapshot), card(escaped, 'p2', snapshot)
        if (not selected_in_frame(escaped, 'p1', snapshot) or not first or not second
                or first['row'] != second['row'] or first['col'] >= second['col']
                or not contains(escaped, 'Latest good recap')
                or any(contains(escaped, marker) for marker in
                    ('TITLE-END', 'PROMPT-BEGIN', 'PROMPT-END', 'RECAP-END', 'DIGEST-BEGIN', 'DIGEST-END'))):
            raise proof.ProofFailure('Escape did not unwind detail to collapsed selected p1 grid')
        # Explicit scripted native-status matrix; title is never detection.
        snapshot['panes'][3]['title'] = 'Pi: SCRIPTED TITLE ONLY'
        for status in ('working', 'idle', 'blocked', 'done', 'unknown'):
            snapshot['panes'][0]['agent_status'] = status
            client.key(b'r'); status_frame = capture(f'status-{status}')
            expected = {'idle': 'READY', 'blocked': '× BLOCKED'}.get(status, status.upper())
            actual = card(status_frame, 'p1', snapshot)
            if not selected_in_frame(status_frame, 'p1', snapshot) or not actual or not any(row.strip() == expected for row in actual['rows']):
                raise proof.ProofFailure(f'scripted native status mismatch: {status}')
            for target in ('p2', 'p3', 'p4'):
                client.key(b']')
                if not selected_in_frame(capture(f'status-{status}-{target}'), target, snapshot):
                    raise proof.ProofFailure('status traversal lost native order')
            title_frame = capture(f'status-{status}-title-only')
            absent = card(title_frame, 'p4', snapshot)
            if not absent or not any(row.strip() == 'NO AGENT' for row in absent['rows']):
                raise proof.ProofFailure(f'scripted status/title-only detection mismatch: {status}')
            if any(row.strip() == 'WORKING' for row in absent['rows']) or 'Pi: SCRIPTED TITLE ONLY' in title_frame:
                raise proof.ProofFailure('title-only fixture became recognized agent or crowded glance')
            for target in ('p3', 'p2', 'p1'):
                client.key(b'[')
                if not selected_in_frame(capture(f'status-{status}-return-{target}'), target, snapshot):
                    raise proof.ProofFailure('status traversal failed to return in native order')
        order_before = [p['pane_id'] for p in snapshot['panes']]
        snapshot['panes'][0]['agent_status'] = 'idle'
        snapshot['panes'][1]['agent_status'] = 'blocked'
        client.key(b'r'); changed = capture('changed-status')
        if not any(row.strip() == 'READY' for row in card(changed,'p1',snapshot)['rows']) or not any(row.strip() == '× BLOCKED' for row in card(changed,'p2',snapshot)['rows']):
            raise proof.ProofFailure('current status frame did not reflect transition')
        observed_pairs = set()
        for target in order_before:
            current = capture(f'changed-order-{target}')
            if not selected_in_frame(current, target, snapshot):
                raise proof.ProofFailure('status transition changed native traversal order')
            group = ('p1', 'p2') if target in ('p1', 'p2') else ('p3', 'p4')
            pair = [card(current, pane, snapshot) for pane in group]
            if all(pair):
                if (pair[0]['row'], pair[0]['col']) >= (pair[1]['row'], pair[1]['col']):
                    raise proof.ProofFailure('status transition reordered current viewer cards')
                observed_pairs.add(group)
            if target != order_before[-1]:
                client.key(b']')
        if observed_pairs != {('p1', 'p2'), ('p3', 'p4')}:
            raise proof.ProofFailure('status transition lacks completed visible pair-order evidence')
        if [p['pane_id'] for p in snapshot['panes']] != order_before:
            raise proof.ProofFailure('status transition reordered fixture')
        client.key(b'[' * 3)
        if not selected_in_frame(capture('changed-order-return'), 'p1', snapshot):
            raise proof.ProofFailure('changed order traversal did not return p1')
        client.key(b'n')
        if not selected_in_frame(capture('changed-next-blocked'), 'p2', snapshot):
            raise proof.ProofFailure('changed attention not reflected by next-blocked')
        snapshot['panes'] = [p for p in snapshot['panes'] if p['pane_id'] != 'p2']
        focus_before = sum(r['method'] == 'pane.focus' for r in requests)
        client.key(b'f')
        frame = capture('closed-target')
        if not contains(frame, 'Cannot focus: selected terminal vanished') or client.process.poll() is not None:
            raise proof.ProofFailure('closed target did not retain popup with notice')
        if sum(r['method'] == 'pane.focus' for r in requests) != focus_before:
            raise proof.ProofFailure('closed target focused an unrelated pane')
        client.key(b'q'); client.process.wait(timeout=5)
        if client.process.returncode:
            raise proof.ProofFailure('viewer CLI failed on quit')
        if any(r['method'] not in ('session.snapshot','pane.focus') for r in requests):
            raise proof.ProofFailure('passive viewer called unexpected public API')
        return {'scripted_explicit_statuses_title_not_detection': True, 'scripted_status_attention_next_blocked': True, 'scripted_full_detail_markers': sorted(seen),
            'scripted_narrow_full_detail_markers': sorted(narrow_seen),
            'scripted_refresh_resize_reading_preserved': True, 'scripted_closed_target_notice_no_focus': True}
    finally:
        (receipts / 'scripted-public-protocol-requests.json').write_text(json.dumps(requests, indent=2))
        if client: client.close()
        server.shutdown(); server.server_close(); thread.join(timeout=5)
