#!/usr/bin/env python3
"""Actual pinned native server/cells visual addon; synthetic publications/statuses.

This is not a physical-phone or live-model proof. map_journey --scenario all
owns the real Pi/current UUID/publication/lifetime contract. This addon measures
one attached native canvas at a time and retains actual cells and colors.
"""
import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import re
import subprocess
import uuid
import time
import shutil
import shlex
from map_identity import current_metadata
import proof
from map_journey import Client, log_digest
from map_frames import canvas, contains, wait_frame, selected_in_frame


def capture(client, directory, name):
    frame = client.frame()
    rows = canvas(frame)
    assert rows[0].startswith('Herdr Overview') and 'Esc/q' in rows[-1]
    cells = [[dict(text=client.screen.buffer[y][x].data,
        fg=client.screen.buffer[y][x].fg, bg=client.screen.buffer[y][x].bg)
        for x in range(client.screen.columns)] for y in range(client.screen.lines)]
    value = dict(frame=client.screen.display, canvas=rows, cells=cells,
        outerColumns=client.screen.columns, outerRows=client.screen.lines,
        canvasColumns=len(rows[0]), canvasRows=len(rows), source='actual Herdr 0.9.1 attached client')
    proof.json_dump(directory / (name+'.json'), value)
    colors = dict(black='#11131d',white='#c0caf5',blue='#7aa2f7',green='#9ece6a',
        yellow='#e0af68',brown='#e0af68',red='#f7768e',magenta='#bb9af7',cyan='#7dcfff',
        brightblack='#414868',brightwhite='#c0caf5',brightblue='#7aa2f7',brightgreen='#9ece6a',
        brightyellow='#e0af68',brightred='#f7768e',brightmagenta='#bb9af7',brightcyan='#7dcfff')
    def color(value, fallback):
        return fallback if value == 'default' else colors.get(value, '#'+value if re.fullmatch('[0-9a-f]{6}',value) else fallback)
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{client.screen.columns*9}" height="{client.screen.lines*18}">']
    for y,row in enumerate(cells):
        for x,c in enumerate(row):
            svg.append(f'<rect x="{x*9}" y="{y*18}" width="9" height="18" fill="{color(c["bg"],"#11131d")}"/>')
    for y,row in enumerate(cells):
        for x,c in enumerate(row):
            svg.append(f'<text x="{x*9}" y="{y*18+14}" font-family="monospace" font-size="14" fill="{color(c["fg"],"#c0caf5")}">{html.escape(c["text"])}</text>')
    (directory / (name+'.svg')).write_text(''.join(svg)+'</svg>')
    return value


def source_manifest():
    paths = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard'], cwd=proof.ROOT, text=True).splitlines()
    return {name: hashlib.sha256((proof.ROOT / name).read_bytes()).hexdigest()
        for name in paths if (proof.ROOT / name).is_file()}

def run(receipts):
    receipts.mkdir(mode=0o700, exist_ok=False)
    proof.json_dump(receipts / "source-before.json", source_manifest())
    run_id=proof.make_run_id();base=receipts/'fixtures';root=proof.run_root(run_id,base)
    server=client=None
    record=dict(status='FAIL',phone='pending',realPi='covered separately by map_journey all',
        fixture='synthetic manual publications and reported states on real Pi, genuine current adapter UUID', captures=[], assertions={})
    try:
        root,state,env=proof.setup_herdr_run(run_id,base)
        server=subprocess.Popen([state['herdr_bin'],'server'],env=env,cwd=root,
            stdout=(receipts/'server.log').open('wb'),stderr=subprocess.STDOUT)
        proof.wait_for(lambda: Path(state['socket_path']).exists() and proof.server_status(state,env).get('running'),'isolated native server')
        work=root/'synthetic-work';work.mkdir()
        proof.herdr_cmd(state,env,'workspace','create','--cwd',str(work),'--label','Synthetic delivery')
        snap=proof.snapshot(state);first=snap['panes'][0];ws=first['workspace_id']
        def rename(kind,id,label):proof.api_request(state,kind+'.rename',{kind+'_id':id,'label':label})
        rename('pane',first['pane_id'],'Deployment readiness and rollback checklist')
        rename('tab',first['tab_id'],'Deployment readiness and rollback checklist')
        proof.herdr_cmd(state,env,'tab','create','--workspace',ws,'--cwd',str(work),'--label','Policy review awaiting publication','--no-focus')
        proof.herdr_cmd(state,env,'tab','create','--workspace',ws,'--cwd',str(work),'--label','Release verification pair','--no-focus')
        snap=proof.snapshot(state);multi=next(p for p in snap['panes'] if p['tab_id']==snap['tabs'][-1]['tab_id'])
        proof.herdr_cmd(state,env,'pane','split',multi['pane_id'],'--direction','right','--cwd',str(work),'--no-focus')
        snap=proof.snapshot(state);peer=next(p for p in snap['panes'] if p['tab_id']==multi['tab_id'] and p['pane_id']!=multi['pane_id'])
        rename('pane',multi['pane_id'],'部署 é 😀 rollback verification')
        rename('pane',peer['pane_id'],'Peer review and release notes')
        proof.herdr_cmd(state,env,'workspace','create','--cwd',str(work),'--label','Synthetic research')
        snap=proof.snapshot(state);late=snap['panes'][-1]
        rename('tab',late['tab_id'],'Research notes and next experiments')
        rename('pane',late['pane_id'],'Research notes and next experiments')
        proof.herdr_cmd(state,env,'tab','create','--workspace',late['workspace_id'],'--cwd',str(work),'--label','Manual shell without publication','--no-focus')
        provider=proof.ensure_scripted_provider(root,state,env)
        extension=root/'scripted-pi-provider.mjs';proof.make_pi_provider_extension(extension)
        real_pi=shutil.which('pi')
        if not real_pi:raise proof.ProofBlocked('real Pi executable unavailable')
        proof.write_exec(root/'bin/pi', '#!/bin/sh\nset -eu\nIFS= read -r HERDR_OVERVIEW_TEST_PROVIDER_URL < "$HERDR_OVERVIEW_TEST_PROVIDER_URL_FILE"\nexport HERDR_OVERVIEW_TEST_PROVIDER_URL\nexec '+shlex.quote(real_pi)+' "$@"\n')
        Path(env['HERDR_OVERVIEW_TEST_PROVIDER_URL_FILE']).write_text(provider['url']+'\n')
        Path(env['HERDR_OVERVIEW_PI_REPLY']).write_text('Synthetic visual fixture reply.\n')
        for number,pane in enumerate((first,multi),1):
            proof.herdr_cmd(state,env,'agent','start',f'synthetic-visual-{number}','--kind','pi','--pane',pane['pane_id'],'--timeout','120000','--',
                '--provider','herdr-proof-scripted','--model','scripted-model','--extension',str(proof.ROOT/'dot_pi/private_agent/extensions/herdr-overview/index.ts'),
                '--extension',str(extension),'--no-skills','--no-prompt-templates','--no-themes','--no-context-files','--no-tools','--offline','--approve',
                '--session-dir',str(root/'pi-sessions'),timeout=130)
        first,metadata=proof.wait_for(lambda:current_metadata(state,env,first['pane_id']),'real current Pi native bridge')
        sid=metadata['sessionId']
        for pane,status in ((first,'working'),(multi,'blocked')):
            report_record=proof.wait_for(lambda:current_metadata(state,env,pane['pane_id']),'reported pane genuine UUID')[1]
            response=proof.api_request(state,'pane.report_agent',dict(pane_id=pane['pane_id'],source='synthetic:visual',agent='pi',state=status,agent_session_id=report_record['sessionId'],seq=time.time_ns()//1000))
            proof.json_dump(receipts/(status+'-report.json'),response)
        data=root/'data/session-recap';records=data/'records/2026-10-02';records.mkdir(parents=True,exist_ok=True)
        summary=('The release candidate is ready for a cautious rollout. Configuration checks and the rollback rehearsal completed without changing the running service.\n\n'
            'The remaining decision is whether to publish today or wait for the policy review. Keep the last good artifact available until the new checks finish.\n\n'
            +'\n'.join(f'Checkpoint {n:02d}: verify the current artifact, record the observed result, and preserve a safe rollback path.' for n in range(35))+'\nNATIVE-RECAP-END')
        prompt='Review the deployment checklist, explain what remains blocked, and suggest the smallest safe next action.\n\nNATIVE-PROMPT-END'
        good=dict(schema_version=1,record_id='visual-good',status='published',source_kind='manual',source_id=first['pane_id'],pane_id=first['pane_id'],published_at='2026-10-02T02:00:00Z',summary=summary)
        bad=dict(schema_version=1,record_id='visual-failed',status='failed',source_kind='manual',source_id=first['pane_id'],pane_id=first['pane_id'],created_at='2026-10-02T03:00:00Z',failure=dict(message='The newer attempt could not complete the policy check. The last good recap remains available. NATIVE-FAILURE-END'))
        for value in (good,bad):proof.json_dump(records/(value['record_id']+'.json'),value)
        proof.json_dump(data/'latest.json',dict(sources=[dict(source_kind='manual',source_id=first['pane_id'],latest_success_id='visual-good',last_attempt_id='visual-failed')]))
        proof.json_dump(data/'prompts'/(sid+'.json'),dict(schema_version=1,session_id=sid,pane_id=first['pane_id'],text=prompt))
        digest=('Delivery review: the release candidate passed the configuration checks. The rollback artifact is retained separately from the new publication.\n\n'
            'Policy review remains open. The session digest records this broader context without replacing the latest published recap.\n\n'
            +'\n'.join(f'Digest note {n:02d}: retain the verified observation and keep the next decision explicit.' for n in range(35))+'\nNATIVE-DIGEST-END')
        proof.json_dump(Path(env['HOME'])/'.pi/session-search/digests'/(sid+'.json'),dict(schemaVersion=1,generatedAt='2026-10-02T04:00:00Z',body=digest))
        proof.api_request(state,'pane.focus',dict(pane_id=first['pane_id']))
        proof.api_request(state,'plugin.action.invoke',dict(action_id='overview.refresh_names'))
        baseline=log_digest(root)
        client=Client(state,env,120);client.drain(2)
        def open_map():
            proof.api_request(state,'plugin.action.invoke',dict(action_id='overview.open'))
            wait_frame(client,'Esc/q')
        def save(name):
            value=capture(client,receipts,name);record['captures'].append(name);return value
        native=proof.snapshot(state)
        proof.json_dump(receipts/'native-fixture.json',native)
        proof.json_dump(receipts/'plugin-fixture.json',proof.plugin_state(root))
        for theme in ('tokyo-night','terminal'):
            config=Path(env['HERDR_CONFIG_PATH']);config.write_text(config.read_text().replace('name = "tokyo-night"',f'name = "{theme}"').replace('name = "terminal"',f'name = "{theme}"'))
            for width in (32,40,48,120,180):
                client.resize(width);client.drain(2);open_map();prefix=f'{theme}-{width}'
                collapsed=save(prefix+'-collapsed')
                if theme=='tokyo-night':
                    backgrounds={c['bg'] for row in collapsed['cells'] for c in row}
                    assert '2d3650' in backgrounds and '232636' in backgrounds,backgrounds
                    assert any(c['fg']=='9ece6a' for row in collapsed['cells'] for c in row),'working green missing'
                client.key(b'\r');wait_frame(client,'Latest good recap');save(prefix+'-reading')
                client.key(b'j'*25);middle=client.frame();save(prefix+'-middle')
                client.key(b'd');wait_frame(client,'Session digest');client.key(b'j'*10);digest_middle=client.frame();client.key(b'd');assert client.frame()==digest_middle
                client.key(b'\x1b');assert client.frame()==middle;save(prefix+'-digest-return')
                original=width;client.resize(120 if width<80 else 40);client.resize(original);client.key(b'r');assert client.frame()==middle
                frames=[]
                for _ in range(140):
                    frame=client.frame();frames.append(frame)
                    if contains(frame,'NATIVE-PROMPT-END'):break
                    client.key(b'jjj')
                for marker in ('NATIVE-RECAP-END','Newer attempt failed','NATIVE-FAILURE-END','Supplied prompt','NATIVE-PROMPT-END'):
                    assert any(contains(frame,marker) for frame in frames),marker
                save(prefix+'-recap-failure-prompt');before=client.frame()
                client.key(b'd');wait_frame(client,'Session digest');save(prefix+'-digest')
                client.key(b'j'*500);wait_frame(client,'NATIVE-DIGEST-END');save(prefix+'-digest-end')
                client.key(b'd');client.key(b'\x1b');assert client.frame()==before
                client.key(b'\x1b');client.key(b'n')
                assert selected_in_frame(client.frame(),multi['pane_id'],native)
                blocked=save(prefix+'-blocked')
                assert any('BLOCKED' in row for row in blocked['canvas'])
                if theme=='tokyo-night':assert any(c['fg']=='e0af68' for row in blocked['cells'] for c in row),'blocked gold missing'
                client.key(b'\r');wait_frame(client,'Latest good recap');save(prefix+'-blocked-reading')
                client.key(b']');wait_frame(client,'Peer review');save(prefix+'-peer-reading')
                client.key(b']');wait_frame(client,'Research notes');save(prefix+'-late-reading')
                late_before=client.frame();client.key(b'd');wait_frame(client,'Session digest');client.key(b'd');save(prefix+'-late-digest');client.key(b'\x1b');assert client.frame()==late_before
                client.key(b'q')
        assert log_digest(root)==baseline,'viewing generated backend work'
        record['assertions']=dict(current_full_footer=True,actual_cells_colors=True,five_outer_widths=True,
            two_palettes=True,blocked_selected_exact_native=True,full_recap_failure_prompt_digest=True,
            middle_resize_refresh_digest_return=True,late_digest_idempotent_return=True,viewer_passive=True)
        record['status']='PASS'
    except Exception as exc:
        import traceback
        record['reason']=str(exc);(receipts/'failure-traceback.txt').write_text(traceback.format_exc())
        if client:(receipts/'failure-frame.txt').write_text(client.frame())
    finally:
        if client:
            (receipts/'client.ansi').write_bytes(client.output);client.close()
        if root.exists():record['cleanup']=proof.scenario_cleanup(run_id,base)
        if server:server.wait(timeout=5)
        proof.json_dump(receipts / 'source-after.json', source_manifest())
        proof.json_dump(receipts/'receipt.json',record)
    print(json.dumps(record));return 0 if record['status']=='PASS' else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--receipts',type=Path,required=True)
    raise SystemExit(run(parser.parse_args().receipts.resolve()))
