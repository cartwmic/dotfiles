#!/usr/bin/env python3
"""Disposable public entrypoint + PTY + protocol-22 scripted socket journey."""
import html, hashlib, json, os, pathlib, pty, select, socket, subprocess, tempfile, threading, time, fcntl, termios, struct, re, signal
ROOT = pathlib.Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='overview-popup-pty-') as tmp:
    home = pathlib.Path(tmp)
    sockpath = str(home / 'socket')
    state = home / 'state'; state.mkdir()
    recaps = home / 'data/session-recap'; (recaps / 'records/2026-10-01').mkdir(parents=True)
    sessions = home / 'sessions'; sessions.mkdir()
    digests = home / 'digests'; digests.mkdir()
    config = home / 'config.toml'; config.write_text('[theme]\nname="'+os.environ.get('OVERVIEW_CAPTURE_THEME','tokyo-night')+'"\n')
    sid = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'
    native = dict(protocol=22, version='0.9.1', focused_workspace_id='w', focused_tab_id='t1', focused_pane_id='p1',
        workspaces=[dict(workspace_id='w',label='Synthetic workspace',active_tab_id='t1',number=1)],
        tabs=[dict(tab_id='t'+str(n),workspace_id='w',label='Multi pane group' if n==3 else 'Single '+str(n),number=n) for n in [1,2,3]],
        panes=[dict(pane_id='p'+str(n),workspace_id='w',tab_id='t'+str(min(n,3)),terminal_id='terminal'+str(n),label='Subject '+str(n),title='Native '+str(n),agent='pi' if n!=4 else None,agent_status='blocked' if n==3 else 'working') for n in [1,2,3,4]], agents=[], layouts=[])
    native['workspaces'].append(dict(workspace_id='w2',label='Second workspace',active_tab_id='t5',number=2))
    for n in [5,6]:
        native['tabs'].append(dict(tab_id='t'+str(n),workspace_id='w2',label='Second single '+str(n),number=n))
        native['panes'].append(dict(pane_id='p'+str(n),workspace_id='w2',tab_id='t'+str(n),terminal_id='terminal'+str(n),label='Subject '+str(n),title='Native '+str(n)))
    if os.environ.get('OVERVIEW_VISUAL_PROOF'):
        native['tabs'][0]['label']='Synthetic deployment readiness and rollback checklist'
        native['tabs'][1]['label']='Synthetic policy review with missing publication'
        native['panes'][1]['agent_status']='idle'
        native['panes'][2]['label']='部署 é 😀 rollback verification and safe publication checklist with additional pending checks'; native['panes'][3]['label']='Distinct peer subject';
        native['panes'][4]['agent']='pi'; native['panes'][4]['agent_status']='done'
    native['panes'][0]['agent_session'] = dict(source='herdr:pi', agent='pi', kind='id', value=sid)
    native['agents'] = [dict(pane_id='p1', agent_session=dict(source='herdr:pi', agent='pi', kind='id', value=sid))]
    record = dict(schemaVersion=1,socketPath=sockpath,terminalId='terminal1',paneId='p1',sessionId=sid,sessionName='Synthetic stable session',publisherPid=os.getpid(),generation='fixture-one')
    if os.environ.get('OVERVIEW_VISUAL_PROOF'): record['sessionName']='Synthetic deployment readiness and rollback checklist'
    key = hashlib.sha256(json.dumps([sockpath,'terminal1'],separators=(',',':')).encode()).hexdigest()
    (sessions/(key+'.json')).write_text(json.dumps(record))
    # The overview follows the recap CLI's presentation zone (records stay UTC).
    recap_config = home/'xdg-config'/'session-recap'; recap_config.mkdir(parents=True); (recap_config/'config.toml').write_text('time_zone = "America/New_York"\n')
    (digests/(sid+'.json')).write_text(json.dumps(dict(schemaVersion=1,generatedAt='2026-10-01T02:00:00Z',body='digest synthetic line\n'*100+'DIGEST-FINAL-MARKER')))
    good=dict(schema_version=1,status='published',record_id='good',source_kind='manual',source_id='p1',pane_id='p1',published_at='2026-10-01T00:00:00Z',summary=''.join(f'recap synthetic line {n:03d}\n' for n in range(100))+'RECAP-FINAL-MARKER')
    bad=dict(schema_version=1,status='failed',record_id='bad',source_kind='manual',source_id='p1',pane_id='p1',created_at='2026-10-01T01:00:00Z',failure=dict(message='NEWER-ATTEMPT-ERROR'))
    for value in [good,bad]: (recaps/'records/2026-10-01'/(value['record_id']+'.json')).write_text(json.dumps(value))
    (recaps/'latest.json').write_text(json.dumps(dict(sources=[dict(source_kind='manual',source_id='p1',latest_success_id='good',last_attempt_id='bad')])))
    env={**os.environ,'HOME':tmp,'XDG_DATA_HOME':str(home/'data'),'XDG_STATE_HOME':str(home/'xdg-state'),'XDG_CONFIG_HOME':str(home/'xdg-config'),'HERDR_SOCKET_PATH':sockpath,'HERDR_PLUGIN_STATE_DIR':str(state),'HERDR_CONFIG_PATH':str(config),'HERDR_OVERVIEW_PI_SESSIONS_DIR':str(sessions),'PI_SESSION_SEARCH_DIGEST_DIR':str(digests)}
    calls=[]; busy=False; focus_fail=False
    server=socket.socket(socket.AF_UNIX); server.bind(sockpath); server.listen(); stopped=False
    def serve():
        while not stopped:
            try: conn,_=server.accept()
            except OSError: return
            with conn:
                data=b''
                while b'\n' not in data:
                    chunk=conn.recv(65536)
                    if not chunk: break
                    data+=chunk
                if not data: continue
                req=json.loads(data.split(b'\n')[0]); calls.append(req)
                method=req['method']; result={}
                error=None
                if method=='session.snapshot': result={'snapshot':native}
                elif method=='plugin.pane.open':
                    if busy: error=dict(code='ui_busy',message='fixture modal busy')
                    else: result={'ok':True}
                elif method=='pane.focus':
                    if focus_fail: error=dict(code='invalid_target',message='FOCUS-FAILURE')
                    else: result={'ok':True}
                elif method=='pane.process_info': result={'process_info':None}
                elif method=='pane.read': result={'read':{'text':'TAIL-MUST-NOT-RENDER'}}
                reply={'id':req['id']}
                reply['error' if error else 'result']=error if error else result
                conn.sendall((json.dumps(reply)+'\n').encode())
    threading.Thread(target=serve,daemon=True).start()
    def cli(action): return subprocess.run(['node',str(ROOT/'index.mjs'),action],env=env,capture_output=True,text=True,timeout=10)
    assert cli('open').returncode==0
    opened=calls[-1]; assert opened['method']=='plugin.pane.open'
    assert opened['params']==dict(plugin_id='overview',entrypoint='overview',placement='popup',width='100%',height='100%',focus=True)
    busy=True; response=cli('open'); assert response.returncode==0 and 'ui_busy' in response.stderr; busy=False
    for action in ['startup','reconcile','event']:
        before=len(calls); response=cli(action); assert response.returncode==0,response.stderr
        assert not any(c['method'] in ['plugin.pane.open','pane.close'] for c in calls[before:])
    if os.environ.get('OVERVIEW_VISUAL_PROOF'):
        saved=json.loads((state/'overview.json').read_text())
        saved.setdefault('displayNameOwnership',{})['tab:t1']=dict(mode='automatic',observedLabel=native['tabs'][0]['label'])
        saved['displayNameOwnership']['pane:p1']=dict(mode='automatic',observedLabel=native['panes'][0]['label'])
        saved['displayNameOwnership']['tab:t2']=dict(mode='manual',observedLabel=native['tabs'][1]['label'])
        (state/'overview.json').write_text(json.dumps(saved))
    viewer_start=len(calls)
    def journey(width, focus=False, focus_index=None):
        global focus_fail
        master,slave=pty.openpty(); fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',24,width,0,0))
        process=subprocess.Popen(['node',str(ROOT/'index.mjs'),'overview'],env=env,stdin=slave,stdout=slave,stderr=slave,close_fds=True); os.close(slave)
        transcript=b''
        def read_until(marker,timeout=5):
            nonlocal transcript
            deadline=time.time()+timeout
            start=len(transcript)
            while time.time()<deadline:
                if marker.encode() in transcript[start:] and marker in current_frame() and 'Esc/q' in current_frame():
                    # Drain the whole matching draw, not merely its first marker.
                    readable,_,_=select.select([master],[],[],.12)
                    if not readable: return
                readable,_,_=select.select([master],[],[],.05)
                if readable:
                    try: transcript+=os.read(master,65536)
                    except OSError: break
            raise AssertionError('missing '+marker+'\n'+transcript[-4000:].decode(errors='replace'))
        def current_frame():
            # Inspect only the latest clear-screen frame from the actual viewer PTY,
            # never outer Herdr sidebar labels or accumulated stream substrings.
            raw = transcript.rsplit(b'\x1b[?2026h\x1b[H',1)[-1].decode(errors='replace')
            return re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', raw)
        def finish():
            deadline=time.time()+10
            while process.poll() is None and time.time()<deadline:
                readable,_,_=select.select([master],[],[],.05)
                if readable:
                    try: os.read(master,65536)
                    except OSError: pass
            process.wait(timeout=1)
        def key(value,marker=None):
            os.write(master,value.encode())
            if marker: read_until(marker)
            else: time.sleep(.1)
        try:
            read_until('Overview')
            time.sleep(.1)
            if os.environ.get('OVERVIEW_VISUAL_PROOF'):
                import pyte
                target=pathlib.Path(os.environ['OVERVIEW_VISUAL_PROOF']); target.mkdir(parents=True,exist_ok=True)
                def capture(name):
                    screen=pyte.Screen(width,24); pyte.Stream(screen).feed(transcript.rsplit(b'\x1b[?2026h\x1b[H',1)[-1].decode(errors='replace'))
                    assert 'Herdr Overview' in screen.display[0], screen.display
                    assert 'Esc/q' in screen.display[-1], screen.display
                    for y,line in enumerate(screen.display):
                        if width<80 and line.startswith('│'): assert line.rstrip().endswith('│'), (y,line)
                        if width<80 and ('部署' in line or '😀' in line): assert screen.buffer[y][width-1].data == '│', (y,line)
                    if name.endswith('-blocked-reading') and os.environ.get('OVERVIEW_CAPTURE_THEME','tokyo-night') == 'tokyo-night':
                        assert any(c.fg == 'e0af68' for row in screen.buffer.values() for c in row.values()), 'blocked gold missing'
                    if name.endswith('-collapsed') and os.environ.get('OVERVIEW_CAPTURE_THEME','tokyo-night') == 'tokyo-night':
                        assert any(c.fg == '9ece6a' for row in screen.buffer.values() for c in row.values()), 'working green missing'
                        assert any(c.fg == '7aa2f7' for row in screen.buffer.values() for c in row.values()), 'ready/selected blue missing'
                    cells=[[dict(text=screen.buffer[y][x].data,fg=screen.buffer[y][x].fg,bg=screen.buffer[y][x].bg) for x in range(width)] for y in range(24)]
                    (target/(name+'.json')).write_text(json.dumps(dict(frame=screen.display,cells=cells),indent=2))
                    svg=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width*9}" height="432"><rect width="100%" height="100%" fill="#11131d"/>']
                    colors=dict(red='#f7768e',cyan='#7dcfff',brown='#e0af68',brightblack='#414868',brightred='#f7768e',brightgreen='#9ece6a',brightyellow='#e0af68',brightblue='#7aa2f7',brightmagenta='#bb9af7',brightcyan='#7dcfff',brightwhite='#c0caf5',blue='#7aa2f7',yellow='#e0af68',green='#9ece6a',magenta='#bb9af7',white='#c0caf5',black='#11131d')
                    def color(v,fallback): return fallback if v == 'default' else colors.get(v,'#'+v if re.fullmatch('[0-9a-f]{6}',v) else fallback)
                    # Paint all backgrounds first so a neighboring cell cannot erase a wide glyph.
                    for y,row in enumerate(cells):
                        for x,c in enumerate(row):
                            svg.append(f'<rect x="{x*9}" y="{y*18}" width="9" height="18" fill="{color(c["bg"],"#11131d")}"/>')
                    for y,row in enumerate(cells):
                        for x,c in enumerate(row):
                            svg.append(f'<text x="{x*9}" y="{y*18+14}" font-family="monospace" font-size="14" fill="{color(c["fg"],"#c0caf5")}">{html.escape(c["text"])}</text>')
                    (target/(name+'.svg')).write_text(''.join(svg)+'</svg>')
                    return screen
                screen=capture(f'after-{width}-collapsed')
                assert any('┌' in line and '┐' in line for line in screen.display)
                assert any(c.bg != 'default' for row in screen.buffer.values() for c in row.values())
                if os.environ.get('OVERVIEW_CAPTURE_THEME','tokyo-night') == 'tokyo-night':
                    backgrounds={c.bg for row in screen.buffer.values() for c in row.values()}
                    assert '2d3650' in backgrounds and '232636' in backgrounds, backgrounds
                # Ready Tab 2 sorts above working Tab 1 (blocked Tab 3 group is first).
                key('[','READY'); capture(f'after-{width}-manual-selected'); assert '› Tab 2 M' in current_frame()
                key(']','WORKING')
                key('\r','Latest good recap'); capture(f'after-{width}-reading')
                key('j'*40,'recap synthetic line'); capture(f'after-{width}-middle')
                passage=re.search(r'recap synthetic line \d+',current_frame()).group()
                original_width=width
                width=120 if width<80 else 32
                fcntl.ioctl(master,termios.TIOCSWINSZ,struct.pack('HHHH',24,width,0,0)); os.kill(process.pid,signal.SIGWINCH)
                read_until(passage); capture(f'after-{original_width}-resize-{width}')
                width=original_width
                fcntl.ioctl(master,termios.TIOCSWINSZ,struct.pack('HHHH',24,width,0,0)); os.kill(process.pid,signal.SIGWINCH)
                read_until(passage); capture(f'after-{width}-resize-return')
                key('r',passage); assert passage in current_frame()
                middle=current_frame(); key('d','Session digest'); key('j'*20,'digest synthetic line'); digest_middle=current_frame(); key('d','digest synthetic line'); assert current_frame()==digest_middle
                key('\x1b',passage); assert current_frame()==middle
                key('j'*55,'RECAP-FINAL-MARKER'); before=current_frame()
                capture(f'after-{width}-recap-tail')
                key('d','Session digest'); key('j'*130,'DIGEST-FINAL-MARKER'); digest_before=current_frame(); key('d','DIGEST-FINAL-MARKER'); assert current_frame()==digest_before; capture(f'after-{width}-digest-tail')
                assert 'Second workspace' not in current_frame()
                key('\x1b','RECAP-FINAL-MARKER'); assert current_frame()==before
                key('\x1b','Herdr Overview'); key('n','BLOCKED'); capture(f'after-{width}-blocked')
                key('\r','Latest good recap'); capture(f'after-{width}-blocked-reading')
                assert '部署' in current_frame()
                key('j'*10,'Distinct peer subject'); capture(f'after-{width}-peer-reading')
                key(']'*4,'Latest good recap'); assert 'Second' in current_frame(); capture(f'after-{width}-late-reading')
                late=current_frame(); key('d','Session digest'); assert 'Unavailable' in current_frame(); key('d','Session digest'); capture(f'after-{width}-late-digest')
                key('\x1b','Latest good recap'); assert current_frame()==late
                assert 'Process ' not in current_frame()
                key('q'); finish(); assert process.returncode==0
                return len(transcript)
            if focus_index is not None:
                # Displayed order: blocked group (p3,p4), then p1, p2, then p5, p6.
                display=[native['panes'][i]['pane_id'] for i in [2,3,0,1,4,5]]
                key(']'*focus_index)
                expected=display[(2+focus_index)%6]
                # Enter opens the recap, a second Enter focuses the pane.
                before=len(calls); key('\r','Latest good recap'); assert not any(c['method']=='pane.focus' for c in calls[before:])
                key('\r'); finish()
                assert process.returncode==0
                assert calls[-1]['method']=='pane.focus' and calls[-1]['params']['pane_id']==expected
                return expected
            frame=current_frame(); rows=frame.splitlines()
            assert 'TAIL-MUST-NOT-RENDER' not in frame
            assert any('Single 1' in line and 'Single 2' in line for line in rows)
            if width < 100:
                assert not any('Synthetic workspace' in line and 'Second workspace' in line for line in rows)
                key(']'*2,'Second workspace')
                assert '› Tab 5' in current_frame()
                key(']'*4,'› Tab 1')
            else:
                # The blocked group sits on top, so its selection shows the headings.
                key('n','› Pane'); key('\x1b[<64;5;5M','Synthetic workspace'); rows=current_frame().splitlines()  # wheel up to the headings
                headings=next(line for line in rows if 'Synthetic workspace' in line and 'Second workspace' in line)
                assert headings.index('Second workspace') > headings.index('Synthetic workspace')
                assert any('› Pane' in line and 'Second single 5' in line for line in rows), '\n'.join(rows)
                key(']]','› Tab 1')
            # Traversal follows the displayed order: questions, ready, working, then others.
            for target in ['p2','p5','p6','p3','p4','p1']:
                key(']')
                key('\r', 'Latest good recap')
                assert 'Latest good recap' in current_frame()
                if target in ['p3','p4']: assert 'Subject '+target[1:] in current_frame()
                key('\x1b','Herdr Overview')
            # A left click on a card opens its recap in place and never focuses.
            rows=current_frame().splitlines(); y=next(i for i,line in enumerate(rows) if 'Single 2' in line); x=rows[y].index('Single 2')
            before=len(calls); key(f'\x1b[<0;{x+1};{y+1}M','Latest good recap')
            assert '› Tab' not in current_frame() and not any(c['method']=='pane.focus' for c in calls[before:])
            key('\x1b','Herdr Overview'); assert '› Tab 2' in current_frame(); key('[','› Tab 1')
            native['panes'][0]['agent_status']='idle'
            key('r','READY')
            native['panes'][0]['agent_status']='working'
            key('\r','Latest good recap')
            key('j'*95,'RECAP-FINAL-MARKER')
            assert 'DIGEST-FINAL-MARKER' not in current_frame()
            assert 'Second workspace' not in current_frame()
            key('d','Session digest · 2026-09-30')  # the time may wrap at 40 columns
            assert '22:00:00' in current_frame()
            key('j'*130,'DIGEST-FINAL-MARKER')
            assert 'RECAP-FINAL-MARKER' not in current_frame()
            assert 'NEWER-ATTEMPT-ERROR' not in current_frame()
            key('\x1b','RECAP-FINAL-MARKER')
            key('\x1b','Herdr Overview')
            key('n','BLOCKED')
            if focus:
                focus_fail=True; key('f','FOCUS-FAILURE'); assert process.poll() is None
                native['panes'][2]['pane_id']='moved-p3'
                key('r','Subject 3'); focus_fail=False
                key('f'); finish()
                assert calls[-1]['method']=='pane.focus' and calls[-1]['params']['pane_id']=='moved-p3'
            else:
                key(']]')
                lost=native['panes'].pop(0)
                key('r')
                key('f','Cannot focus:')
                assert process.poll() is None
                native['panes'].insert(0,lost)
                key('\x1b'); finish()
            assert process.returncode==0
            return len(transcript)
        finally:
            if process.poll() is None: process.kill(); process.wait()
            os.close(master)
    if os.environ.get('OVERVIEW_VISUAL_PROOF'):
        widths=[32,40,48,120,180]
        sizes=[journey(width) for width in widths]
        print(json.dumps(dict(ok=True,widths=widths,bytes=sizes)))
        raise SystemExit(0)
    def rejected_identity(identity):
        native['agents'][0]['agent_session'] = identity
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 120, 0, 0))
        process = subprocess.Popen(['node', str(ROOT/'index.mjs'), 'overview'], env=env,
            stdin=slave, stdout=slave, stderr=slave, close_fds=True)
        os.close(slave)
        output = b''
        def wait(marker):
            nonlocal output
            deadline = time.time()+10
            while time.time()<deadline:
                if select.select([master], [], [], .05)[0]:
                    output += os.read(master, 65536)
                frame = output.rsplit(b'\x1b[?2026h\x1b[H', 1)[-1]
                if marker.encode() in frame:
                    return frame
            raise AssertionError('missing negative identity frame '+marker)
        try:
            wait('Herdr Overview'); os.write(master, b'd')
            frame = wait('Unavailable')
            assert b'DIGEST-FINAL-MARKER' not in frame
            os.write(master, b'f')
            deadline = time.time()+10
            while process.poll() is None and time.time()<deadline:
                if select.select([master], [], [], .05)[0]:
                    try: os.read(master, 65536)
                    except OSError: pass
            process.wait(timeout=1)
            assert process.returncode == 0
            assert calls[-1]['method'] == 'pane.focus' and calls[-1]['params']['pane_id'] == 'p1'
        finally:
            if process.poll() is None: process.kill(); process.wait()
            os.close(master)
    for identity in [dict(agent='pi', kind='id', value='00000000-0000-0000-0000-000000000000'),
                     dict(agent='pi', kind='path', value=sid), dict(agent='codex', kind='id', value=sid)]:
        rejected_identity(identity)
    native['agents'][0]['agent_session'] = dict(source='herdr:pi', agent='pi', kind='id', value=sid)
    narrow=journey(40)
    wide=journey(120,True)
    focused=[journey(120,focus_index=i) for i in range(6)]
    assert focused==['p1','p2','p5','p6','moved-p3','p4']
    viewer_calls=calls[viewer_start:]
    assert all(c['method'] in ['session.snapshot','pane.focus'] for c in viewer_calls),viewer_calls
    assert not any('generate' in c['method'] or 'recap' in c['method'] for c in viewer_calls)
    stopped=True; server.close()
    print(json.dumps(dict(status='PASS',current_frame_layout='wide workspace columns; narrow stacked workspace two-card rows',display_order=['p3','p4','p1','p2','p5','p6'],exact_focus_targets=focused,narrow_bytes=narrow,wide_bytes=wide,viewer_methods=[c['method'] for c in viewer_calls],generation_requests=0)))
