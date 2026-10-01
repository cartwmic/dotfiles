#!/usr/bin/env python3
"""Explicitly capped, exact-model live proof. --self-test never sends requests."""
from __future__ import annotations
import argparse
import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROVIDER = 'openai-codex'
MODEL = 'gpt-6.1-sol'
MODEL_REF = f'{PROVIDER}/{MODEL}'
VERSION = '0.99.2'
CONTEXT = 272000
OUTPUT = 128000
REQUEST_BYTES = 45000 - 4096
SEED_ROWS = 300
STAGES = ('cold', 'ordinary-warm', 'ordinary-unchanged', 'question', 'gated-save', 'edited-ordinary')
CALLS = len(STAGES) * 2 * 2
TOOLS = 'cache_ordinary,ask_user_question,cache_gate'
REMINDER = 'Keep the existing implementation unless the operator asks otherwise.'
EDITED = 'Preserve the implementation and report focused verification.'

class Blocked(RuntimeError): pass

def require(value, reason):
    if not value: raise Blocked(reason)

def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0

def reserve(model):
    require(model.get('provider') == PROVIDER and model.get('id') == MODEL and
            model.get('api') == 'openai-codex-responses' and
            model.get('contextWindow') == CONTEXT and model.get('maxTokens') == OUTPUT,
            'unusable or mismatched native model capacity')
    cost = model.get('cost', {})
    tiers = cost.get('tiers', [])
    require(isinstance(tiers, list), 'unusable cost tiers')
    rates = [cost, *tiers]
    require(all(isinstance(r, dict) and all(finite(r.get(k)) for k in ('input','output','cacheRead','cacheWrite')) for r in rates), 'missing cost rates')
    rate = max(r[k] for r in rates for k in ('input','cacheRead','cacheWrite'))
    output = max(r['output'] for r in rates)
    require(rate > 0 and output > 0, 'zero rates cannot reserve spend')
    return (CONTEXT * rate + OUTPUT * output) / 1e6

def usage(message):
    require(message.get('provider') == PROVIDER and message.get('model') == MODEL, 'response identity mismatch')
    u = message.get('usage', {})
    require(all(finite(u.get(k)) and int(u[k]) == u[k] for k in ('input','output','cacheRead','cacheWrite')), 'unusable token counters')
    require(0 < u['input'] + u['cacheRead'] + u['cacheWrite'] <= CONTEXT and u['output'] <= OUTPUT, 'token reserve exceeded or empty input')
    require(finite(u.get('cost', {}).get('total')), 'unusable spend counter')
    return {k:u[k] for k in ('input','output','cacheRead','cacheWrite')} | {'cost':u['cost']['total']}

def check_reserve(spent, per_call, remaining, cap):
    require(finite(cap) and cap > 0 and finite(spent) and finite(per_call), 'invalid explicit cap/reserve')
    require(isinstance(remaining, int) and not isinstance(remaining, bool) and 0 <= remaining <= CALLS,
            'invalid remaining call reserve')
    require(spent + per_call * remaining <= cap + 1e-9, 'remaining worst-case reservation exceeds cap')

def cold_seed():
    return '\n'.join(f'Stable cache fixture row {i:04d}: ordinary context shared exactly across arms.' for i in range(SEED_ROWS))

def stage_tool(step):
    require(step in STAGES, 'unknown workload stage')
    return 'ask_user_question' if step == 'question' else 'cache_gate' if step == 'gated-save' else 'cache_ordinary'

def state(sessions, sid, text=REMINDER, pending=False):
    path = sessions / 'standing-reminder' / f'{sid}.json'
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(json.dumps({'version':1,'reminder':text,'pending':pending}))
    path.chmod(0o600)
    return path

def stage(root, source):
    target = root / 'source-extension'
    shutil.copytree(source.parent, target)
    shutil.copytree(source.parent.parent / 'inspect-prompt', root / 'inspect-prompt')
    (target / 'config.json').write_text(json.dumps({'triggers':['tool-result:ask_user_question']}))
    return target / source.name

FIXTURE = r'''import {appendFileSync, writeFileSync} from 'node:fs';
import {Type} from '@sinclair/typebox';
export default function(pi) {
 let requests=0, tools=0;
 const refuse=(reason='fixture_guard')=>{console.error('CACHE-REFUSAL:'+reason);process.exit(72);};
 pi.on('before_provider_request',event=>{
  const declared=event.payload?.tools;
  const names=['cache_ordinary','ask_user_question','cache_gate'];
  if(!Array.isArray(declared) || declared.length!==3 ||
    !names.every(n=>declared.filter(t=>t.type==='function' && t.name===n).length===1))
   refuse('provider_tool_declarations');
  if(process.env.CACHE_LOADOUT_TEST==='1') {
   appendFileSync(process.env.CACHE_AUDIT,JSON.stringify({loadout_verified:true,tool_count:declared.length})+'\n');
   process.exit(73); // Offline regression: never enter provider HTTP.
  }
 });
 pi.on('message_end',event=>{
  const m=event.message;
  if(m.role!=='assistant') return;
  const u=m.usage;
  const valid=v=>typeof v==='number' && Number.isFinite(v) && v>=0;
  if(m.provider!=='openai-codex' || m.model!=='gpt-6.1-sol' || !u ||
    !['input','output','cacheRead','cacheWrite'].every(k=>valid(u[k]) && Number.isInteger(u[k])) ||
    u.input+u.cacheRead+u.cacheWrite<=0 || u.input+u.cacheRead+u.cacheWrite>272000 || u.output>128000 ||
    !valid(u.cost?.total) || u.cost.total>Number(process.env.CACHE_RESERVE)+1e-9) refuse();
 });
 pi.on('context_with_system',event=>{
  // Independent bounded transcript guard; native capacity reserves framing/tools.
  if(Buffer.byteLength(JSON.stringify(event.messages),'utf8')>45000-4096) refuse();
 });
 const text=c=>typeof c==='string'?c:(c??[]).filter(p=>p.type==='text').map(p=>p.text).join('\n');
 for (const name of ['cache_ordinary','ask_user_question','cache_gate']) pi.registerTool({
  name,label:name,description:'Deterministic bounded fixture; call with empty arguments.',
  parameters:Type.Object({}, {additionalProperties:false}),
  async execute(_id,args) {
   if (++tools!==1 || name!==process.env.CACHE_TOOL || Object.keys(args).length) refuse();
   if(name==='cache_gate') {
    // A finite gate, then a private saved-value change. Reload owns restoration;
    // actual editor/UI mid-turn semantics are separately proved by SR-2.
    await new Promise(resolve=>setTimeout(resolve,25));
    if(process.env.CACHE_STATE) writeFileSync(process.env.CACHE_STATE,
      JSON.stringify({version:1,reminder:process.env.CACHE_EDITED,pending:true}),{mode:0o600});
   }
   return {content:[{type:'text',text:'CACHE-RESULT:'+name}],details:{}};
  }
 });
 pi.on('session_start',()=>pi.setActiveTools(['cache_ordinary','ask_user_question','cache_gate']));
 pi.on('tool_call',event=>{
  if(event.toolName!==process.env.CACHE_TOOL || Object.keys(event.input??{}).length) refuse();
 });
 pi.on('context_with_system',event=>{
  if(++requests>2) refuse();
  if(requests===2 && tools!==1) refuse();
  appendFileSync(process.env.CACHE_AUDIT,JSON.stringify({
   request:requests,messages:event.messages,
   reminders:event.messages.map(m=>text(m.content)).filter(t=>t.startsWith('<standing-reminder>\n'))
  })+'\n');
 });
}
'''

def lines(text):
    try: rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    except ValueError: raise Blocked('non-JSON proof output')
    require(all(isinstance(r,dict) for r in rows), 'non-object proof output')
    return rows

def run(argv, env, cwd, stdin=None):
    try: p = subprocess.run(argv, env=env, cwd=cwd, input=stdin, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired): raise Blocked('Pi process unavailable or timed out')
    require(p.returncode == 0, f'Pi process failed (exit {p.returncode}); diagnostics withheld')
    return p.stdout

def prepare(root, source_agent):
    try: auth = json.loads((source_agent/'auth.json').read_text())
    except (OSError,ValueError): raise Blocked('private Pi auth unavailable')
    require(PROVIDER in auth, 'selected provider credential unavailable')
    agent = root/'agent'; agent.mkdir(mode=0o700)
    path = agent/'auth.json'; path.write_text(json.dumps({PROVIDER:auth[PROVIDER]})); path.chmod(0o600)
    (agent/'settings.json').write_text(json.dumps({'retry':{'enabled':False,'maxRetries':0,'provider':{'maxRetries':0}},'compaction':{'enabled':False},'cacheWarming':'off'}))
    env = os.environ.copy(); env.pop('OPENAI_API_KEY',None)
    env.update(HOME=str(root/'home'), PI_CODING_AGENT_DIR=str(agent), PI_OFFLINE='1', PI_TELEMETRY='0', PYTHONDONTWRITEBYTECODE='1')
    return env

def identity(pi):
    package = Path(os.environ.get('PI_STANDING_REMINDER_ORIGIN_PACKAGE','/nonexistent')).resolve()
    require(Path(pi).resolve().is_relative_to(package), 'use isolated_pi.py; installed runtime forbidden')
    metadata = json.loads((package/'package.json').read_text())
    require(metadata.get('name')=='@earendil-works/pi-coding-agent' and metadata.get('version')==VERSION, 'exact Pi 0.99.2 required')
    marker = 'chezmoi-pi-patch:standing-reminder-origin v2'
    require(all(marker in (package/p).read_text() for p in ('dist/core/agent-session.js','dist/core/extensions/types.d.ts')), 'private origin patch missing')
    require(sum(marker in p.read_text() for p in (package/'dist/bundle/chunks').glob('*.js')) == 1, 'bundle patch missing')
    require(os.environ.get('PI_CHEZMOI_PROFILE') in ('personal','axon-work-computer'), 'desktop profile required')

def comparison(arms):
    for name, rows in arms.items():
        require(len(rows)==len(STAGES)*2, 'incomplete arm')
        require(any(r['cacheRead']>0 for r in rows[2:6]), f'{name} has no warmed cacheRead')
    return [{'stage':s,'off':arms['off'][i*2:i*2+2], 'on':arms['on'][i*2:i*2+2],
             'genuine_zero_cacheRead':{a:[r['cacheRead']==0 for r in arms[a][i*2:i*2+2]] for a in arms}}
            for i,s in enumerate(STAGES)]

def loadout_test(pi):
    identity(pi)
    with tempfile.TemporaryDirectory(prefix='cache-loadout-', dir='/tmp') as tmp:
        root=Path(tmp); (root/'home').mkdir(); (root/'project').mkdir()
        owner=Path(os.environ.get('PI_CODING_AGENT_DIR',Path.home()/'.pi/agent'))
        env=prepare(root,owner)
        extension=stage(root,ROOT/'dot_pi/private_agent/extensions/standing-reminder/index.ts')
        fixture=root/'fixture.ts'; fixture.write_text(FIXTURE)
        for disabled in (False, True):
            audit=root/f'loadout-{disabled}.jsonl'
            call_env=env | {'CACHE_LOADOUT_TEST':'1','CACHE_AUDIT':str(audit),'CACHE_TOOL':'cache_ordinary'}
            argv=[pi,'--approve','--no-context-files','--no-skills','--no-prompt-templates','--no-themes',
                  '--no-extensions','--provider',PROVIDER,'--model',MODEL_REF,'--mode','json',
                  '--extension',str(extension),'--extension',str(fixture),'--no-session']
            argv+=['--no-tools'] if disabled else ['--tools',TOOLS]
            p=subprocess.run(argv+['Call cache_ordinary with empty arguments.'],env=call_env,
                             cwd=root/'project',capture_output=True,text=True,timeout=60)
            require(p.returncode==(72 if disabled else 73), f'offline loadout boundary not reached (exit {p.returncode}, disabled={disabled})')
            if disabled:
                require('CACHE-REFUSAL:provider_tool_declarations' in p.stderr+p.stdout and
                        not any(r.get('loadout_verified') for r in (lines(audit.read_text()) if audit.exists() else [])),
                        'disabled declarations not refused before provider')
            else:
                require(lines(audit.read_text())[-1]=={'loadout_verified':True,'tool_count':3},
                        'exact fixture declarations unavailable')
    print('PASS: real isolated Pi exact loadout and --no-tools refusal; forced exit before HTTP')

def self_test():
    native = {'provider':PROVIDER,'id':MODEL,'api':'openai-codex-responses',
              'contextWindow':CONTEXT,'maxTokens':OUTPUT,
              'cost':{'input':5,'output':15,'cacheRead':5,'cacheWrite':5}}
    require(SEED_ROWS == 300 and len(cold_seed().splitlines()) == 300 and
            cold_seed().splitlines()[-1].startswith('Stable cache fixture row 0299:'),
            'shared 300-row cold fixture regression')
    rate = reserve(native)
    require(abs(rate*CALLS-78.72)<1e-9, 'native 24-call reservation regression')
    check_reserve(0,rate,CALLS,250)
    def rejects(fn):
        try: fn()
        except Blocked: return
        raise AssertionError('accepted unusable evidence')
    rejects(lambda:check_reserve(0,rate,CALLS,20))
    rejects(lambda:reserve(native | {'cost':{}}))
    rejects(lambda:reserve(native | {'maxTokens':256}))
    rejects(lambda:reserve(native | {'contextWindow':45000}))
    rejects(lambda:reserve(native | {'contextWindow':872000}))
    tiered = native | {'cost':native['cost'] | {'tiers':[{'input':10,'output':30,'cacheRead':8,'cacheWrite':9}]}}
    require(abs(reserve(tiered)-2*rate)<1e-9, 'maximum tier reservation')
    good={'provider':PROVIDER,'model':MODEL,'usage':{'input':100,'output':1,'cacheRead':2000,'cacheWrite':0,'cost':{'total':0.01}}}
    usage(good)
    for key in ('input','output','cacheRead','cacheWrite'):
        for bad in (None,True,-1,float('nan'),1.5):
            changed=json.loads(json.dumps(good)); changed['usage'][key]=bad
            rejects(lambda:usage(changed))
    changed=json.loads(json.dumps(good)); changed['usage']['output']=OUTPUT+1
    rejects(lambda:usage(changed))
    changed=json.loads(json.dumps(good)); changed['usage']['input']=CONTEXT+1
    rejects(lambda:usage(changed))
    rejects(lambda:usage(good | {'model':'wrong'}))
    for bad in (None, True, -1, float('nan'), float('inf')):
        changed=json.loads(json.dumps(good)); changed['usage']['cost']['total']=bad
        rejects(lambda:usage(changed))
    rejects(lambda:check_reserve(1,rate,CALLS,rate*CALLS))
    for remaining in (-1, CALLS+1, True, 1.5, None):
        rejects(lambda:check_reserve(0,rate,remaining,250))
    require([stage_tool(s) for s in STAGES] == [
        'cache_ordinary', 'cache_ordinary', 'cache_ordinary',
        'ask_user_question', 'cache_gate', 'cache_ordinary'], 'stage tool mapping')
    rejects(lambda:stage_tool('unapproved-stage'))
    rows=[usage(good) for _ in range(len(STAGES)*2)]
    comparison({'off':rows,'on':rows})
    for arm in ('off','on'):
        rejects(lambda:comparison({'off':rows,'on':rows}|{arm:[r|{'cacheRead':0} for r in rows]}))
    for bad_cap in (None, True, float('nan'), float('inf'), -1, 0):
        rejects(lambda:check_reserve(0,rate,CALLS,bad_cap))
    with tempfile.TemporaryDirectory(prefix='cache-self-', dir='/tmp') as tmp:
        root=Path(tmp)
        owner=root/'owner'; owner.mkdir()
        (owner/'auth.json').write_text(json.dumps({PROVIDER:{'type':'api_key','key':'offline-dummy'},'unrelated':{}}))
        env=prepare(root,owner)
        agent=Path(env['PI_CODING_AGENT_DIR'])
        require(not (agent/'models.json').exists(), 'native metadata overridden')
        require(set(json.loads((agent/'auth.json').read_text()))=={PROVIDER}, 'unrelated auth copied')
        require(agent.stat().st_mode&0o777==0o700 and (agent/'auth.json').stat().st_mode&0o777==0o600,'auth privacy')
        settings=json.loads((agent/'settings.json').read_text())
        require(settings['retry']['provider']['maxRetries']==0 and not settings['retry']['enabled'] and
                not settings['compaction']['enabled'] and settings['cacheWarming']=='off','background/retry guards')
        p=state(root,'first')
        require(json.loads(p.read_text())=={'version':1,'reminder':REMINDER,'pending':False},'first sidecar creation')
        require(p.stat().st_mode&0o777==0o600 and p.parent.stat().st_mode&0o777==0o700,'sidecar privacy')
        state(root,'first',EDITED,True)
        require(json.loads(p.read_text())['pending'], 'gated save state')
        staged=stage(root,ROOT/'dot_pi/private_agent/extensions/standing-reminder/index.ts')
        require(json.loads((staged.parent/'config.json').read_text())=={'triggers':['tool-result:ask_user_question']},'active config staging')
        require((root/'inspect-prompt/helpers.ts').exists(), 'editor helper staging')
    require(len(STAGES)==6 and CALLS==24 and 'ask_user_question' in FIXTURE and 'cache_gate' in FIXTURE,'workload stages')
    print('PASS: offline reserve/counter rejection, first sidecar, save, six stages and adjacent active config staging')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--loadout-test',action='store_true',help='offline real isolated Pi declaration regression; exits before HTTP')
    parser.add_argument('--cap-usd',type=float,help='required approved finite cap; driver uses 250')
    parser.add_argument('--pi',default=os.environ.get('PI_BIN') or shutil.which('pi'))
    args=parser.parse_args()
    try:
        if args.self_test: self_test(); return 0
        if args.loadout_test: loadout_test(args.pi); return 0
        require(finite(args.cap_usd) and args.cap_usd>0,'explicit --cap-usd required')
        require(args.pi,'Pi executable unavailable')
        identity(args.pi)
        source_agent=Path(os.environ.get('PI_CODING_AGENT_DIR',Path.home()/'.pi/agent'))
        with tempfile.TemporaryDirectory(prefix='pi-cache-proof-', dir='/tmp') as tmp:
            root=Path(tmp); (root/'home').mkdir(); (root/'project').mkdir(); sessions=root/'sessions'; sessions.mkdir()
            env=prepare(root,source_agent); env['PI_CODING_AGENT_SESSION_DIR']=str(sessions)
            extension=stage(root,ROOT/'dot_pi/private_agent/extensions/standing-reminder/index.ts')
            fixture=root/'fixture.ts'; fixture.write_text(FIXTURE)
            cwd=root/'project'
            common=[args.pi,'--approve','--no-context-files','--no-skills','--no-prompt-templates','--no-themes','--no-extensions','--provider',PROVIDER,'--model',MODEL_REF]
            require(run([args.pi,'--version'],env,cwd).strip()==VERSION,'runtime version mismatch')
            models=lines(run(common+['--mode','rpc','--offline','--no-session'],env,cwd,json.dumps({'id':'models','type':'get_available_models'})+'\n'))
            response=next((r for r in models if r.get('id')=='models' and r.get('success')), {})
            model=next((m for m in response.get('data',{}).get('models',[]) if m.get('provider')==PROVIDER and m.get('id')==MODEL),{})
            require(model.get('api')=='openai-codex-responses' and model.get('contextWindow')==CONTEXT and model.get('maxTokens')==OUTPUT,'exact native API/capacity unavailable')
            per_call=reserve(model); check_reserve(0,per_call,CALLS,args.cap_usd)
            print(json.dumps({'runtime':VERSION,'model':model,'calls_reserved':CALLS,'token_ceiling_per_call':{'context':CONTEXT,'output':OUTPUT},'reserve_usd':per_call*CALLS,'cap_usd':args.cap_usd}),flush=True)
            spent=0; done=0; arms={}; snapshots={}
            payload=cold_seed()
            for arm in ('off','on'):
                sid='cache-proof-'+arm; session=None; rows=[]; audits=[]
                for i,step in enumerate(STAGES):
                    check_reserve(spent,per_call,CALLS-done,args.cap_usd)
                    tool=stage_tool(step)
                    prompt=f'CACHE-STAGE-{i+1}:{step}\n{payload if i == 0 else 'Continue the unchanged cache fixture.'}\nCall exactly one {tool} with empty arguments. After CACHE-RESULT, return exactly CACHE-ACK-{i+1}. No other tool calls.'
                    audit=root/f'{arm}-{i}.jsonl'; call_env=env|{'CACHE_TOOL':tool,'CACHE_AUDIT':str(audit),'CACHE_EDITED':EDITED,'CACHE_RESERVE':str(per_call)}
                    if arm=='on' and step=='gated-save': call_env['CACHE_STATE']=str(sessions/'standing-reminder'/f'{sid}.json')
                    argv=common+['--mode','json','--extension',str(extension),'--extension',str(fixture),'--tools',TOOLS,'--thinking','low','--session-dir',str(sessions)]
                    argv+=['--session',str(session)] if session else ['--session-id',sid]
                    records=lines(run(argv+[prompt],call_env,cwd))
                    messages=[r['message'] for r in records if r.get('type')=='message_end' and r.get('message',{}).get('role')=='assistant']
                    require(len(messages)==2,'expected exactly two provider responses')
                    calls=[p for m in messages for p in m.get('content',[]) if p.get('type')=='toolCall']
                    require(len(calls)==1 and calls[0].get('name')==tool and calls[0].get('arguments')=={},'tool workload deviation')
                    require(messages[-1].get('stopReason')=='stop' and ''.join(p.get('text','') for p in messages[-1].get('content',[]))==f'CACHE-ACK-{i+1}','ordinary completed outcome missing')
                    for m in messages:
                        u=usage(m); require(u['cost']<=per_call+1e-9,'per-response spend exceeds reserve')
                        spent+=u['cost']; done+=1; require(spent<=args.cap_usd+1e-9,'reported spend exceeded cap')
                        rows.append(u)
                        print(json.dumps({'arm':arm,'stage':step,'call':done,**u}),flush=True)
                    late=lines(audit.read_text()); require(len(late)==2,'late request count mismatch')
                    wording=EDITED if step=='edited-ordinary' else REMINDER
                    expected=[f'<standing-reminder>\n{wording}\n</standing-reminder>'] if arm=='on' and i>0 else []
                    require(late[0]['reminders']==expected and late[1]['reminders']==(expected*2 if step=='question' else expected),'selective reminder projection mismatch')
                    audits.append({'stage':step,'requests':late})
                    print(json.dumps({'arm':arm,'stage':step,'late_request_snapshots':late}),flush=True)
                    if session is None:
                        matches=[]
                        for p in sessions.rglob('*.jsonl'):
                            if json.loads(p.open().readline()).get('id')==sid: matches.append(p)
                        require(len(matches)==1,'session identity unavailable'); session=matches[0]
                        if arm=='on': state(sessions,sid)
                arms[arm]=rows; snapshots[arm]=audits
            pairs=comparison(arms)
            print(json.dumps({'status':'PASS','runtime':VERSION,'model':MODEL_REF,'thinking':'low','workload':STAGES,'provider_calls':done,'cap_usd':args.cap_usd,'reserve_usd':per_call*CALLS,'actual_cost_usd':spent,'pairs':pairs,'late_request_snapshots':snapshots}))
        return 0
    except (Blocked,OSError,ValueError,StopIteration) as exc:
        print(f'BLOCKED: {exc if isinstance(exc,Blocked) else type(exc).__name__}; no fallback or synthetic counters')
        return 2

if __name__=='__main__': raise SystemExit(main())
