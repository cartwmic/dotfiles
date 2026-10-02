#!/usr/bin/env python3
"""Pi-owned public settings: oversized manual/automatic refusal, reduction, deadline."""
import json
from pathlib import Path
import sys
import tempfile
from public_helpers import PublicPi

observations = []
evidence = []
for trigger, topic in [('manual', 'orchard'), ('settlement', 'harbor')]:
    with tempfile.TemporaryDirectory(prefix='recap-recursion-') as temporary:
        root = Path(temporary)
        pi = PublicPi(root, oversized=True)
        try:
            pi.send('Initialize proof')
            pi.wait(lambda: any(e['event'] == 'settled' for e in pi.events()), 'initial session not persisted')
            if trigger == 'settlement': pi.setting('completed', True)
            pi.setting('recursion', False)
            pi.send('Inspect ' + topic)
            pi.wait(lambda: sum(e['event'] == 'settled' for e in pi.events()) == 2, 'main work never settled')
            if trigger == 'manual': pi.send('/recap')
            pi.wait(lambda: len(pi.envelopes()) == 1, 'oversized request not delivered')
            off = pi.envelopes()[0]
            pi.wait(lambda: pi.terminal(off['token']), 'off refusal never finished')
            assert off['recursive'] is False and len(off['material'].encode()) > off['budget']
            assert pi.terminal(off['token'])['status'] == 'failed'
            failed = [r for r in pi.records() if r['token'] == off['token']]
            assert len(failed) == 2 and {r['attempt'] for r in failed} == {1, 2}
            assert all(r['status'] == 'failed' and r['failure']['message'] == 'recap generation failed' for r in failed)
            assert 'recursive reduction is disabled' in pi.terminal(off['token'])['failure']['message']
            assert not pi.calls() and not any(r['status'] == 'published' for r in pi.records()), 'off truncated or published'
            pi.wait(lambda: 'coverage unchanged' in pi.visible(), 'off refusal not visible', 5)

            pi.setting('recursion', True)
            before = len(pi.output)
            if trigger == 'manual': pi.send('/recap')
            else: pi.send('Continue inspecting ' + topic)
            pi.wait(lambda: len(pi.envelopes()) == 2, 'on request not captured')
            on = pi.envelopes()[-1]
            assert on['recursive'] is True and on['budget'] == off['budget']
            assert off['material'] in on['material'], 'off request incorrectly advanced coverage'
            pi.wait(lambda: pi.terminal(on['token']), 'recursive request did not finish')
            assert pi.terminal(on['token'])['status'] == 'published', pi.terminal(on['token'])
            pi.wait(lambda: '[Input was recursively chunked and reduced.]' in pi.visible(before), 'saved reduction not displayed', 5)
            record, = [r for r in pi.records() if r['token'] == on['token'] and r['status'] == 'published']
            assert record['reduced'] is True and record['metadata']['pi']['trigger'] == trigger
            calls = pi.calls()
            reductions = [c for c in calls if c['reduction']]
            assert len(reductions) >= 2 and len([c for c in calls if not c['reduction']]) == 1, 'no real chunk/final calls'
            header = 'Reduce this complete chunk, preserving meaningful facts, identifiers, outcomes, uncertainties and unresolved work. Do not omit unresolved material.\n\n'
            assert ''.join(c['prompt'][len(header):] for c in reductions) == on['material'], 'chunking dropped or fabricated source'
            assert all(len(c['prompt'].encode()) <= on['budget'] for c in calls), 'backend budget exceeded'
            for text in [record['summary'], pi.visible(before)]:
                assert '[Input was recursively chunked and reduced.]' in text
                assert f'Observed {topic}:' in text and f'{topic}-checks-passed' in text
                assert f'{topic}-deployment-unfinished' in text and f'Next: {topic}-review-before-deploy.' in text
            observations.append(trigger + '-public-setting-off-refuses-on-complete-chunks-input-derived-disclosed-narrative')

            # Each backend call can succeed inside the timeout, yet several calls
            # cannot finish within one attempt. Both attempts restart reduction;
            # the attempt's clock must not restart at each chunk or final request.
            pi.setting('timeoutSeconds', 4)
            pi.slow.touch()
            count = len(pi.envelopes()); calls_before = len(pi.calls())
            pi.send('Inspect ' + topic + ' follow-up')
            pi.wait(lambda: sum(e['event'] == 'settled' for e in pi.events()) >= (3 if trigger == 'manual' else 4), 'follow-up never settled')
            if trigger == 'manual': pi.send('/recap')
            pi.wait(lambda: len(pi.envelopes()) == count + 1, 'deadline request not captured')
            timed = pi.envelopes()[-1]
            pi.wait(lambda: pi.terminal(timed['token']), 'whole-attempt deadline did not stop recursion', 15)
            terminal = pi.terminal(timed['token'])
            attempts = [r for r in pi.records() if r['token'] == timed['token']]
            assert len(attempts) == 2 and {r['attempt'] for r in attempts} == {1, 2}, 'missing or excessive retry'
            assert all(r['status'] == 'failed' and r['failure']['reason'] == 'timed_out' for r in attempts), attempts
            elapsed = terminal['time'] - timed['time']
            assert 7.6 <= elapsed < 11, ('deadline reset inside recursion or final call', elapsed)
            stint = pi.calls()[calls_before:]
            responses = [e for e in pi.events() if e['event'] == 'response' and e.get('number') in {c['number'] for c in stint}]
            assert len(stint) >= 6 and len(responses) >= 4, 'did not exercise successful recursive calls then timeout/retry'
            assert len([c for c in stint if not c['reduction']]) == 2 and all(e['reduction'] for e in responses), 'whole-attempt timeout did not include both final calls after reduction'
            effective = ('Background only (not new activity):\n' + timed['background'] + '\n\nNew material:\n' if timed['background'] else '') + timed['material']
            first_chunks = [c for c in stint if c['prompt'].startswith(header + effective[:100])]
            assert len(first_chunks) == 2, 'retry did not restart the complete captured material'
            assert len([r for r in pi.records() if r['status'] == 'published']) == 1, 'timeout established coverage'

            pi.slow.unlink(); pi.setting('timeoutSeconds', 40)
            count = len(pi.envelopes()); before = len(pi.output); follow_calls_start = len(pi.calls())
            if trigger == 'manual': pi.send('/recap')
            else: pi.send('Resume inspecting ' + topic)
            pi.wait(lambda: len(pi.envelopes()) == count + 1, 'safe follow-up not captured')
            follow = pi.envelopes()[-1]
            assert timed['material'] in follow['material'], 'timeout covered unfinished scope'
            pi.wait(lambda: pi.terminal(follow['token']), 'safe follow-up did not finish')
            assert pi.terminal(follow['token'])['status'] == 'published'
            pi.wait(lambda: '[Input was recursively chunked and reduced.]' in pi.visible(before), 'follow-up not displayed', 5)
            assert f'Observed {topic}:' in pi.visible(before) and 'recursively chunked and reduced' in pi.visible(before)
            saved = [r for r in pi.records() if r['status'] == 'published']
            assert len(saved) == 2
            count = len(pi.calls()); envelopes = len(pi.envelopes()); before = len(pi.output)
            pi.send('/recap', 2)
            assert len(pi.calls()) == count and len(pi.envelopes()) == envelopes and 'No new activity' in pi.visible(before), 'new successful coverage not authoritative'
            pi.assert_no_transcript_output()
            observations.append(trigger + '-whole-recursive-attempt-deadline-one-retry-uncovered-safe-followup-no-duplicate')
            evidence.append(dict(trigger=trigger, topic=topic, off_recursive=off['recursive'], off_material_bytes=len(off['material'].encode()), input_budget=on['budget'], off_attempts=[r['attempt'] for r in failed], off_backend_calls=0, on_recursive=on['recursive'], on_material_bytes=len(on['material'].encode()), reduction_calls=len(reductions), reduction_chunk_bytes=[len(c['prompt'].encode()) for c in reductions], complete_chunk_material_match=True, published_summary=record['summary'], timeout_seconds=timed['timeout'], two_attempt_elapsed_seconds=round(elapsed, 3), timed_attempts=[r['attempt'] for r in attempts], timed_reduction_calls=sum(c['reduction'] for c in stint), timed_final_calls=sum(not c['reduction'] for c in stint), followup_source_retained=True, followup_backend_calls=len(pi.calls()) - follow_calls_start, subsequent_backend_calls=0))
        except Exception:
            print(json.dumps({'completed_cases': observations, 'receipts': [{k: v for k, v in e.items() if k not in ('material', 'background', 'instructions')} for e in pi.receipts()], 'recap_calls': len(pi.calls())}), file=sys.stderr)
            print(pi.visible()[-12000:], file=sys.stderr)
            raise
        finally:
            pi.close()
    assert not root.exists(), 'private fixture cleanup failed'
print(json.dumps({'status': 'PASS', 'cases': observations, 'observations': evidence, 'cleanup': 'private Pi/supervisors exited and resources removed'}))
