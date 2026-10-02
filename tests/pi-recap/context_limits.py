#!/usr/bin/env python3
"""Focused private real-Pi compacted-context regression; no owner resources."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from current_screen import CurrentScreen
from public_helpers import PublicPi

before = os.environ.get('RECAP_CONTEXT_BEFORE') == '1'
full_only = os.environ.get('RECAP_CONTEXT_FULL_ONLY') == '1'
evidence = Path(os.environ['RECAP_CONTEXT_EVIDENCE'])
evidence.mkdir(parents=True, exist_ok=True)
observations = []
with tempfile.TemporaryDirectory(prefix='recap-context-') as temporary:
    root = Path(temporary)
    screen = CurrentScreen()
    pi = PublicPi(root, terminal=screen, config={'inputBudget': 24000}, environment={'RECAP_PROOF_UX': '1'})
    try:
        pi.stop()
        sdk = subprocess.check_output(['npm', 'root', '-g'], text=True).strip() + '/@earendil-works/pi-coding-agent/dist/index.js'
        seed = root / 'seed.mjs'
        seed.write_text('''import { SessionManager } from SDK;
const s = SessionManager.create(process.env.HOME, process.env.HOME + '/sessions');
const user = text => ({role:'user', content:[{type:'text',text}], timestamp:Date.now()});
s.appendMessage(user('RAW_ARCHIVED_MARKER ' + 'archived historical detail '.repeat(200000)));
s.appendMessage({role:'assistant',api:'openai-completions',provider:'recap-proof',model:'main',content:[{type:'text',text:'Archive complete'}],stopReason:'stop',timestamp:Date.now(),usage:{input:1,output:1,cacheRead:0,cacheWrite:0,totalTokens:2,cost:{input:0,output:0,cacheRead:0,cacheWrite:0,total:0}}});
const kept = s.appendMessage(user('FACT_topic=orchard FACT_result=orchard-checks-passed FACT_pending=orchard-deployment-unfinished FACT_next=orchard-review-before-deploy ' + 'recent public observation '.repeat(2400)));
s.appendCompaction('FACT_topic=older FACT_result=older-checks-passed FACT_pending=older-deployment-unfinished FACT_next=older-review-before-deploy SUMMARY_ELIGIBLE',kept,1500000);
console.log(JSON.stringify({file:s.getSessionFile(),id:s.getSessionId(),projection:s.buildSessionProjection().messages.map(m=>({role:m.role,chars:JSON.stringify(m).length}))}));
'''.replace('SDK', json.dumps(sdk)))
        info = json.loads(subprocess.check_output(['node', str(seed)], env=pi.env, text=True))
        session = Path(info['file'])
        original = session.read_bytes()
        archive_hash = hashlib.sha256(original).hexdigest()
        pi.launch(session); pi.collect(4)
        if 'Trust project folder?' in pi.visible(): pi.send('\x1b[B', 1)
        pi.send('/recap')
        pi.wait(lambda: pi.envelopes() and pi.terminal(pi.envelopes()[-1]['token']), 'recap did not complete')
        first = pi.envelopes()[-1]; terminal = pi.terminal(first['token'])
        pi.collect(1)
        observations.append({'phase':'before' if before else 'after','archive_bytes':len(original),'archive_sha256':archive_hash,'projection':info['projection'],'material_bytes':len(first['material'].encode()),'terminal':terminal,'backend_calls':len(pi.calls())})
        if before:
            assert terminal['status'] == 'failed' and not pi.calls()
            assert 'RAW_ARCHIVED_MARKER' in first['material']
            assert 'coverage unchanged' in pi.visible()
        else:
            assert terminal['status'] == 'published'
            assert len(first['material'].encode()) > 24000
            assert 'SUMMARY_ELIGIBLE' in first['material'] and 'RAW_ARCHIVED_MARKER' not in first['material']
            record = next(r for r in pi.records() if r['status']=='published')
            assert record['metadata']['pi']['scope'] == 'current-context'
            assert len(record['metadata']['pi']['coverage']['units']) == 2
            assert 'older-checks-passed' in record['summary'] and 'orchard-checks-passed' in record['summary']
            count = len(pi.calls()); pi.send('/recap', 1)
            assert len(pi.calls()) == count and len(pi.envelopes()) == 1
            # Manual full means all current context, not the retained raw archive.
            pi.send('/recap full')
            pi.wait(lambda: len(pi.envelopes()) == 2 and pi.terminal(pi.envelopes()[-1]['token']), 'full did not complete')
            full = pi.envelopes()[-1]
            assert pi.terminal(full['token'])['status']=='published'
            assert 'RAW_ARCHIVED_MARKER' not in full['material'] and 'SUMMARY_ELIGIBLE' in full['material']
            assert 'FACT_topic=orchard' in full['material']
            full_saved = next(r for r in pi.records() if r['status']=='published' and r['token']==full['token'])
            assert full_saved['metadata']['pi']['mode']=='full' and full_saved['metadata']['pi']['scope']=='current-context'
            assert len(full_saved['metadata']['pi']['coverage']['units'])==2
            count = len(pi.calls()); pi.send('/recap full', 1); pi.send('/recap', 1)
            assert len(pi.calls())==count and len(pi.envelopes())==2
            assert next(r for r in pi.records() if r['record_id']==full_saved['record_id'])['published_at']==full_saved['published_at']
            # Persisted full mode remains full: automatic material contains already
            # covered summary/recent material AND fresh activity, never old originals.
            pi.setting('mode', 'full'); pi.setting('completed', True)
            pi.send('Inspect harbor', 1)
            pi.wait(lambda: len([r for r in pi.records() if r['status']=='published']) == 3, 'automatic full-current fact follow-up failed')
            automatic = pi.envelopes()[-1]
            assert all(f in automatic['material'] for f in ('SUMMARY_ELIGIBLE','FACT_topic=orchard','FACT_topic=harbor'))
            assert 'RAW_ARCHIVED_MARKER' not in automatic['material']
            automatic_saved = next(r for r in pi.records() if r['status']=='published' and r['token']==automatic['token'])
            assert automatic_saved['metadata']['pi']['trigger']=='settlement' and automatic_saved['metadata']['pi']['mode']=='full'
            pi.setting('completed', False)
            # Disable automation without changing captured generation settings: the
            # first matching manual full after that policy change publishes; then reuse.
            pi.send('/recap full')
            pi.wait(lambda: len(pi.envelopes()) == 4 and pi.terminal(pi.envelopes()[-1]['token']), 'full-current policy-change capture missing')
            assert pi.terminal(pi.envelopes()[-1]['token'])['status']=='published'
            count = len(pi.calls()); envelopes = len(pi.envelopes())
            pi.send('/recap full', 1); pi.send('/recap', 1)
            assert len(pi.calls())==count and len(pi.envelopes())==envelopes
            observations.append({'manual_full_current_published':True,'automatic_full_current_published':True,'full_reuse_zero_calls':True,'incremental_after_full_no_new':True,'archived_originals_excluded':True})
            if not full_only:
                # Same current projection, virtual selection, real SDK/helper/CLI.
                pi.send('/recap settings')
                for _ in range(2): os.write(pi.master, b'\x1b[B'); pi.collect(.1)
                pi.send(''); pi.send('')
                pi.wait(lambda: 'Follow current Pi model' in pi.visible(), 'model picker not open')
                for _ in range(5): os.write(pi.master, b'\x1b[B'); pi.collect(.1)
                pi.send(''); os.write(pi.master, b'\x1b'); pi.collect(.5)
                pi.send('Inspect newer', 1); pi.send('/recap')
                pi.wait(lambda: len([r for r in pi.records() if r['status']=='published']) == 5, 'virtual current context failed')
                assert any(e['event']=='preflight' for e in pi.receipts())
                # Actual routed call checks a smaller physical window than preflight.
                pi.setting('options', {'thinkingLevel':'off','maxTokens':256})
                pi.send('Inspect older', 1)
                (root / 'smaller-route').touch(); pi.send('/recap')
                pi.wait(lambda: len(pi.envelopes()) == 6 and pi.terminal(pi.envelopes()[-1]['token']), 'small routed failure missing')
                assert pi.terminal(pi.envelopes()[-1]['token'])['failure']['reason'] == 'context_limit'
                assert len([r for r in pi.records() if r['status']=='published']) == 5
                (root / 'smaller-route').unlink()
                # Recognized model-side rejection is safe and actionable, not leaked.
                (root / 'context-rejection').touch(); pi.send('/recap')
                pi.wait(lambda: len(pi.envelopes()) == 7 and pi.terminal(pi.envelopes()[-1]['token']), 'provider context rejection missing')
                assert pi.terminal(pi.envelopes()[-1]['token'])['failure']['reason'] == 'context_limit'
                pi.wait(lambda: 'routed model context window' in '\n'.join(screen.screen.display), 'safe context-limit UI missing')
                (root / 'context-rejection').unlink()
                (root / 'private-error').touch(); pi.send('/recap')
                pi.wait(lambda: len(pi.envelopes()) == 8 and pi.terminal(pi.envelopes()[-1]['token']), 'unknown private failure missing')
                assert 'reason' not in pi.terminal(pi.envelopes()[-1]['token'])['failure']
                (root / 'private-error').unlink()
                pi.send('/recap')
                pi.wait(lambda: len([r for r in pi.records() if r['status']=='published']) == 6, 'failure-preserving follow-up missing')
                assert 'FACT_topic=older' in pi.envelopes()[-1]['material']
                for sentinel in ('PRIVATE_CONTEXT_SENTINEL', 'PRIVATE_STDERR_SENTINEL', 'PRIVATE_PROVIDER_SENTINEL'):
                    assert sentinel not in pi.visible() + json.dumps(pi.records()) + json.dumps(pi.receipts())
                    assert all(sentinel not in p.read_text() for p in (root / 'sessions').rglob('*.jsonl'))
                pi.assert_no_transcript_output()
                observations.append({'no_new_calls':0,'fresh_fact':True,'virtual_published':True,'smaller_actual_route_refused':True,'model_rejection_safe':True,'unknown_provider_redacted':True,'failure_preserving_followup':True})
        assert session.read_bytes().startswith(original), 'retained archive rewritten'
        observations.append({'archive_prefix_unchanged':True})
        print(json.dumps({'status':'EXPECTED_FAIL_BEFORE' if before else 'PASS','observations':observations}))
    finally:
        (evidence/'observations.json').write_text(json.dumps(observations,indent=2))
        (evidence/'ui.ansi').write_bytes(pi.output)
        (evidence/'transport.jsonl').write_text(pi.transport.read_text() if pi.transport.exists() else '')
        (evidence/'provider.jsonl').write_text(pi.log.read_text() if pi.log.exists() else '')
        (evidence/'records.json').write_text(json.dumps(pi.records(),indent=2))
        screen.capture('final-or-failed')
        (evidence/'frames.json').write_text(json.dumps(screen.frames,ensure_ascii=False))
        pi.close()
assert not root.exists()
(evidence/'cleanup.json').write_text(json.dumps({'private_root_removed':True}))
