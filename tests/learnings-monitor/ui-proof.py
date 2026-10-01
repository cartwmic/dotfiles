#!/usr/bin/env python3
"""Real private Pi key journeys. No production state or model service is used."""
import argparse
import fcntl
import json
import signal
import re
import struct
import subprocess
import tempfile
import termios
import time
from datetime import datetime, timezone
from pathlib import Path
import proof as h


def seed(root, sid):
    script = '''const {createLearningStore}=await import(process.env.STORE);
const store=createLearningStore({root:process.env.ROOT});
for(const source of [process.env.SID,"fixture-other"]){
 const rows=Array.from({length:25},(_,i)=>({id:`fixture-${i}`,proposalKey:`proposal-${i}`,type:"friction",status:"open",observation:`ROW_${String(i).padStart(2,"0")} operator edited body`,recommendation:Array.from({length:65},(_,n)=>`DETAIL_${i}_${n}`).join("\\n"),evidence:[],reviewHistory:[],analogues:[],recordedAt:i===24?undefined:i===23?"2025-01-01T00:00:00.000Z":"2020-01-01T00:00:00.000Z"}));
 await store.applyChanges(source,rows,{label:source===process.env.SID?"Primary fixture":"Other fixture"});
}'''
    import os
    subprocess.run(['node','--input-type=module','-e',script],env={**os.environ,'STORE':(h.EXTENSION.parent/'store.mjs').as_uri(),'ROOT':str(root/'xdg/pi/learnings-monitor'),'SID':sid},check=True,capture_output=True)
    # Legacy timestamps are fixture data, not newly generated store records.
    for path, metadata, text in h.all_records(root):
        n=int(metadata['id'].split('-')[-1])
        metadata['recordedAt']=None if n==24 else '2025-01-01T00:00:00.000Z' if n==23 else '2020-01-01T00:00:00.000Z'
        marker='<!-- learnings-monitor:metadata\n'
        start=text.index(marker)+len(marker); end=text.index('\n-->',start)
        path.write_text(text[:start]+json.dumps(metadata)+text[end:])


def snapshot(root):
    return {str(p):p.read_bytes() for p,_,_ in h.all_records(root)}


def key(pi, value, expected):
    start=len(pi.text()); pi.send(value); return pi.wait_text(expected,start=start)


def review(pi):
    start=len(pi.text()); pi.sendline('/learnings review'); pi.wait_text('Esc Exit',start=start)


def leave(pi, choice):
    key(pi,'\x1b','Staged Learnings decisions')
    pi.send({'Apply':'\r','Discard':'\x1b[B\r','Continue':'\x1b[B\x1b[B\r'}[choice])
    if choice=='Continue': pi.wait_text('Esc Exit',start=len(pi.text())-200)


def choose_scope(pi, log, label, expected):
    start=len(pi.text())
    key(pi,'s','Review scope')
    pane=pi.wait_text('Primary fixture ·',start=start)[start:]
    labels=['Current session','All local sources','Other fixture ·','Primary fixture ·']
    h.require(all(value in pane for value in labels),'scope chooser omitted fixture labels','UI')
    options=sorted(labels,key=pane.index)
    matches=[i for i,value in enumerate(options) if value==label or value.startswith(label+' ·')]
    h.require(len(matches)==1,f'scope label not unique: {label}: {options}','UI')
    frame_start=len(pi.text())
    key(pi,'\x1b[B'*matches[0]+'\r',expected)
    wait_detail(pi,frame_start)
    return frame_start


def wait_detail(pi, start):
    deadline=time.monotonic()+12
    while time.monotonic()<deadline:
        frame=pi.text()[start:]
        matches=re.findall(r'DETAIL_(\d+)_0',frame)
        if matches:
            return int(matches[-1])
        pi.pump(0.2)
    raise h.ProofFailure('Fresh review frame did not complete its selected detail', 'UI')


def select_record(pi, root, number, *, status='all', frame_start=0, recorded=None):
    # Read-only fixture ordering guides keys; selected detail is still proved
    # by native terminal output, not by a controller call.
    rows=sorted((p,m) for p,m,text in h.all_records(root)
        if m['sourceId']=='fixture-other' and (status=='all' or h.markdown_status(text)==status))
    order=[int(m['id'].split('-')[-1]) for _,m in rows]
    current=wait_detail(pi,frame_start)
    h.require(current in order and number in order,f'filtered selection outside eligible rows: {current}, {number}, {order}','UI')
    delta=order.index(number)-order.index(current)
    output=pi.text()[frame_start:]
    selected_start=frame_start
    for step in range(abs(delta)):
        start=len(pi.text())
        selected_start=start
        target=order[order.index(current)+(step+1)*(1 if delta>0 else -1)]
        output=key(pi,'\x1b[B' if delta>0 else '\x1b[A',f'DETAIL_{target}_0')[start:]
    if recorded is not None:
        pi.wait_text(recorded,start=selected_start)
        output=pi.text()[selected_start:]
    h.require(f'DETAIL_{number}_0' in output,f'keys did not select fixture-{number}','UI')
    return output


def run(scenario):
    with tempfile.TemporaryDirectory(prefix='learnings-ui-proof-') as tmp:
        root=Path(tmp); log=root/'ui.jsonl'
        backend=h.ScriptedBackends(root/'work',root/'backend.jsonl')
        pi=None
        try:
            env,agent,sessions,xdg,project=h.make_environment(root,backend,log)
            h.ACTIVE_UI_LOG=log
            pi=h.PiTui(h.pi_command(env,agent,sessions),env,project,'ui-'+scenario); pi.wait_start()
            h.turn(pi,'UI_BEFORE','PI_CASE:UI_BEFORE primary conversation before review')
            session=h.primary_session(sessions); sid=h.source_id(h.parse_session(session)[0]['id'])
            seed(root,sid); before=snapshot(root)
            start=len(pi.text()); pi.sendline('/learnings')
            home=pi.wait_text('Cleanup — Delete source notes and owned observer; confirms.',start=start)[start:]
            for name in ('Review','Status','On','Off','Focus','Model','Tools','Flush','Patterns','Promote','Cleanup'):
                h.require(re.search(rf'{name} — \S',home),f'home lacks visible help for {name}','UI')
            key(pi,'\r','Esc Exit')
            scrolled=key(pi,'\x1b[6~','DETAIL_')
            h.require('DETAIL_6_23' in scrolled[-8000:],'PageDown did not expose later detail lines','UI')
            for _ in range(20): key(pi,'\x1b[B','▶')
            for _ in range(20): key(pi,'\x1b[A','▶')
            key(pi,'k','kept'); key(pi,'d','dismissed'); key(pi,'u','open')
            key(pi,'k','kept')
            h.require(snapshot(root)==before,'staging wrote authoritative Markdown','UI')
            h.require(not backend.retain_calls,'staging sent promotion','UI')
            leave(pi,'Continue'); key(pi,'d','dismissed')
            leave(pi,'Discard')
            h.command(pi,log,'/learnings status','Learnings monitor')
            h.require(snapshot(root)==before,'Discard wrote authoritative Markdown','UI')
            h.require(not backend.retain_calls,'Discard sent promotion','UI')
            review(pi); key(pi,'k','kept'); key(pi,'\x1b[B','▶'); key(pi,'d','dismissed')
            key(pi,'\x1b[B','▶'); key(pi,'k','kept'); key(pi,'p','+Promote'); key(pi,'d','dismissed')
            leave(pi,'Apply')
            pi.wait_text('3 applied')
            records=h.all_records(root)
            changed=[(p,m,t) for p,m,t in records if p.read_bytes()!=before[str(p)]]
            h.require(len(changed)==3 and all(m['sourceId']==sid for _,m,_ in changed),'Apply changed wrong records/sources','UI')
            h.require(all('operator edited body' in t for _,_,t in changed),'Apply lost edited bodies','UI')
            h.require(sorted(h.markdown_status(t) for _,_,t in changed)==['dismissed','dismissed','kept'],'Apply persisted wrong mixed decisions','UI')
            for path,meta,_ in changed:
                old=before[str(path)].decode(); marker='<!-- learnings-monitor:metadata\n'
                original=json.loads(old.split(marker,1)[1].split('\n-->',1)[0])
                h.require(meta.get('recordedAt')==original.get('recordedAt'),'Apply reset original recorded time','UI')
                h.require(len(meta.get('reviewHistory',[]))==len(original.get('reviewHistory',[]))+1,'Apply did not append exactly one review decision','UI')
            h.require(not backend.retain_calls,'p then d sent promotion','UI')
            review(pi); key(pi,'f','· kept ·')
            key(pi,'\x1b','────────────────────')
            h.turn(pi,'UI_AFTER','PI_CASE:UI_AFTER primary conversation after review')
            users=h.primary_user_messages(session)
            h.require(not any(x.startswith('/learnings') for x in users),'review polluted primary conversation','UI')
            h.require(h.assistant_for_case(session,'UI_BEFORE') is not None and h.assistant_for_case(session,'UI_AFTER') is not None,'primary conversation lost turns','UI')
            if scenario=='scope-time':
                review(pi)
                choose_scope(pi,log,'All local sources','All local sources')
                h.require(len([m for _,m,_ in h.all_records(root) if m['id']=='fixture-6'])==2,'same-ID source fixture missing','UI')
                frame_start=choose_scope(pi,log,'Other fixture','fixture-other')
                dates={}
                for number in (6,23,24):
                    if number==24:
                        date='Recorded: unknown'
                    else:
                        original='2025-01-01T00:00:00.000Z' if number==23 else '2020-01-01T00:00:00.000Z'
                        local=subprocess.run(['node','-e',f'console.log(new Date({json.dumps(original)}).toLocaleString())'],
                            env=env,check=True,capture_output=True,text=True).stdout.strip()
                        days=(datetime.now(timezone.utc)-datetime.fromisoformat(original.replace('Z','+00:00'))).days
                        date=f'Recorded: {local} ({days}d ago)'
                    output=select_record(pi,root,number,status='open',frame_start=frame_start,recorded=date)
                    h.require(date in output[-8000:],f'displayed recorded time/age missing for fixture-{number}: {date}','UI')
                    dates[number]=date
                select_record(pi,root,23)
                scope_before=snapshot(root)
                key(pi,'k','kept'); leave(pi,'Apply'); pi.wait_text('1 applied')
                scope_changed=[m for p,m,_ in h.all_records(root) if p.read_bytes()!=scope_before[str(p)]]
                h.require(len(scope_changed)==1 and scope_changed[0]['sourceId']=='fixture-other' and scope_changed[0]['id']=='fixture-23','scope write crossed source/record identity','UI')
                h.require(scope_changed[0]['recordedAt']=='2025-01-01T00:00:00.000Z','review reset newer recorded time','UI')
                review(pi)
                choose_scope(pi,log,'Other fixture','fixture-other')
                frame_start=len(pi.text())
                key(pi,'f','· kept ·')
                output=select_record(pi,root,23,status='kept',frame_start=frame_start,recorded=dates[23])
                h.require('DETAIL_23_0' in output[-8000:] and dates[23] in output[-8000:],'reopened kept record lost original displayed date/age','UI')
                choose_scope(pi,log,'All local sources','All local sources')
                import os
                start=len(pi.text())
                fcntl.ioctl(pi.master,termios.TIOCSWINSZ,struct.pack('HHHH',24,65,0,0))
                os.kill(pi.proc.pid,signal.SIGWINCH)
                pi.wait_text('Learnings review',start=start)
                key(pi,'f','dismissed'); key(pi,'f','all')
                frame_start=choose_scope(pi,log,'Other fixture','fixture-other')
                output=select_record(pi,root,24,frame_start=frame_start,recorded='Recorded: unknown')
                h.require('Recorded: unknown' in output[-8000:],'narrow review invented legacy date','UI')
                start=len(pi.text())
                fcntl.ioctl(pi.master,termios.TIOCSWINSZ,struct.pack('HHHH',48,180,0,0))
                os.kill(pi.proc.pid,signal.SIGWINCH)
                pi.wait_text('Recorded: unknown',start=start)
                key(pi,'\x1b','────────────────────')
                h.require(snapshot(root)=={**scope_before,**{str(p):p.read_bytes() for p,m,_ in h.all_records(root) if m['sourceId']=='fixture-other' and m['id']=='fixture-23'}},'scope/filter/resize changed untouched records','UI')
            if scenario=='promotion':
                review(pi); key(pi,'f','kept'); key(pi,'p','+Promote'); leave(pi,'Apply')
                preview=pi.wait_ui(log,lambda r:r.get('kind')=='confirm' and 'Hindsight' in r.get('title',''))
                h.require('cartwmic' in preview['message'] and 'operator edited body' in preview['message'],'exact promotion preview missing','UI')
                pi.send('\x1b[B\r'); pi.wait_text('cancelled')
                h.require(not backend.retain_calls,'cancel sent promotion','UI')
                kept_id=next(m['id'] for _,m,t in h.all_records(root) if m['sourceId']==sid and h.markdown_status(t)=='kept')
                backend.fail_retains=True
                review(pi); key(pi,'f','kept'); key(pi,'p','+Promote'); leave(pi,'Apply')
                pi.wait_text('Send this exact text?',start=len(pi.text())-10000)
                pi.send('\r'); backend.wait_for('retain_calls',1)
                h.command(pi,log,'/learnings status','Learnings monitor')
                h.require(all(h.markdown_status(t)=='kept' for _,m,t in h.all_records(root) if m['sourceId']==sid and m['id']==kept_id),'failed promotion lost local Keep','UI')
                sent=backend.retain_calls[0]['items'][0]['content']
                number=int(kept_id.split('-')[-1])
                exact=f'ROW_{number:02d} operator edited body\n\n'+ '\n'.join(f'DETAIL_{number}_{n}' for n in range(65))
                h.require(sent==exact,'promotion was not exact Observation/Recommendation text','UI')
                backend.fail_retains=False
                review(pi); key(pi,'f','kept'); key(pi,'p','+Promote'); leave(pi,'Apply')
                pi.wait_text('Send this exact text?',start=len(pi.text())-10000)
                pi.send('\r'); backend.wait_for('retain_calls',2)
                pi.wait_text('Hindsight accepted the asynchronous request')
                h.require(backend.retain_calls[1]=={'items':[{'content':exact}],'async':True},'confirmed request payload diverged','UI')
            return {'scenario':scenario,'passed':True,'changedRecords':len(changed),'retainRequests':len(backend.retain_calls)}
        finally:
            if pi: pi.close()
            backend.close()


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--scenario',choices=['stage','promotion','scope-time','all'],default='all'); args=parser.parse_args()
    print(json.dumps([run(s) for s in (['stage','promotion','scope-time'] if args.scenario=='all' else [args.scenario])],indent=2))

if __name__=='__main__': main()
