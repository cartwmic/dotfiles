#!/usr/bin/env python3
"""Argv-safe timed recorder/exporter. No input capture or automatic downloads."""
import argparse,hashlib,json,os,shlex,subprocess,sys,time,shutil,fcntl,termios,struct,signal,math,unicodedata
from pathlib import Path
BASE=Path(__file__).resolve().parent
ASSETS=BASE/'assets'
def dependency(name):
 path=shutil.which(name)
 if not path: raise RuntimeError('Missing executable dependency on PATH: '+name)
 return Path(path)
FF=None
def run(args,cwd=None): subprocess.run([str(x) for x in args],check=True,cwd=cwd)
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def safe(v): return json.dumps(v,ensure_ascii=True).replace('<','\\u003c')
def load_actions(path,duration):
 if path is None:return []
 path=Path(path)
 if path.stat().st_size>512*1024:raise ValueError('Action log exceeds 512 KiB')
 rows=json.loads(path.read_text())
 if not isinstance(rows,list) or len(rows)>256:raise ValueError('Actions must be an array of at most 256 explicit inputs')
 previous=0
 for row in rows:
  if not isinstance(row,dict) or set(row)!={'time','kind','value'}:raise ValueError('Action needs exactly time, kind and value')
  t=row['time'];value=row['value']
  if type(t) not in (int,float) or not math.isfinite(t) or not previous<=t<=duration:raise ValueError('Action time must be finite, ordered and within the original cast')
  if row['kind'] not in ('key','text') or not isinstance(value,str) or not value or len(value)>2048:raise ValueError('Action kind/value invalid or too long')
  if any(unicodedata.category(c)=='Cc' and c not in ('\n','\t') for c in value) or (row['kind']=='key' and ('\n' in value or '\t' in value)):raise ValueError('Action values cannot contain terminal controls')
  previous=t
 return rows
def action_text(actions,t):
 recent=[row for row in actions if row['time']<=t<row['time']+3]
 rows=[]
 for row in recent:
  label=f"[{row['time']:.2f}s] {'Typed' if row['kind']=='text' else 'Key'}: {row['value']}"
  if rows and row['kind']=='key' and row['value']=='Enter' and previous['kind']=='text' and row['time']==previous['time']:
   rows[-1]+=' · Key: Enter'
  elif rows and row['kind']=='key' and previous['kind']=='key':
   rows[-1]+=' · '+label
  else:rows.append(label)
  previous=row
 return 'Recorded input (annotation)\n'+('\n'.join(rows) or 'No recent input')
def wrap_action(text,columns):
 # Conservative terminal-cell wrapping; user data never enters an FFmpeg expression.
 rows=[];line='';width=0
 for char in text.expandtabs(4):
  if char=='\n':rows.append(line);line='';width=0;continue
  cell=0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in ('W','F') else 1
  if width+cell>columns:rows.append(line);line='';width=0
  line+=char;width+=cell
 rows.append(line);return rows
def movie_overlay(out,actions,duration):
 if not actions:return '',0
 header=(out/'render.gif').read_bytes()[:10]
 if header[:3]!=b'GIF':raise ValueError('Overlay requires the exported GIF')
 width,height=struct.unpack('<HH',header[6:10]);columns=max(1,(width-24)//12)
 boundaries=sorted({0,duration,*[row['time'] for row in actions],*[min(duration,row['time']+3) for row in actions]})
 spans=[];max_rows=0
 for start,end in zip(boundaries,boundaries[1:]):
  if end<=start:continue
  rows=wrap_action(action_text(actions,start),columns)
  if len(rows)>16:raise ValueError('Input overlay exceeds 16 lines; split long typing into actual input chunks')
  spans.append((start,end,'\n'.join(rows)));max_rows=max(max_rows,len(rows))
 band=max_rows*24+16;directory=out/'input-overlay';directory.mkdir(mode=0o700,exist_ok=True)
 filters=[f"pad=ceil(iw/2)*2:ceil((ih+{band})/2)*2:color=0x171717"]
 for i,(start,end,text) in enumerate(spans):
  name=f"input-overlay/{i:04d}.txt";(out/name).write_text(text);os.chmod(out/name,0o600)
  filters.append(f"drawtext=textfile={name}:font=monospace:fontsize=18:fontcolor=white:x=12:y={height+8}:line_spacing=6:expansion=none:enable='gte(t,{start:.9f})*lt(t,{end:.9f})'")
 return ','.join(filters),band
def export(out,chapters=None,actions_path=None):
 cast=out/'record.cast'; original=sha(cast); lines=[json.loads(x) for x in cast.read_text().splitlines()]
 if not lines or lines[0].get('version')!=3: raise ValueError('Only asciicast v3 is supported; source unchanged')
 duration=sum(x[0] for x in lines[1:]); exitcode=next((int(x[2]) for x in reversed(lines[1:]) if x[1]=='x'),None)
 elapsed=0;last_output=0
 for event in lines[1:]:
  elapsed+=event[0]
  # agg renders no frame for a trailing resize; only output ends the visible movie.
  if event[1]=='o':last_output=elapsed
 final_dwell=max(.001,duration-last_output)
 actions_source=Path(actions_path) if actions_path else out/'actions.json' if (out/'actions.json').exists() else None
 actions=load_actions(actions_source,duration)
 actions_hash=sha(actions_source) if actions_source else None
 run([dependency('agg'),'--idle-time-limit',str(duration+60),'--last-frame-duration',str(final_dwell if final_dwell>=.5 else 0),'--no-loop',cast,out/'render.gif'])
 overlay,overlay_height=movie_overlay(out,actions,duration)
 movie_filter='fps=30,'+(overlay or 'pad=ceil(iw/2)*2:ceil(ih/2)*2')
 run([FF,'-y','-i',out/'render.gif','-fps_mode','cfr','-c:v','libx264','-pix_fmt','yuv420p','-vf',movie_filter,'-t',str(duration),'-movflags','+faststart',out/'phone.mp4'],cwd=out)
 if actions_source:
  (out/'actions.json').write_text(json.dumps(actions,ensure_ascii=False,indent=2)+'\n');os.chmod(out/'actions.json',0o600)
 run([FF,'-v','error','-i',out/'phone.mp4','-f','null','-'])
 import re
 def media_duration(path):
  info=subprocess.run([str(FF),'-hide_banner','-i',str(path)],capture_output=True,text=True).stderr
  match=re.search(r'Duration: (\d+):(\d+):([\d.]+)',info)
  if not match:raise RuntimeError('Cannot inspect media duration: '+str(path))
  h,m,s=map(float,match.groups());return h*3600+m*60+s
 gif_duration=media_duration(out/'render.gif');movie_duration=media_duration(out/'phone.mp4')
 if abs(movie_duration-duration)>.2 or gif_duration<duration-.2:raise RuntimeError('Derived movie/GIF duration mismatch')
 ch=json.loads(Path(chapters).read_text()) if chapters else []
 label=(out/'label.txt').read_text() if (out/'label.txt').exists() else 'Timed terminal recording; original cast preserved. Current-frame text uses the pinned player DOM.'
 import html as html_escape
 html='<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Terminal review</title><style>'+ (ASSETS/'asciinema-player.css').read_text()+'\nbody{margin:8px;background:#171717;color:white;font:16px sans-serif}button{padding:12px;margin:4px}#frame{overflow:auto;background:white;color:black;white-space:pre;font:12px monospace;user-select:text}#screen{max-width:100%}#input-keys{white-space:pre-wrap;overflow-wrap:anywhere;background:#171717;color:white;padding:12px;font:16px monospace;min-height:3em;user-select:text}</style><h1>Terminal review</h1><p>'+html_escape.escape(label)+'</p><div id="screen"></div><pre id="input-keys" aria-label="Recorded input annotation"></pre><button onclick="player.pause()">Pause</button><button onclick="snapshot()">Current frame</button><button onclick="selectFrame()">Select text</button><button onclick="copyFrame()">Copy text</button><span id="stamp"></span><div id="chapters"></div><pre id="frame" tabindex="0"></pre><script>'+ (ASSETS/'asciinema-player.min.js').read_text().replace('</script','<\\/script')+'</script><script>const cast='+safe(cast.read_text())+';const chapters='+safe(ch)+';const actions='+safe(actions)+';const player=AsciinemaPlayer.create({data:cast},document.getElementById("screen"),{autoPlay:false,fit:"width",idleTimeLimit:Infinity});window.player=player;\n'+r'''
function extractFrame(){
 const pre=document.querySelector('.ap-term-text'); if(!pre) throw Error('Pinned player text DOM missing');
 const cols=Number(getComputedStyle(pre).getPropertyValue('--term-cols'));const cell=pre.getBoundingClientRect().width/cols;if(!cell)throw Error('Pinned player cell geometry unavailable');
 return [...pre.querySelectorAll('.ap-line')].map(row=>{let text='',column=0;for(const span of row.children){const offset=Number(span.style.getPropertyValue('--offset'));text+=' '.repeat(Math.max(0,offset-column))+span.textContent;column=offset+Math.round(span.getBoundingClientRect().width/cell);}return text;}).join('\n');
}
function inputText(t){const recent=actions.filter(a=>a.time<=t&&t<a.time+3),rows=[];let previous;for(const a of recent){const label='['+a.time.toFixed(2)+'s] '+(a.kind==='text'?'Typed':'Key')+': '+a.value;if(rows.length&&a.kind==='key'&&a.value==='Enter'&&previous.kind==='text'&&a.time===previous.time)rows[rows.length-1]+=' · Key: Enter';else if(rows.length&&a.kind==='key'&&previous.kind==='key')rows[rows.length-1]+=' · '+label;else rows.push(label);previous=a;}return 'Recorded input (annotation)\n'+(rows.join('\n')||'No recent input');}
function updateInput(){document.getElementById('input-keys').textContent=actions.length?inputText(player.getCurrentTime()):'';}
setInterval(updateInput,100);
function snapshot(){player.pause();updateInput();document.getElementById('frame').textContent=extractFrame();document.getElementById('stamp').textContent=player.getCurrentTime().toFixed(2)+'s';return extractFrame();}
function selectFrame(){snapshot();const r=document.createRange();r.selectNodeContents(document.getElementById('frame'));const s=getSelection();s.removeAllRanges();s.addRange(r);}
async function copyFrame(){selectFrame();try{await navigator.clipboard.writeText(document.getElementById('frame').textContent);}catch(e){document.execCommand('copy');}}
for(const chapter of chapters){const b=document.createElement('button');b.textContent=chapter.label+' ('+chapter.time.toFixed(1)+'s)';b.onclick=async()=>{player.pause();await player.seek(chapter.time);setTimeout(snapshot,150);};document.getElementById('chapters').appendChild(b);}
window.snapshot=snapshot;
'''+'</script>'
 (out/'phone.html').write_text(html)
 assert sha(cast)==original
 versions={}
 for name,args in [('asciinema',[dependency('asciinema'),'--version']),('agg',[dependency('agg'),'--version']),('ffmpeg',[FF,'-version'])]: versions[name]={'version':subprocess.check_output([str(x) for x in args],text=True).splitlines()[0],'sha256':sha(Path(args[0]))}
 versions['utility']={'sha256':sha(Path(__file__))}
 versions['player']={'version':'3.17.0','js_sha256':sha(ASSETS/'asciinema-player.min.js'),'css_sha256':sha(ASSETS/'asciinema-player.css')}
 (out/'metadata.json').write_text(json.dumps({'cast_duration':duration,'renderer_added_tail_removed':max(0,gif_duration-duration),'actual_exit_dwell':final_dwell,'gif_duration':gif_duration,'movie_duration':movie_duration,'cast_header':lines[0],'exit':exitcode,'cast_sha256':original,'actions':{'enabled':bool(actions),'source_sha256':actions_hash,'count':len(actions),'display_seconds':3,'overlay_height':overlay_height,'original_cast_changed':False,'raw_input_capture':False},'dependencies':versions,'movie_timing':'Derived GIF centisecond/agg FPS and MP4 30fps quantization; no speedup or idle clamp. Only renderer-added tail beyond original cast end removed by -t cast duration; every original interval retained. CFR preserves GIF final packet duration; VFR rejected by resize duration test. Cast is archival timing.','files':{p.name:{'sha256':sha(p),'bytes':p.stat().st_size} for p in out.iterdir() if p.is_file() and p.name!='metadata.json'}},indent=2))
def main():
 p=argparse.ArgumentParser();p.add_argument('--output-dir',required=True);p.add_argument('--size',default='48x32');p.add_argument('--chapters');p.add_argument('--actions',help='Explicit safe input JSON; never raw keylogging');p.add_argument('--label');p.add_argument('--export-only',action='store_true');p.add_argument('command',nargs=argparse.REMAINDER);a=p.parse_args();out=Path(a.output_dir).resolve()
 global FF
 FF=dependency('ffmpeg')
 if a.export_only: export(out,a.chapters,a.actions);return 0
 cmd=a.command[1:] if a.command[:1]==['--'] else a.command
 if not cmd:p.error('command required')
 import re
 if not re.fullmatch(r'[1-9][0-9]*x[1-9][0-9]*',a.size) or any(int(v)>65535 for v in a.size.split('x')):p.error('size must be COLSxROWS (1..65535)')
 recorder=dependency('asciinema')
 dependency('agg')
 if not shutil.which(cmd[0]):p.error('command executable unavailable: '+cmd[0])
 out.mkdir(parents=True,mode=0o700,exist_ok=False);os.chmod(out,0o700)
 if a.label:(out/'label.txt').write_text(a.label)
 config=out/'recorder-config';config.mkdir(mode=0o700);(config/'config.toml').write_text('[session]\ncapture_input = false\n')
 sizeargs=['--window-size',a.size];oldsize=None
 previous=None;handler_installed=False
 try:
  if os.isatty(0):
   oldsize=fcntl.ioctl(0,termios.TIOCGWINSZ,b'\0'*8);cols,rows=map(int,a.size.split('x'));fcntl.ioctl(0,termios.TIOCSWINSZ,struct.pack('HHHH',rows,cols,0,0));sizeargs=[]
  child=subprocess.Popen([str(recorder),'record','--return',*sizeargs,'--command',shlex.join(cmd),str(out/'record.cast')],env={**os.environ,'ASCIINEMA_CONFIG_HOME':str(config)})
  previous=signal.signal(signal.SIGWINCH,lambda *_:child.send_signal(signal.SIGWINCH) if child.poll() is None else None)
  handler_installed=True
  rc=child.wait()
 finally:
  try:
   if handler_installed:signal.signal(signal.SIGWINCH,previous)
  finally:
   if oldsize is not None:fcntl.ioctl(0,termios.TIOCSWINSZ,oldsize)
 (out/'command.json').write_text(json.dumps({'argv':cmd,'recorder_exit':rc}))
 try: export(out,a.chapters,a.actions)
 except Exception as error:
  (out/'export-failure.json').write_text(json.dumps({'status':'FAIL','error':repr(error),'recorder_exit':rc}))
  print('Export failed: '+repr(error),file=sys.stderr)
  return rc if rc else 1
 return rc
if __name__=='__main__':sys.exit(main())
