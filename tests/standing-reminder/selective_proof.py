#!/usr/bin/env python3
"""Selective cadence through isolated Pi, actual question UI and native codemode.

No live credentials, installed writes, or test-only production configuration hook.
Each scenario owns a private source copy, config, provider, editor and transcript.
"""
from __future__ import annotations
import argparse
import hashlib
import http.server
import json
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path
import proof as p

QUESTION = Path('/Users/cartwmic/.pi/agent/npm/node_modules/@juicesharp/rpiv-ask-user-question')
A = 'SELECTIVE current A\n  exact\tindent'
B = 'SELECTIVE superseded B'
C = 'SELECTIVE latest C\n  exact\tindent'
PARAMS = {'questions': [
    {'header': 'First', 'question': 'SELECTIVE-FIRST-QUESTION', 'options': [
        {'label': 'Alpha', 'description': 'Select alpha'}, {'label': 'Beta', 'description': 'Select beta'}]},
    {'header': 'Second', 'question': 'SELECTIVE-SECOND-QUESTION', 'options': [
        {'label': 'Gamma', 'description': 'Select gamma'}, {'label': 'Delta', 'description': 'Select delta'}]},
]}
CASES = ('direct', 'cancel', 'invalid', 'codemode', 'codemode-invalid', 'non-ui',
         'edits', 'clear', 'coalesce', 'operator-coalesce', 'rollback', 'lifecycle',
         'tool-config', 'message-config', 'empty-config', 'invalid-config',
         'default-exclusions', 'historical', 'unavailable', 'independence', 'warming')


def fingerprint(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.rglob('*')):
        if path.is_file() and 'node_modules' not in path.relative_to(directory).parts:
            digest.update(str(path.relative_to(directory)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def projections(body):
    return [(i, p.as_text(m.get('content'))) for i, m in enumerate(body['messages'])
            if '<standing-reminder>' in p.as_text(m.get('content'))]


def assert_value(body, value, count):
    found = projections(body)
    p.require(len(found) == count, f'expected {count} projections, got {found}')
    p.require(all(text == f'<standing-reminder>\n{value}\n</standing-reminder>' for _, text in found),
              'stale or inexact projection')


FIXTURE = r'''import { appendFileSync } from 'node:fs';
import { Type } from 'typebox';
export default function(pi) {
 const log = (v) => appendFileSync(process.env.STANDING_PROOF_TRACE, JSON.stringify(v)+'\n');
 pi.events.on('rpiv:ask-user:blocked', e=>log({kind:'question_blocked',active:e.active}));
 // Exercise the actual package's no-UI backstop, which its reconciler normally
 // hides. Public tool activation only: do not replace/wrap its execute function.
 pi.on('before_agent_start', (_,ctx)=>{
   if (process.env.STANDING_SELECTIVE_NON_UI==='1' && !ctx.hasUI)
     pi.setActiveTools([...new Set([...pi.getActiveTools(),'ask_user_question'])]);
 });
 pi.on('tool_execution_end', e => log({kind:'execution_end', name:e.toolName, id:e.toolCallId,
   parent:e.parentToolCallId ?? null, error:e.isError}));
 pi.registerCommand('fixture-notify', {description:'UI-only notification', handler:async(_,ctx)=>ctx.ui.notify('SELECTIVE-NOTIFY')});
 pi.registerCommand('fixture-extension', {description:'Real extension-origin request', handler:async()=>
   pi.sendUserMessage('SELECTIVE-EXTENSION-ONLY',{deliverAs:'followUp'})});
 pi.registerCommand('fixture-custom', {description:'Append actual model-visible custom message', handler:async()=>
   pi.sendMessage({customType:'selective-fixture',content:'SELECTIVE-CUSTOM',display:false}, {triggerTurn:false})});
 for (const name of ['selective_tool','subagent']) pi.registerTool({name,label:name,description:'Deterministic proof result',
   parameters:Type.Object({}), async execute(){return {content:[{type:'text',text:'SELECTIVE-'+name+'-RESULT'}],details:{}};}});
}
'''


class Provider(p.ScriptedProvider):
    def __init__(self, case, root):
        self.case, self.root = case, root
        self.work = []
        self.receipt = None
        super().__init__()

    def calls(self):
        case = self.case
        gate = {'command': f"printf ready > '{self.root}/tool-ready'; while [ ! -f '{self.root}/tool-release' ]; do sleep 0.05; done; printf SELECTIVE-GATED-RESULT"}
        question = PARAMS if case not in ('invalid', 'codemode-invalid') else {'questions': []}
        if case in ('direct','cancel','invalid','coalesce','operator-coalesce','clear'):
            return [('ask_user_question', question), ('bash', gate)]
        if case in ('codemode','codemode-invalid','non-ui'):
            return [('codemode', {'code': 'try { text(await tools.ask_user_question('+json.dumps(question)+')); } catch(e) { text("QUESTION-ERROR: "+e.message); } text(await tools.bash('+json.dumps(gate)+'));'})]
        if case == 'tool-config':
            return [('selective_tool', {})]
        if case == 'default-exclusions':
            return [('subagent', {}), ('bash', gate)]
        return [('bash', gate)]

    def make_handler(self):
        server = self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_POST(self):
                try:
                    body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    with server.lock: server.requests.append(body)
                    latest = p.latest_user_text(body)
                    p.sse_start(self)
                    if server.case == 'warming':
                        server_max = body.get('max_tokens', body.get('max_completion_tokens'))
                        if server_max == 1:
                            p.require(not projections(body), 'idle warming received pending reminder')
                        p.sse(self, {})
                        self.wfile.write(('data: '+json.dumps({'id':'warm-usage','object':'chat.completion.chunk',
                            'choices':[], 'usage':{'prompt_tokens':1000,'completion_tokens':1,'total_tokens':1001}})+'\n\n').encode())
                        self.wfile.flush()
                    if p.is_compaction_request(body):
                        p.require(not projections(body), 'summary received reminder')
                        p.sse_text(self,'SELECTIVE-SUMMARY'); p.sse_finish(self); return
                    if latest.startswith('SELECTIVE-WORK') or 'SELECTIVE-WORK' in p.request_text(body):
                        server.work.append(body)
                        step = len(server.work)
                        if step == 1:
                            calls = server.calls()
                            for i,(name,args) in enumerate(calls):
                                p.sse(self, {'tool_calls':[{'index':i,'id':f'selective-root-{i}','type':'function',
                                    'function':{'name':name,'arguments':json.dumps(args)}}]})
                            p.sse_finish(self,'tool_calls'); return
                        if step == 2:
                            tools = [m for m in body['messages'] if m.get('role')=='tool']
                            p.require(all(any(m.get('tool_call_id') == f'selective-root-{i}' for m in tools)
                                          for i in range(len(server.calls()))), 'request before complete root batch')
                            server.receipt = '\n'.join(p.as_text(m.get('content')) for m in tools)
                            p.sse(self, {'tool_calls':[{'index':0,'id':'selective-ordinary','type':'function',
                                'function':{'name':'bash','arguments':json.dumps({'command':'printf SELECTIVE-ORDINARY-RESULT'})}}]})
                            p.sse_finish(self,'tool_calls'); return
                        p.require(step == 3, 'unexpected forced request')
                        p.require('SELECTIVE-ORDINARY-RESULT' in p.request_text(body), 'ordinary tool did not finish')
                        p.sse_text(self,'SELECTIVE-COMPLETED-WORK'); p.sse_finish(self); return
                    p.sse_text(self,'PROOF-SCRIPTED-ANSWER SELECTIVE-COMPLETED-OPERATOR'); p.sse_finish(self)
                except Exception as exc:
                    with server.lock: server.errors.append(str(exc))
                    try: p.sse_text(self,'SELECTIVE-FAILED'); p.sse_finish(self)
                    except OSError: pass
        return Handler


class Run(p.ProofRun):
    def env(self):
        env=super().env()
        if self.provider.case=='non-ui': env['STANDING_SELECTIVE_NON_UI']='1'
        return env

    def launch_tui(self, **kwargs):
        starts=sum(r.get('kind')=='session_start' for r in self.trace.records())
        tui=super().launch_tui(**kwargs)
        self.trace.wait_count(lambda r:r.get('kind')=='session_start', starts+1, 'loaded TUI session')
        return tui

    def argv(self, **kwargs):
        args = super().argv(**kwargs)
        args[args.index('--tools')+1] = 'bash,codemode,ask_user_question,selective_tool,subagent'
        args.extend(['--extension', str(QUESTION/'index.ts'), '--extension','builtin:codemode',
                     '--extension',str(self.root/'fixture.ts')])
        return args


def stage(root, config=None):
    target = root/'source-extension'
    shutil.copytree(p.EXTENSION.parent, target)
    shutil.copytree(p.EXTENSION.parent.parent/'inspect-prompt', root/'inspect-prompt')
    (target/'config.json').write_text(json.dumps({'triggers':['tool-result:ask_user_question']} if config is None else config))
    return target/'index.ts'


def stable_count(run, expected):
    time.sleep(.35)
    p.require(len(run.provider.snapshot()) == expected,
              f'forced/unexpected request: expected {expected}, got {len(run.provider.snapshot())}')


def save(run,tui):
    offset = run.next_editor(tui)
    tui.wait_output_since(offset,'applies to next normal request')


def scenario(case, root):
    config = {'tool-config':{'triggers':['tool-result:selective_tool']},
              'message-config':{'triggers':['message:selective-fixture']},
              'historical':{'triggers':['message:selective-fixture']},
              'empty-config':{'triggers':[]}, 'invalid-config':{'triggers':['notification:*']}}.get(case)
    extension = stage(root,config)
    print(f'Case {case}: source-loaded extension={extension}; adjacent config={extension.parent / "config.json"}',flush=True)
    provider = Provider(case,root)
    run = Run(root,provider,provider.start(),extension)
    run.setup()
    if case == 'warming':
        (run.agent/'settings.json').write_text(json.dumps({'cacheWarming':'idle'}))
        models=json.loads((run.agent/'models.json').read_text())
        model=models['providers']['standing-proof']['models'][0]
        model['promptCache']={'short':12,'long':12}
        model['cost']={'input':1000,'output':0,'cacheRead':0,'cacheWrite':0}
        (run.agent/'models.json').write_text(json.dumps(models))
    p.write_exec(root/'observer.ts',p.OBSERVER_SOURCE)
    p.write_exec(root/'fixture.ts',FIXTURE)
    plan = [{'text':A},{'text':B},{'text':C},{'write':False},
            {'draft':'SELECTIVE-FAILED-DRAFT','text':'SELECTIVE-FAILED-DRAFT','code':23}]
    if case == 'rollback': plan = [plan[0],plan[3],plan[4]]
    run.editor_plan.write_text(json.dumps(plan))
    try:
        if case == 'non-ui': (root/'tool-release').touch()
        tui = run.launch_tui(session_id='selective-'+case)
        run.trace.wait(lambda r:r.get('kind')=='session_start','loaded session')
        tui.wait_output('No session reminder')
        if case == 'invalid-config': tui.wait_output('Invalid standing-reminder')
        run.prompt_and_wait(tui,'SELECTIVE-INITIALIZE')
        sid = run.session_id_for(tui)
        save(run,tui)
        if case in ('lifecycle','historical','unavailable','independence','warming'):
            lifecycle(case,run,tui,sid)
            return
        if case == 'non-ui':
            tui.stop(); run.tui=None
            before = len(provider.snapshot())
            result = __import__('subprocess').run(run.argv(session=run.session_file(sid))+['--print','SELECTIVE-WORK'],
                       cwd=run.project,env=run.env(),capture_output=True,text=True,timeout=p.TIMEOUT)
            p.require(result.returncode==0 and 'SELECTIVE-COMPLETED-WORK' in result.stdout,'non-UI work incomplete: '+result.stderr[-1000:])
            p.require('UI not available' in (provider.receipt or ''), 'actual installed tool no-UI rejection missing')
        else:
            before = len(provider.snapshot())
            settled = sum(r.get('kind')=='agent_settled' for r in run.trace.records())
            output = tui.output_length()
            tui.send('SELECTIVE-WORK')
            provider.wait_count(before+1)
            original = json.dumps(provider.work[0],sort_keys=True)
            assert_value(provider.work[0],A,1)
            if case in ('direct','cancel','coalesce','operator-coalesce','codemode','clear'):
                run.trace.wait(lambda r:r.get('kind')=='question_blocked' and r.get('active'),'actual questionnaire open')
                time.sleep(.25)
                tui.wait_output('SELECTIVE-FIRST-QUESTION')
                stable_count(run,before+1)
                if case == 'cancel': tui.key(b'\x1b')
                else:
                    tui.key(b'\r'); tui.wait_output('SELECTIVE-SECOND-QUESTION')
                    stable_count(run,before+1)  # individual tab is not a result
                    tui.key(b'\r'); time.sleep(.15); stable_count(run,before+1)
                    tui.key(b'\r')  # submit complete questionnaire
            if case != 'tool-config':
                p.wait_for(lambda:(root/'tool-ready').exists(),'already-running gated tool')
            if case in ('edits','coalesce','operator-coalesce'):
                save(run,tui); save(run,tui)
                p.require(run.saved_state(sid)=={'version':1,'reminder':C,'pending':True},'latest pending state not C')
            if case == 'operator-coalesce':
                tui.send('SELECTIVE-QUEUED-OPERATOR')
                run.trace.wait(lambda r:r.get('kind')=='input' and r.get('text')=='SELECTIVE-QUEUED-OPERATOR','queued operator')
            if case == 'clear':
                tui.send('/reminder-clear'); tui.wait_output('Reminder cleared; applies to the next normal request')
            if case == 'rollback':
                prior=run.saved_state(sid)
                run.next_editor(tui,expect_warning='Reminder unchanged')
                p.require(run.saved_state(sid)==prior,'unchanged close queued a save')
                invocation, offset=run.start_editor(tui)
                run.trace.wait(lambda r:r.get('kind')=='editor_draft_saved' and r.get('invocation')==invocation,
                               'failed draft while editor open',editor=True)
                p.require(run.saved_state(sid)==prior,'draft became current before close')
                stable_count(run,before+1)
                run.close_editor(tui,invocation,offset,expect_warning='Reminder edit canceled')
                p.require(run.saved_state(sid)==prior,'failed draft changed saved state')
            if case in ('message-config','default-exclusions'):
                tui.send('/fixture-notify'); tui.wait_output('SELECTIVE-NOTIFY')
                tui.send('/fixture-custom'); time.sleep(.2)
            if case != 'tool-config':
                stable_count(run,before+1)
                (root/'tool-release').touch()
            p.require(json.dumps(provider.work[0],sort_keys=True)==original,'earlier request body changed')
            run.trace.wait_count(lambda r:r.get('kind')=='agent_settled',settled+1,'completed work')
            tui.wait_output_since(output,'SELECTIVE-COMPLETED-WORK')
        stable_count(run,before+3)
        p.require(len(provider.work)==3,'did not complete exactly root, handoff and ordinary continuation')
        handoff,ordinary = provider.work[1:]
        count = 2 if case in ('direct','cancel','invalid','codemode','codemode-invalid','non-ui','tool-config','message-config') else 1
        value = C if case in ('edits','coalesce','operator-coalesce') else A
        if case == 'clear': count=0
        assert_value(handoff,value,count); assert_value(ordinary,value,count)
        p.require(ordinary['messages'][:len(handoff['messages'])] == handoff['messages'],
                  'ordinary continuation rewrote established request prefix/anchor placement')
        if count==2:
            last_tool = max(i for i,m in enumerate(handoff['messages']) if m.get('role')=='tool')
            p.require(sum(i>last_tool for i,_ in projections(handoff))==1,'not exactly one fresh reminder after complete batch')
        if case in ('direct','codemode','coalesce','operator-coalesce','clear'):
            p.require('"SELECTIVE-FIRST-QUESTION"="Alpha"' in provider.receipt and '"SELECTIVE-SECOND-QUESTION"="Gamma"' in provider.receipt,
                      'actual multi-tab answer envelope missing')
            p.require(any(r.get('kind')=='question_blocked' and r.get('active') is False for r in run.trace.records()),
                      'actual questionnaire did not close')
        if case in ('cancel','invalid','codemode-invalid'):
            root_result = next(m for m in handoff['messages']
                               if m.get('role')=='tool' and m.get('tool_call_id')=='selective-root-0')
            result_text = p.as_text(root_result.get('content'))
            if case=='cancel':
                p.require(result_text == 'User declined to answer questions',
                          'actual canonical decline envelope missing')
                p.require(any(r.get('kind')=='question_blocked' and r.get('active') is False
                              for r in run.trace.records()), 'canceled questionnaire did not close')
            else:
                validation = ('Validation failed for tool "ask_user_question":\n'
                              '  - questions: must not have fewer than 1 items\n\n'
                              'Received arguments:\n{\n  "questions": []\n}')
                p.require(result_text == validation if case=='invalid' else
                          '\nQUESTION-ERROR: '+validation+'\n' in result_text,
                          'actual empty-question native validation result missing')
        if case.startswith('codemode') or case == 'non-ui':
            p.require(any(r.get('kind')=='execution_end' and r.get('name')=='ask_user_question' and r.get('parent')
                          for r in run.trace.records()),'native nested execution evidence missing')
        p.require('SELECTIVE-FAILED-DRAFT' not in p.request_text(handoff),'failed draft delivered')
        if case=='clear': p.require('Reminder cleared' not in p.request_text(handoff),'model-visible clear instruction')
        run.assert_no_delivery_transcript(sid)
        provider.assert_healthy()
        print(f'PASS {case}: requests {before}->{len(provider.snapshot())}; root batch -> fresh={count-1 if count else 0}; ordinary carry={count}; visible completion; transcript clean')
        print('Body contract:', json.dumps({'initial_projection_indices':[i for i,_ in projections(provider.work[0])],
              'handoff_projection_indices':[i for i,_ in projections(handoff)],
              'root_result_ids':[m.get('tool_call_id') for m in handoff['messages'] if m.get('role')=='tool'],
              'ordinary_prefix_unchanged':True,'visible_response':'SELECTIVE-COMPLETED-WORK'}))
        if case in ('direct','codemode','cancel','invalid','codemode-invalid','non-ui'):
            print('Actual question/root result text:', json.dumps(provider.receipt))
    except Exception:
        if run.tui: print('TUI failure tail:', repr(run.tui.plain()[-4000:]))
        print('Provider errors:', provider.errors)
        if len(provider.work)>1:
            print('Root results:', [m for m in provider.work[1]['messages'] if m.get('role')=='tool'])
        raise
    finally: run.cleanup()


def lifecycle(case,run,tui,sid):
    provider=run.provider
    before=len(provider.snapshot())
    session=run.session_file(sid)
    if case=='historical':
        body=run.prompt_and_wait(tui,'SELECTIVE-CONSUME-PENDING')
        assert_value(body,A,1)
        p.require(not run.saved_state(sid)['pending'],'pending save not consumed before historical probe')
        tui.send('/fixture-custom')
        p.wait_for(lambda:'SELECTIVE-CUSTOM' in session.read_text(), 'persisted native custom message before replay')
        tui.send('/reload')
        run.trace.wait_count(lambda r:r.get('kind')=='session_start',2,'historical reload')
        p.require(not run.saved_state(sid)['pending'],'reload created pending save')
        n=len(provider.snapshot()); offset=tui.output_length()
        tui.send('/fixture-extension')
        provider.wait_count(n+1)
        tui.wait_output_since(offset,'SELECTIVE-COMPLETED-OPERATOR')
        stable_count(run,n+1)
        body=provider.snapshot()[-1]
        assert_value(body,A,0)
        p.require('SELECTIVE-CUSTOM' in p.request_text(body),'native custom history absent from replay')
        print(f'Historical extension-only replay: requests {n}->{len(provider.snapshot())}; projections=0; no operator/save/tool cause')
        run.assert_no_delivery_transcript(sid); provider.assert_healthy()
        return
    if case=='warming':
        provider.wait_count(before+1)
        warmed=provider.snapshot()[-1]
        p.require(warmed.get('max_tokens',warmed.get('max_completion_tokens'))==1, 'not an actual cache-warmer replay')
        p.require(not projections(warmed) and run.saved_state(sid)['pending'], 'warming consumed or delivered pending save')
        body=run.prompt_and_wait(tui,'SELECTIVE-AFTER-WARMING')
        assert_value(body,A,1)
        p.require(not run.saved_state(sid)['pending'], 'normal request did not consume pending save')
    elif case=='unavailable':
        tui.stop(); run.tui=None
        run.state_path(sid).write_text('not json')
        tui=run.launch_tui(session=session)
        tui.wait_output('Could not restore')
        body=run.prompt_and_wait(tui,'SELECTIVE-UNAVAILABLE')
        p.assert_no_reminder(body,'SELECTIVE-UNAVAILABLE')
        save(run,tui)
        body=run.prompt_and_wait(tui,'SELECTIVE-RECOVERED')
        assert_value(body,B,1)
    elif case=='independence':
        tui.stop(); run.tui=None
        tui=run.launch_tui(session_id='selective-independent')
        body=run.prompt_and_wait(tui,'SELECTIVE-INDEPENDENT')
        p.assert_no_reminder(body,'SELECTIVE-INDEPENDENT')
        tui.stop(); run.tui=None
        tui=run.launch_tui(session=session)
        body=run.prompt_and_wait(tui,'SELECTIVE-PARENT')
        assert_value(body,A,1)
    else:
        offset=tui.output_length(); tui.send('/reload')
        run.trace.wait_count(lambda r:r.get('kind')=='session_start',2,'reload')
        p.require(run.saved_state(sid)['pending'],'reload consumed idle pending save')
        stable_count(run,before)
        tui.stop(); run.tui=None
        tui=run.launch_tui(session=session)
        p.require(run.saved_state(sid)['pending'],'resume consumed pending save')
        if case=='lifecycle':
            offset=tui.output_length(); tui.send('/compact')
            run.trace.wait(lambda r:r.get('kind')=='session_compact','manual compaction')
            p.require(run.saved_state(sid)['pending'],'summary consumed pending save')
            summaries=[b for b in provider.snapshot() if p.is_compaction_request(b)]
            p.require(summaries and all(not projections(b) for b in summaries),'summary exclusion unproved')
        body=run.prompt_and_wait(tui,'SELECTIVE-AFTER-LIFECYCLE')
        assert_value(body,A,1)
        p.require(not run.saved_state(sid)['pending'],'normal delivery failed to clear pending')
    run.assert_no_delivery_transcript(sid); provider.assert_healthy()
    print(f'PASS {case}: requests {before}->{len(provider.snapshot())}; completed outer path and private transcript')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',choices=CASES)
    args=parser.parse_args()
    try:
        p.require_isolated_patched_pi(os.environ.get('PI_BIN',''))
        p.require((QUESTION/'index.ts').is_file(),'actual installed question package unavailable')
        metadata=json.loads((QUESTION/'package.json').read_text())
        before=fingerprint(QUESTION)
        print(f'Question path={QUESTION}/index.ts version={metadata["version"]} sha256={before}',flush=True)
        for case in ([args.case] if args.case else CASES):
            with tempfile.TemporaryDirectory(prefix='pi-selective-'+case+'-') as directory:
                scenario(case,Path(directory))
        p.require(fingerprint(QUESTION)==before,'installed question package changed')
        return 0
    except p.ProofBlocked as exc: print(f'BLOCKED: {exc}'); return 2
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f'FAIL: {type(exc).__name__}: {exc}'); return 1

if __name__=='__main__': raise SystemExit(main())
