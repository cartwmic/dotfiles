#!/usr/bin/env python3
"""Real dated-directory write failure, readable baseline, draft and viewer proof.
Requires pyte/wcwidth in the selected Python; see current_screen.py.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from current_screen import CurrentScreen, plain
from public_helpers import PublicPi

screen = CurrentScreen()
observed = []
with tempfile.TemporaryDirectory(prefix='recap-ux-unsaved-') as temporary:
    root = Path(temporary)
    pi = PublicPi(root, terminal=screen, config={'inputBudget': 24000}, environment={'RECAP_PROOF_UX': '1', 'TZ': 'UTC'})
    dated = None
    original_mode = None
    cleanup = {'root': str(root), 'mode_restored': False, 'baseline_hashes_restored': False}
    def saved(): return [r for r in pi.records() if r['status'] == 'published']
    def recap_calls(): return [e for e in pi.events() if e['event'] == 'call' and 'number' in e]
    def hashes(): return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in (root / 'data/session-recap/records').rglob('*.json')}
    try:
        if 'Trust project folder?' in pi.visible(): os.write(pi.master, b'\x1b[B\r'); pi.collect(2)
        pi.send('Inspect orchard', 1)
        pi.send('/recap')
        pi.wait(lambda: len(saved()) == 1, 'baseline not saved'); pi.collect(1)
        baseline = saved()[0]
        widget = screen.widget(baseline, 'local', pi.env, 'readable-success-baseline')
        prior_hashes = hashes()
        record_file = next(p for p in (root / 'data/session-recap/records').rglob('*.json') if json.loads(p.read_text())['record_id'] == baseline['record_id'])
        dated = record_file.parent
        original_mode = dated.stat().st_mode & 0o7777
        # Actual write failure in a real dated directory; prior records stay readable.
        dated.chmod(0o555)
        assert dated.stat().st_mode & 0o7777 == 0o555
        try:
            (dated / 'write-preflight-owned').write_text('must fail')
        except PermissionError: pass
        else: raise AssertionError('0555 did not enforce write failure')
        assert saved() == [baseline]
        pi.send('Inspect harbor', 1)
        calls_before = len(recap_calls())
        pi.gate.touch()
        start = len(pi.output)
        pi.send('/recap')
        pi.wait(lambda: len(recap_calls()) == calls_before + 1, 'backend not started')
        # Put real text in the main editor while detached generation is gated.
        os.write(pi.master, b'KILLRING_original\x01\x0bDRAFT_unsent_harbor'); pi.collect(.3)
        pi.gate.unlink()
        pi.wait(lambda: any(e['event'] == 'terminal' and e['status'] == 'generated-unsaved' for e in pi.receipts()), 'actual unsaved outcome missing')
        pi.collect(1)
        terminal = [e for e in pi.receipts() if e['event'] == 'terminal'][-1]
        assert terminal['status'] == 'generated-unsaved' and terminal['attempt'] == 2
        assert len(recap_calls()) == calls_before + 2, 'expected one actual retry'
        assert 'harbor-checks-passed' in terminal['text']
        action_text = plain(pi.visible(start))
        assert 'Generated recap was not saved; no coverage was advanced.' in action_text
        assert '詳しい' not in action_text and 'Observed harbor:' not in action_text, 'unsaved narrative autodumped'
        assert saved() == [baseline] and hashes() == prior_hashes
        assert screen.widget(baseline, 'local', pi.env, 'unsaved-retained-success-widget') == widget
        assert any('DRAFT_unsent_harbor' in l for l in screen.capture('unsaved-draft-preserved')['lines'])
        # Actual key -> private launcher -> public /recap view; no mock UI or
        # editor setter, and the real editor draft remains nonempty at entry.
        envelopes = len(pi.envelopes()); events = len(pi.events())
        fence = pi.current(pi.envelopes()[-1]['request_key'])
        os.write(pi.master, b'\x1bg'); pi.collect(.7)
        viewer_frame = '\n'.join(screen.capture('viewer-with-nonempty-editor')['lines'])
        assert 'Esc close' in viewer_frame and '詳しい1:' in viewer_frame and 'Observed orchard:' in viewer_frame, 'actual saved viewer not opened'
        os.write(pi.master, b'\x1b'); pi.collect(.4)
        assert any('DRAFT_unsent_harbor' in l for l in screen.capture('viewer-draft-restored')['lines'])
        assert len(pi.envelopes()) == envelopes and pi.current(pi.envelopes()[-1]['request_key']) == fence
        assert not any(e['event'] == 'call' for e in pi.events()[events:])
        # Yank the prior killed text into the restored actual editor. This tests
        # retained kill ring independently of the draft's current text.
        os.write(pi.master, b'\x19'); pi.collect(.3)
        assert any('DRAFT_unsent_harborKILLRING_original' in l for l in screen.capture('viewer-killring-restored')['lines'])
        os.write(pi.master, b'\x01\x0b'); pi.collect(.2)
        dated.chmod(original_mode)
        cleanup['mode_restored'] = dated.stat().st_mode & 0o7777 == original_mode
        cleanup['baseline_hashes_restored'] = hashes() == prior_hashes
        assert cleanup['mode_restored'] and cleanup['baseline_hashes_restored']
        # The failed attempt did not establish coverage: fresh incremental
        # follow-up must capture harbor facts in MATERIAL, not baseline background.
        pi.send('/recap')
        pi.wait(lambda: len(saved()) == 2, 'restored writable followup failed'); pi.collect(1)
        assert 'FACT_result=harbor-checks-passed' in pi.envelopes()[-1]['material']
        assert 'harbor-checks-passed' in saved()[-1]['summary']
        screen.widget(saved()[-1], 'local', pi.env, 'restored-success-followup')
        assert all(hashes()[p] == digest for p, digest in prior_hashes.items())
        pi.assert_no_transcript_output()
        observed = ['real dated 0555 failure/readable successful baseline', 'two real attempts/one retry', 'explicit unsaved warning/no narrative dump', 'unchanged successful widget/time/coverage/hash', 'async unsent draft and viewer draft/killring retained via real keys', 'exact mode restored and uncovered harbor followup saved']
        print(json.dumps({'status': 'PASS', 'observations': observed, 'cleanup': cleanup}))
    except Exception:
        print(json.dumps({'status': 'FAIL', 'observations': observed}), file=sys.stderr)
        raise
    finally:
        if dated is not None and original_mode is not None:
            dated.chmod(original_mode)
            cleanup['mode_restored'] = dated.stat().st_mode & 0o7777 == original_mode
        evidence = Path(os.environ['RECAP_UX_EVIDENCE']) if 'RECAP_UX_EVIDENCE' in os.environ else None
        if evidence:
            evidence.mkdir(parents=True, exist_ok=True)
            (evidence / 'ui.ansi').write_bytes(pi.output)
            (evidence / 'provider.jsonl').write_text(pi.log.read_text() if pi.log.exists() else '')
            (evidence / 'transport.jsonl').write_text(pi.transport.read_text() if pi.transport.exists() else '')
            (evidence / 'records.json').write_text(json.dumps(pi.records(), indent=2))
            (evidence / 'frames.json').write_text(json.dumps(screen.frames, ensure_ascii=False, indent=2))
        pi.close()
        cleanup['all_supervisors_exited'] = {e['pid'] for e in pi.envelopes()} <= {e['pid'] for e in pi.receipts() if e['event'] == 'exited'}
        if evidence: (evidence / 'cleanup.json').write_text(json.dumps(cleanup, indent=2))
    if evidence: (evidence / 'cleanup.json').write_text(json.dumps(cleanup, indent=2))
assert not root.exists(), 'private fixture survived'
if evidence:
    cleanup['root_removed'] = not root.exists()
    (evidence / 'cleanup.json').write_text(json.dumps(cleanup, indent=2))
