#!/usr/bin/env python3
"""Private pinned-server popup and interaction journeys, failing closed.

Interactions require a private venv using requirements-interactions.txt.
Scripted statuses exercise the public viewer, not native agent detection.
This does not replace publication/grouping or attended phone receipts.
"""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pty
import select
import struct
import subprocess
import termios
import time
import proof
from map_frames import canvas, contains
from map_publication import publication
from map_identity import identity


class Client:
    def __init__(self, state, env, width, command=None, max_drain=10):
        self.closed = False
        self.max_drain = max_drain
        self.master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 32, width, 0, 0))
        import pyte
        class Screen(pyte.Screen):
            def report_device_status(self, mode, **kwargs):
                # Herdr emits DEC private status queries; these do not draw cells.
                if not kwargs.get('private'):
                    super().report_device_status(mode)
        self.screen = Screen(width, 32)
        self.stream = pyte.ByteStream(self.screen)
        self.output = bytearray()
        self.process = subprocess.Popen(command or [state['herdr_bin']], env=env,
            stdin=slave, stdout=slave, stderr=slave, close_fds=True)
        os.close(slave)

    def drain(self, seconds=.5):
        if self.closed:
            return
        minimum = time.monotonic() + seconds
        deadline = minimum + self.max_drain
        while time.monotonic() < deadline:
            ready, _, _ = select.select([self.master], [], [], .15)
            if not ready and time.monotonic() >= minimum:
                return
            if ready:
                try:
                    data = os.read(self.master, 65536)
                    self.output.extend(data)
                    self.stream.feed(data)
                except OSError:
                    break

    def expect(self, marker, offset=0, timeout=15):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.drain(.1)
            # Native incremental rendering can leave identical cells unchanged
            # across close/reopen; current completed cells, not ANSI substrings,
            # are the observable UI. Allocation is checked separately by API.
            try:
                if contains('\n'.join(self.screen.display), marker):
                    self.drain(.3)
                    canvas('\n'.join(self.screen.display))
                    return
            except proof.ProofFailure:
                pass
            if self.process.poll() is not None:
                break
        raise proof.ProofFailure(f'attached client did not render {marker!r}: current cells={self.screen.display!r}')

    def key(self, value):
        os.write(self.master, value)
        self.drain()

    def frame(self):
        self.drain(.2)
        return '\n'.join(self.screen.display)

    def resize(self, width, height=32):
        self.screen.resize(lines=height, columns=width)
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack('HHHH', height, width, 0, 0))
        # Popen PTYs are not controlling terminals; deliver their resize signal.
        import signal
        self.process.send_signal(signal.SIGWINCH)
        self.drain(1)

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        os.close(self.master)


def native_signature(snapshot):
    # Attached clients of different sizes own successive render geometry.
    # Preserve structural splits, native order/identity, labels and focus, but
    # compare viewport geometry separately in the retained raw snapshots.
    value = json.loads(json.dumps(snapshot))
    for pane in value.get('panes', []):
        pane.get('scroll', {}).pop('viewport_rows', None)
    for layout in value.get('layouts', []):
        layout.pop('area', None)
        for pane in layout.get('panes', []):
            pane.pop('rect', None)
    return {key: value.get(key) for key in
        ('workspaces', 'tabs', 'panes', 'layouts', 'focused_workspace_id',
         'focused_tab_id', 'focused_pane_id')}


def popup_busy(state):
    """Probe the public popup allocation boundary, not accumulated PTY output.

    A successful probe is returned to the caller for immediate owned dismissal.
    """
    try:
        return False, proof.api_request(state, 'plugin.pane.open', {
            'plugin_id': 'overview', 'entrypoint': 'overview',
            'placement': 'popup', 'width': '100%', 'height': '100%', 'focus': True})
    except proof.ProofFailure as exc:
        if 'ui_busy' not in str(exc):
            raise
        return True, {'error': str(exc)}


def require_busy(state, receipts, name):
    busy, response = popup_busy(state)
    proof.json_dump(receipts / f'{name}.json', response)
    if not busy:
        raise proof.ProofFailure(f'{name}: shared popup allocation did not return ui_busy')
    return response


# Read-only CLI queries (the recap extension's widget/history refresh) are not
# generation; only these subcommands can create or start a recap.
GENERATING_RECAP_COMMANDS = {'create', 'run', 'reserve', 'prepare', 'publish'}


def log_digest(root):
    def content(name):
        path = root / name
        if not path.exists():
            return None
        data = path.read_bytes()
        if name == 'recap-commands.jsonl':
            data = b''.join(line + b'\n' for line in data.splitlines()
                            if json.loads(line)[0] in GENERATING_RECAP_COMMANDS)
        return hashlib.sha256(data).hexdigest()
    return {name: content(name) for name in ('backend-captures.jsonl', 'recap-commands.jsonl')}


INTERACTION_OUTCOMES = {
    'native_multiworkspace_single_tab_grid_wide_narrow',
    'native_every_pane_selectable_exact_focus', 'native_resize_refresh_selection_preserved',
    'native_closed_target_notice_no_unrelated_focus',
    'native_owner_tab_dismissal_survivor_reopen_focus',
    'scripted_explicit_statuses_title_not_detection', 'scripted_status_attention_next_blocked',
    'scripted_refresh_resize_reading_preserved', 'scripted_closed_target_notice_no_focus',
    'complete_interactions_backend_logs_unchanged',
}
IDENTITY_OUTCOMES = {
    'scripted_pi_publication', 'publication_plus_exact_30s_deadline',
    'last_good_preserved', 'failure_deadline_unchanged', 'group_member_ids_preserved',
    'verified_current_adapter_identity', 'complete_dated_digest_scroll',
    'wrong_session_missing_malformed_excluded', 'digest_view_passive',
    'wide_narrow_full_dated_last_good_failure_prompt', 'real_session_replacement_reload',
    'native_manual_automatic_membership_names', 'body_redraw_zero_name_churn',
    'native_unique_terminal_rekey_focus', 'actual_reader_old_wrong_duplicate_dead_rejected',
    'multi_pane_own_recap_attribution', 'current_rekey_publication_attribution',
}


def require_completed_outcomes(outcomes, scenario):
    required = {'both_clients_rendered', 'public_ui_busy_singleton',
        'native_structure_labels_focus_unchanged_while_open', 'close_reopen', 'viewer_passive'}
    if scenario in ('all', 'interactions'):
        required |= INTERACTION_OUTCOMES
        for key in ('scripted_full_detail_markers', 'scripted_narrow_full_detail_markers'):
            if outcomes.get(key) != ['ERROR-END', 'PROMPT-END', 'RECAP-END', 'TITLE-END']:
                raise proof.ProofFailure(f'incomplete assertion composition: {key}')
    if scenario in ('all', 'identity'):
        required |= IDENTITY_OUTCOMES
    missing = sorted(key for key in required if outcomes.get(key) is not True)
    if missing:
        raise proof.ProofFailure('incomplete assertion composition: ' + ', '.join(missing))


def run(receipts, scenario):
    receipts.mkdir(parents=True, mode=0o700, exist_ok=False)
    os.chmod(receipts, 0o700)
    run_id = proof.make_run_id()
    base = receipts / 'fixtures'
    root = proof.run_root(run_id, base)
    clients = []
    server = None
    record = dict(command_id='map-user-journey', scenario=scenario,
        status='FAIL', repo_root=str(proof.ROOT),
        head=proof.run_process(['git', 'rev-parse', 'HEAD']).stdout.strip(),
        run_id=run_id, phone='pending', deployment='not performed', outcomes={})
    try:
        root, state, env = proof.setup_herdr_run(run_id, base)
        with (root / 'server/server.log').open('ab') as output:
            server = subprocess.Popen([state['herdr_bin'], 'server'], env=env,
                cwd=root, stdin=subprocess.DEVNULL, stdout=output,
                stderr=subprocess.STDOUT, start_new_session=True)
        proof.wait_for(lambda: Path(state['socket_path']).exists() and
            proof.server_status(state, env).get('running'), 'private pinned server')
        proof.snapshot(state)
        workdir = root / 'synthetic-work'; workdir.mkdir()
        proof.herdr_cmd(state, env, 'workspace', 'create', '--cwd', str(workdir),
            '--label', 'SYNTHETIC-MAP-WORKSPACE')
        for width in (120, 40):
            clients.append(Client(state, env, width))
        for client in clients:
            client.drain(1)
        before = proof.snapshot(state)
        proof.json_dump(receipts / 'native-before.json', before)
        backend_before = log_digest(root)
        def open_map():
            return proof.api_request(state, 'plugin.action.invoke',
                {'action_id': 'overview.open'})
        open_map()
        for client in clients:
            client.expect('Herdr Overview')
        record['outcomes']['both_clients_rendered'] = True
        require_busy(state, receipts, 'popup-open-busy')
        open_map()  # Existing shared popup must remain singleton.
        require_busy(state, receipts, 'popup-singleton-busy')
        record['outcomes']['public_ui_busy_singleton'] = True
        for client in clients:
            client.drain(1)
        during = proof.snapshot(state)
        if native_signature(before) != native_signature(during):
            raise proof.ProofFailure('popup changed native layouts/labels/focus')
        record['outcomes']['native_structure_labels_focus_unchanged_while_open'] = True
        # Escape closes the shared temporary view; reopening must produce a fresh frame.
        clients[0].key(b'\x1b')
        time.sleep(1)
        offsets = [len(c.output) for c in clients]
        if scenario in ('all', 'interactions'):
            busy, response = popup_busy(state)
            proof.json_dump(receipts / 'popup-after-escape.json', response)
            if busy:
                raise proof.ProofFailure('Escape left the shared popup busy')
            record['outcomes']['public_closed_then_reopened'] = True
        else:
            open_map()
        # Shared PTY is one geometry: prove current complete reopen on the
        # fitting wide peer, not independent simultaneous client layouts.
        clients[0].expect('Herdr Overview', offsets[0])
        record['outcomes']['close_reopen'] = True
        clients[0].key(b'r')
        clients[0].key(b'\x1b')
        time.sleep(1)
        after = proof.snapshot(state)
        proof.json_dump(receipts / 'native-after.json', after)
        if native_signature(before) != native_signature(after):
            raise proof.ProofFailure('viewer changed native layouts/labels/focus')
        if log_digest(root) != backend_before:
            raise proof.ProofFailure('viewer generated recap commands/backend calls')
        record['outcomes']['viewer_passive'] = True
        if scenario in ('all', 'interactions'):
            focus_offsets = [len(c.output) for c in clients]
            open_map()
            clients[0].expect('Herdr Overview', focus_offsets[0])
            require_busy(state, receipts, 'popup-before-focus')
            selected = proof.snapshot(state)
            proof.json_dump(receipts / 'selected-before-focus.json', {
                'selected_pane_id': selected['focused_pane_id'],
                'selected_terminal_id': next(p.get('terminal_id') for p in selected['panes']
                    if p['pane_id'] == selected['focused_pane_id']),
                'source': 'initial native selection; no navigation performed'})
            clients[1].key(b'f')
            time.sleep(1)
            focused = proof.snapshot(state)
            proof.json_dump(receipts / 'native-after-focus.json', focused)
            if focused['focused_pane_id'] != selected['focused_pane_id']:
                raise proof.ProofFailure('focus selected a different native pane')
            busy, response = popup_busy(state)
            proof.json_dump(receipts / 'popup-after-focus.json', response)
            if busy:
                raise proof.ProofFailure('successful focus did not close popup')
            from map_frames import wait_frame
            wait_frame(clients[0], 'Esc/q')
            clients[1].key(b'q')
            time.sleep(1)
            record['outcomes']['initial_selected_native_focus_closes_from_narrow_client'] = True
            if log_digest(root) != backend_before:
                raise proof.ProofFailure('focus journey generated backend calls')
            from map_interactions import native_interactions
            record['outcomes'].update(native_interactions(root, state, env, receipts, clients, open_map, log_digest))
            from map_interactions import scripted_interactions
            record['outcomes'].update(scripted_interactions(root, env, receipts, Client))
            if log_digest(root) != backend_before:
                raise proof.ProofFailure('complete interaction paths changed backend call logs')
            record['outcomes']['complete_interactions_backend_logs_unchanged'] = True
        if scenario in ('all', 'identity'):
            live = proof.snapshot(state)
            if scenario == 'all':
                # Preserve interaction survivors and deletion boundaries. Give
                # the identity lifecycle its required unlabelled singleton,
                # rather than inheriting a manual tab or multi-pane subject.
                old_ids = {p['pane_id'] for p in live['panes']}
                proof.herdr_cmd(state, env, 'tab', 'create', '--workspace',
                    live['workspaces'][0]['workspace_id'], '--cwd', str(workdir), '--no-focus')
                live = proof.snapshot(state)
                pane = next(p for p in live['panes'] if p['pane_id'] not in old_ids)
            else:
                pane = live['panes'][0]
            proof.api_request(state, 'pane.focus', {'pane_id': pane['pane_id']})
            proof.json_dump(receipts / 'combined-publication-target.json', {
                'pane': pane, 'snapshot': proof.snapshot(state)})
            completed = publication(root, state, env, pane['pane_id'], pane['workspace_id'], receipts,
                full_disclosure=True)
            record['outcomes'].update(completed)
            record['outcomes'].update(identity(root, state, env, pane['pane_id'], receipts,
                clients, open_map, log_digest, publication_outcomes=completed))
        require_completed_outcomes(record['outcomes'], scenario)
        record['status'] = 'PASS'
    except proof.ProofBlocked as exc:
        record.update(status='BLOCKED', reason=str(exc))
    except Exception as exc:
        import traceback
        (receipts / 'failure-traceback.txt').write_text(traceback.format_exc())
        record.update(status='FAIL', reason=f'{type(exc).__name__}: {exc}')
    finally:
        for index, client in enumerate(clients):
            client.drain(.1)
            path = receipts / f'client-{index}.ansi'
            path.write_bytes(client.output); path.chmod(0o600)
            client.close()
        if root.exists():
            for name in ('server/server.log', 'backend-captures.jsonl', 'recap-commands.jsonl'):
                source = root / name
                if source.is_file():
                    target = receipts / source.name
                    target.write_bytes(source.read_bytes()); target.chmod(0o600)
            try:
                record['cleanup'] = proof.scenario_cleanup(run_id, base)
            except Exception as exc:
                record.update(status='FAIL', cleanup_error=str(exc))
        if server is not None:
            if server.poll() is None:
                server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill(); server.wait(timeout=5)
        proof.json_dump(receipts / 'receipt.json', record)
        for receipt in receipts.iterdir():
            if receipt.is_file():
                receipt.chmod(0o600)
    print(json.dumps(record, sort_keys=True))
    return {'PASS': 0, 'FAIL': 1, 'BLOCKED': 2}[record['status']]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', choices=['all', 'smoke', 'interactions', 'identity'], default='all')
    parser.add_argument('--receipts', type=Path,
        default=Path('/tmp') / ('hm-' + proof.make_run_id()),
        help='new private receipt directory; must not already exist')
    args = parser.parse_args()
    return run(args.receipts.resolve(), args.scenario)


if __name__ == '__main__':
    raise SystemExit(main())
