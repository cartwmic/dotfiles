#!/usr/bin/env python3
"""Focused genuine Pi/CLI regressions for interpreter, unfinished output and limits."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from public_helpers import PublicPi, ROOT


def published(pi):
    return [r for r in pi.records() if r['status'] == 'published']


def recap(pi, full=False):
    before = len(pi.envelopes())
    pi.send('/recap full' if full else '/recap', 1)
    pi.wait(lambda: len(pi.envelopes()) > before, 'public recap did not hand off', 12)
    token = pi.envelopes()[-1]['token']
    pi.wait(lambda: pi.terminal(token), 'public recap did not finish')
    return token


def run(case):
    sources = ['dot_local/bin/executable_session-recap', 'dot_pi/private_agent/extensions/recap/index.ts', 'dot_pi/private_agent/extensions/recap/helpers.ts', 'dot_pi/private_agent/extensions/recap/backend.mjs', 'tests/pi-recap/limits.py', 'tests/pi-recap/public_helpers.py', 'tests/pi-recap/public_fixture.ts']
    observations = {'source_sha256': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources}}
    with tempfile.TemporaryDirectory(prefix='recap-limits-') as temporary:
        root = Path(temporary)
        env = {}
        if case.startswith('python'):
            old = root / 'old-bin'; old.mkdir()
            (old / 'python3').write_text('#!/bin/sh\necho "Python lacks tomllib" >&2\nexit 1\n')
            (old / 'python3').chmod(0o700)
            selected = root / ('compatible' if case.endswith('explicit') else '.local/share/mise/shims/python3')
            selected.parent.mkdir(parents=True, exist_ok=True)
            selected.write_text('#!/bin/sh\nprintf "%s\\n" "$1" >> "' + str(root / 'python-selection') + '"\nexec "' + sys.executable + '" "$@"\n')
            selected.chmod(0o700)
            env['PATH'] = str(old) + ':' + os.environ['PATH']
            env['SESSION_RECAP_PYTHON'] = str(selected) if case.endswith('explicit') else ''
        budget_case = case.startswith('budget')
        if budget_case:
            env.update(RECAP_PROOF_CONTEXT='4096', RECAP_PROOF_MAX_OUTPUT='512')
        config = {'inputBudget': 24000} if budget_case else None
        if case.startswith('budget-virtual'):
            config['model'] = dict(provider='recap-router', id='auto')
        pi = PublicPi(root, environment=env, config=config)
        try:
            pi.send('orchard'); pi.wait(lambda: any(e['event'] == 'settled' for e in pi.events()), 'main did not settle')
            token = recap(pi)
            assert pi.terminal(token)['status'] == 'published', 'compatible interpreter did not save'
            saved = published(pi)
            assert len(saved) == 1 and 'tool confirmed orchard-checks-passed' in saved[0]['summary']
            assert len([e for e in pi.events() if e['event'] == 'call' and e.get('model') == 'main']) == 2
            pi.assert_no_transcript_output()
            if case.startswith('python'):
                selection = (root / 'python-selection').read_text().splitlines()
                assert any(s.endswith('observe.py') for s in selection), 'script override not honored'
                assert len(selection) >= 4, 'control and detached path did not share interpreter'
                observations['selected_invocations'] = len(selection)
            elif budget_case and case == 'budget-virtual-preflight':
                pi.send('harbor'); pi.wait(lambda: len([e for e in pi.events() if e['event'] == 'settled']) == 2, 'second turn did not settle')
                baseline = (len(pi.envelopes()), len(pi.calls()), len(published(pi)))
                (root / 'budget-gate').touch()
                pi.send('/recap')
                pi.wait(lambda: any(e['event'] == 'budget-wait' for e in pi.events()), 'preflight never gated')
                pi.send('/new', 2)
                pi.send('/resume', 2); pi.send('', 2)
                (root / 'budget-gate').unlink(); pi.collect(3)
                pi.wait(lambda: len(published(pi)) == baseline[2] + 1, 'uncanceled captured preflight lost after departure')
                assert (len(pi.envelopes()), len(pi.calls()), len(published(pi))) == tuple(n + 1 for n in baseline)
                pi.send('/recap', 2); pi.redraw()
                assert 'No new activity.' in pi.visible()
                assert (len(pi.envelopes()), len(pi.calls()), len(published(pi))) == tuple(n + 1 for n in baseline), 'saved original coverage duplicated work'
                final = next(r for r in published(pi) if r['record_id'] != saved[0]['record_id'])
                assert 'harbor-deployment-unfinished' in final['summary'] and 'harbor' in pi.envelopes()[-1]['material']
                pi.assert_no_transcript_output()
                observations.update(captured_preflight_survived=True, original_coverage_recovered=True, no_duplicate_followup=True)
            elif budget_case and case == 'budget-refusal':
                pi.send('harbor'); pi.wait(lambda: len([e for e in pi.events() if e['event'] == 'settled']) == 2, 'second turn did not settle')
                baseline = (len(pi.envelopes()), len(pi.calls()), len(published(pi)))
                config_path = pi.extension / 'config.json'
                original = config_path.read_text()
                invalid = json.loads(original); invalid['model']['id'] = 'missing'
                config_path.write_text(json.dumps(invalid))
                start = len(pi.output); pi.send('/recap', 4)
                assert 'unavailable or unusable; coverage unchanged' in pi.visible(start)
                assert (len(pi.envelopes()), len(pi.calls()), len(published(pi))) == baseline, 'unknown selection fell back or saved'
                assert json.loads(config_path.read_text())['model']['id'] == 'missing', 'unknown choice mutated'
                invalid['model']['id'] = 'unusable'
                config_path.write_text(json.dumps(invalid))
                start = len(pi.output); pi.send('/recap', 2); pi.redraw()
                assert 'unavailable or unusable; coverage unchanged' in pi.visible(start)
                assert (len(pi.envelopes()), len(pi.calls()), len(published(pi))) == baseline, 'unknown limits fell back or saved'
                assert json.loads(config_path.read_text())['model']['id'] == 'unusable', 'unusable choice mutated'
                config_path.write_text(original)
                follow = recap(pi)
                assert pi.terminal(follow)['status'] == 'published'
                final = next(r for r in published(pi) if r['record_id'] != saved[0]['record_id'])
                assert 'harbor-deployment-unfinished' in final['summary'] and 'harbor' in pi.envelopes()[-1]['material']
                pi.assert_no_transcript_output()
                observations.update(unknown_unusable_no_fallback=True, prior_history_preserved=True, pending_coverage=True, safe_followup=True)
            elif budget_case:
                initial_token = pi.envelopes()[-1]['token']
                initial_budget = next((e['input_budget_bytes'] for e in pi.receipts() if e['event'] == 'preflight' and e['token'] == initial_token), pi.envelopes()[-1]['budget'])
                initial_output = pi.calls()[-1]['maxTokens']
                if case.endswith('explicit'):
                    pi.setting('inputBudget', 18000)
                    pi.setting('options', dict(thinkingLevel='off', maxTokens=256))
                (root / 'oversized').touch()
                pi.send('harbor'); pi.wait(lambda: len([e for e in pi.events() if e['event'] == 'settled']) == 2, 'second turn did not settle')
                calls = len(pi.calls())
                failed = recap(pi)
                envelope = pi.envelopes()[-1]
                assert 4096 < len(envelope['material'].encode()) < 24000, 'fixture not above real context and below old default'
                off_status = pi.terminal(failed)['status']
                off_calls = len(pi.calls()) - calls
                off_published = len(published(pi))
                has_failure = any(r['status'] == 'failed' for r in pi.records())
                pi.setting('recursion', True)
                follow = recap(pi, full=True)
                observations.update(initial_budget=initial_budget, initial_output=initial_output, source_bytes=len(envelope['material'].encode()), off_status=off_status, off_calls=off_calls, on_status=pi.terminal(follow)['status'], on_reduction_calls=sum(c['reduction'] for c in pi.calls()))
                assert initial_budget < 4096, 'physical input context limit bypassed'
                assert initial_output <= 512, 'physical output allowance bypassed'
                assert off_status == 'failed' and off_calls == 0, 'oversized recursion-off material reached provider'
                assert off_published == 1 and has_failure, 'failure changed successful history'
                assert pi.terminal(follow)['status'] == 'published', 'bounded small-model reduction did not save'
                final = next(r for r in published(pi) if r['record_id'] != saved[0]['record_id'])
                for fact in ('harbor-checks-passed', 'harbor-deployment-unfinished', 'harbor-review-before-deploy'):
                    assert fact in final['summary'], 'reduction omitted pending fact'
                assert final['reduced']
                assert sum(c['reduction'] for c in pi.calls()) >= 2, 'chunks not reduced'
                before_reuse = (len(pi.calls()), len(published(pi)))
                pi.send('/recap full', 3)
                assert (len(pi.calls()), len(published(pi))) == before_reuse, 'full reuse generated or duplicated'
                pi.send('/recap', 2)
                assert (len(pi.calls()), len(published(pi))) == before_reuse, 'no-new generated or duplicated'
                assert 'harbor' in pi.envelopes()[-1]['material'] and 'orchard' in pi.envelopes()[-1]['background']
                assert all(c['maxTokens'] <= (256 if case.endswith('explicit') and c['number'] > 1 else 512) for c in pi.calls())
                assert len([e for e in pi.events() if e['event'] == 'call' and e.get('model') == 'main']) == 4
                pi.assert_no_transcript_output()
                observations.update(input_budget=envelope['budget'], output_allowance=pi.calls()[-1]['maxTokens'], source_bytes=len(envelope['material'].encode()), off_no_call=True, on_all_chunks=True, no_save_failure_history=True, pending_coverage=True, safe_followup=True)
            else:
                stage = case.split('-', 1)[1]
                if stage == 'reduction':
                    (root / 'oversized').touch()
                    pi.setting('recursion', True)
                pi.send('harbor'); pi.wait(lambda: len([e for e in pi.events() if e['event'] == 'settled']) == 2, 'second turn did not settle')
                (root / 'unfinished').write_text(stage)
                calls = len(pi.calls())
                failed = recap(pi)
                assert pi.terminal(failed)['status'] == 'failed', 'unfinished narrative published'
                assert len(pi.calls()) == calls + 2, 'unfinished output did not get exactly one retry'
                assert len(published(pi)) == 1 and published(pi)[0]['record_id'] == saved[0]['record_id'], 'failure changed successful history'
                assert any(r['status'] == 'failed' for r in pi.records()), 'safe failure history absent'
                assert 'harbor' in pi.envelopes()[-1]['material']
                (root / 'unfinished').unlink()
                follow = recap(pi)
                assert pi.terminal(follow)['status'] == 'published', 'safe follow-up failed'
                final = next(r for r in published(pi) if r['record_id'] != saved[0]['record_id'])
                for fact in ('harbor-checks-passed', 'harbor-deployment-unfinished', 'harbor-review-before-deploy'):
                    assert fact in final['summary'], 'pending work omitted'
                assert 'harbor' in pi.envelopes()[-1]['material'] and 'orchard' in pi.envelopes()[-1]['background'], 'coverage advanced on failure'
                assert len([e for e in pi.events() if e['event'] == 'call' and e.get('model') == 'main']) == 4
                pi.assert_no_transcript_output()
                observations.update(unfinished_stage=stage, no_save=True, one_retry=True, failure_history=True, pending_coverage=True, safe_followup=True)
            observations.update(status='PASS', case=case, saved=len(published(pi)), no_extra_turn=True)
        except Exception as exc:
            observations.update(status='FAIL', case=case, reason=str(exc), envelopes=len(pi.envelopes()), published=len(published(pi)), budgets=[e['budget'] for e in pi.envelopes()], output_allowances=[e.get('maxTokens') for e in pi.calls()], terminals=[e for e in pi.receipts() if e['event'] == 'terminal'], ui=pi.visible()[-5000:])
            raise
        finally:
            (root / 'budget-gate').unlink(missing_ok=True)
            pi.close()
            observations['cleanup'] = 'owned Pi and supervising jobs stopped; private tree removed'
            print(json.dumps(observations), flush=True)


if __name__ == '__main__':
    run(sys.argv[1])
