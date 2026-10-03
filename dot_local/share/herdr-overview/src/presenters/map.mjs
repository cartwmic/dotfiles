import { markdownLines, plainMarkdown } from '../markdown.mjs';
import { displayTime } from '../time.mjs';
const clean = value => String(value ?? '').replace(/\x1b\[[0-?]*[ -/]*[@-~]/g, '').replace(/\t/g, '    ').replace(/[\x00-\x08\x0b-\x1f\x7f]/g, ' ');
// Keep ANSI, combining sequences and emoji clusters out of cell arithmetic.
const segmenter = new Intl.Segmenter(undefined, { granularity: 'grapheme' });
const graphemes = value => [...segmenter.segment(clean(value))].map(part => part.segment);
function cells(value) {
  if (/^[\p{Mark}\u200d\ufe0f]+$/u.test(value)) return 0;
  const cp = value.codePointAt(0);
  return /\p{Emoji_Presentation}|\p{Regional_Indicator}|\u20e3/u.test(value) || value.includes('\ufe0f') && /\p{Extended_Pictographic}/u.test(value) || cp >= 0x1100 && (cp <= 0x115f || cp === 0x2329 || cp === 0x232a || cp >= 0x2e80 && cp <= 0xa4cf || cp >= 0xac00 && cp <= 0xd7a3 || cp >= 0xf900 && cp <= 0xfaff || cp >= 0xfe10 && cp <= 0xfe6f || cp >= 0xff01 && cp <= 0xff60 || cp >= 0xffe0 && cp <= 0xffe6 || cp >= 0x20000) ? 2 : 1;
}
export const cellWidth = value => graphemes(value).reduce((sum, g) => sum + cells(g), 0);
function clip(value, width) { let result = '', used = 0; for (const g of graphemes(value)) { if (used + cells(g) > width) break; result += g; used += cells(g); } return result; }
const pad = (value, width) => value + ' '.repeat(Math.max(0, width - cellWidth(value)));
function compact(value, width) { const text = clean(value).replace(/\s+/g, ' '); return cellWidth(text) > width ? clip(text, Math.max(0, width - 1)) + '…' : text; }
export function wrap(value, width) {
  width = Math.max(1, width);
  return clean(value).split(/\r?\n/).flatMap(line => {
    if (!line) return [''];
    const parts = []; let rest = graphemes(line);
    while (rest.length) {
      let count = 0, used = 0, space = -1;
      while (count < rest.length && used + cells(rest[count]) <= width) { used += cells(rest[count]); if (/\s/u.test(rest[count])) space = count; count++; }
      if (count < rest.length && space > 0) count = space + 1;
      count = Math.max(1, count); parts.push(rest.splice(0, count).join(''));
    }
    return parts;
  });
}
// Wrap styled spans at spaces like wrap(); continuation rows hang under the prefix.
function wrapSpans(prefix, spans, width) {
  let indent = prefix.reduce((sum, span) => sum + cellWidth(span.text), 0);
  if (width - indent < 8) { prefix = []; indent = 0; }
  const items = spans.flatMap(span => graphemes(span.text).map(g => ({ g, span }))), rows = [];
  if (!items.length) return [prefix];
  while (items.length) {
    let count = 0, used = 0, space = -1;
    while (count < items.length && used + cells(items[count].g) <= width - indent) { used += cells(items[count].g); if (/\s/u.test(items[count].g)) space = count; count++; }
    if (count < items.length && space > 0) count = space + 1;
    const row = [];
    for (const { g, span } of items.splice(0, Math.max(1, count))) { if (row.at(-1)?.source === span) row.at(-1).text += g; else row.push({ ...span, source: span, text: g }); }
    rows.push([...(rows.length ? (indent ? [{ text: ' '.repeat(indent) }] : []) : prefix), ...row]);
  }
  return rows;
}
const title = value => value?.label || value?.sessionName || value?.subject || value?.title || value?.terminalTitle || 'Unavailable';
const fullTitle = tab => tab.displayNameOwnership?.mode === 'manual' ? title(tab) : tab.fullTitle || title(tab);
const paneTitle = pane => pane.displayNameOwnership?.mode === 'manual' ? title(pane) : pane.paneSubject || pane.sessionName || pane.subject || title(pane);
export function paint(token, bg = false) {
  if (token?.kind === 'reset') return `\x1b[${bg ? 49 : 39}m`;
  if (token?.kind === 'rgb' && /^#[0-9a-f]{6}$/i.test(token.hex)) return `\x1b[${bg ? 48 : 38};2;${token.hex.slice(1).match(/../g).map(x => parseInt(x, 16)).join(';')}m`;
  const codes = { black:30,red:31,green:32,yellow:33,blue:34,magenta:35,purple:35,cyan:36,white:37,gray:37,grey:37,darkgray:90,darkgrey:90,lightred:91,lightgreen:92,lightyellow:93,lightblue:94,lightmagenta:95,lightcyan:96,lightwhite:97 };
  return token?.kind === 'ansi' && codes[token.name] ? `\x1b[${codes[token.name] + (bg ? 10 : 0)}m` : '';
}
const awaiting = pane => pane.agent?.status === 'blocked' && pane.agent?.stateLabels?.blocked === 'Awaiting answer';
const stateName = pane => awaiting(pane) ? '× Awaiting answer' : pane.agent?.recognized ? ({ idle:'READY', blocked:'× BLOCKED' }[pane.agent.status] || pane.agent.status?.toUpperCase() || 'UNKNOWN') : pane.agent?.present ? 'UNKNOWN' : 'NO AGENT';
const stateColor = pane => !pane.agent?.recognized ? 'overlay0' : ({ blocked:'red', working:'green', idle:'blue', done:'teal' }[pane.agent?.status] || 'overlay0');
function blocked(model, ids) { return ids.filter(id => model.panes[id]?.agent?.recognized && model.panes[id]?.agent?.status === 'blocked').length; }
export function mapLines(state, width, now = Date.now()) {
  const { model, journey } = state, palette = state.theme?.palette;
  const when = (value, label = true) => value ? displayTime(value, state.timeZone ?? 'local', label) : value;
  const style = (text, role = 'text', surface = 'panel_bg') => `${paint(palette?.[role])}${paint(palette?.[surface], true)}${text}\x1b[0m`;
  const columns = Math.max(1, Math.min(model.workspaceOrder.length, Math.floor((width + 3) / 55)));
  const workspaceWidth = Math.floor((width - (columns - 1) * 3) / columns);
  const chunks = model.workspaceOrder.map(workspaceId => {
    const workspace = model.workspaces[workspaceId], lines = []; let anchor = 0, end = null, positions = [], selectedLine = 0, rectangles = [];
    const cellSize = Math.floor((workspaceWidth - 2) / 2);
    const box = (content, size, border = 'overlay1', selected = false, overrideSurface = null) => {
      const surface = overrideSurface || (selected ? 'selection_bg' : 'active_row_bg'), inner = Math.max(1, size - 4);
      const edge = text => style(text, border, surface);
      return [edge('┌' + '─'.repeat(size - 2) + '┐'), edge('│' + ' '.repeat(size - 2) + '│'),
        ...content.map(row => edge('│ ') + (row.spans ? spanRow(row, inner, row.surface || surface) : (row.bold ? '\x1b[1m' : '') + style(pad(clip(row.text, inner), inner), row.role || 'text', row.surface || surface)) + edge(' │')),
        edge('│' + ' '.repeat(size - 2) + '│'), edge('└' + '─'.repeat(size - 2) + '┘')];
    };
    const spanRow = (row, inner, surface) => { let used = 0, out = '';
      for (const span of row.spans) { const text = clip(span.text, inner - used); if (!text) continue; used += cellWidth(text); out += (span.bold ? '\x1b[1m' : '') + (span.italic ? '\x1b[3m' : '') + style(text, span.role || row.role || 'text', surface); }
      return out + style(' '.repeat(Math.max(0, inner - used)), row.role || 'text', surface); };
    // extra: rows a taller paired card would otherwise leave blank; the recap fills them.
    const card = (tab, pane, size, extra = 0) => {
      const selected = pane.id === journey?.paneId, multi = tab.paneIds.length > 1;
      const wrapped = wrap(multi ? paneTitle(pane) : fullTitle(tab), size - 4);
      const names = wrapped.slice(0, 2);
      if (wrapped.length > 2) names[1] = clip(names[1].trimEnd(), Math.max(0, size - 5)) + '…';
      while (names.length < 2) names.push(''); // fixed title block keeps paired rows aligned
      const manual = (multi ? pane : tab).displayNameOwnership?.mode === 'manual';
      const latest = pane.recap?.latest, attempt = pane.recap?.lastAttempt;
      const good = latest?.status === 'published';
      const warning = attempt && attempt.record_id !== latest?.record_id ? wrap(`Newer attempt ${attempt.status}`, size - 4) : [];
      // At least two preview lines; an unused warning slot goes to the recap.
      const budget = 2 + extra + (warning.length ? 0 : 1);
      const excerpt = wrap(good ? plainMarkdown(latest.summary) || 'Unavailable' : 'Unavailable · no published recap', size - 4).filter((line, i, all) => line.trim() || (i > 0 && all[i - 1].trim()));
      const preview = excerpt.slice(0, budget);
      if (excerpt.length > budget) preview[budget - 1] = clip(preview[budget - 1].trimEnd(), size - 5) + '…';
      while (preview.length < budget) preview.push('');
      const metadata = wrap(`Latest good recap · ${good ? when(latest.published_at || latest.created_at, false) || 'date unavailable' : 'unavailable'}`, size - 4);
      return box([{text:`${selected ? '›' : ' '} ${multi ? 'Pane' : 'Tab ' + (tab.number ?? '')}${manual ? ' M' : ''}`,role:manual ? 'mauve' : 'overlay0'}, ...names.map(text=>({text})), ...wrap(stateName(pane), size - 4).map(text=>({text,role:stateColor(pane),bold:true})), ...metadata.map(text=>({text,role:'overlay1'})), ...preview.map(text=>({text,role:good?'text':'overlay0'})), ...warning.map(text=>({text,role:'yellow'}))], size, pane.agent?.status === 'blocked' ? 'red' : selected ? 'accent' : 'overlay1', selected);
    };
    const reading = tab => {
      const logical = []; let selectedLogical = 0; const add = (text, role='text', surface, md=false) => logical.push({text,role,surface,md});
      add(fullTitle(tab)); add('');
      for (const id of tab.paneIds) {
        const pane = model.panes[id]; if (!pane || journey.level === 'digest' && id !== journey.paneId) continue;
        if (id === journey.paneId && tab.paneIds.length > 1 && journey.level !== 'digest') selectedLogical = logical.length;
        if (tab.paneIds.length > 1) { add('─'.repeat(workspaceWidth - 4),'overlay1'); add(`${id === journey.paneId ? '› ' : ''}${paneTitle(pane)}`); }
        add(`${pane.agent?.recognized ? (pane.agent.displayName || pane.agent.kind || 'Agent') : 'Manual'} · ${stateName(pane)}`, stateColor(pane)); add('');
        if (journey.level === 'digest' && id === journey.paneId) {
          add('Session digest','mauve'); add(when(pane.digest?.generatedAt) || 'date unavailable','overlay0');
          if (pane.digest?.status === 'available') add(pane.digest.body,'text','active_row_bg',true); else add('Unavailable · no verified digest','text','active_row_bg');
        } else {
          const latest = pane.recap?.latest, attempt = pane.recap?.lastAttempt;
          add('Latest good recap','teal');
          if (latest?.status === 'published') { const date = when(latest.published_at || latest.created_at); add(`Published ${date || 'date unavailable'}`,'overlay0'); if (latest.summary) add(latest.summary,'text','active_row_bg',true); else add('Unavailable','text','active_row_bg'); }
          else add('Unavailable · no published recap','overlay0');
          if (attempt && attempt.record_id !== latest?.record_id) { add(''); add(`Newer attempt ${attempt.status}`,'yellow'); add(when(attempt.created_at || attempt.published_at) || 'date unavailable','overlay0'); add(attempt.failure?.message || '', 'yellow','active_row_bg'); }
          add(''); add('Supplied prompt','teal'); add(pane.prompt?.text || 'Unavailable · no supplied prompt','text','active_row_bg'); add('');
          add('▸ Session digest · d to read','mauve'); add(when(pane.digest?.generatedAt) || 'unavailable','overlay0');
        }
        add('');
      }
      const rows = []; positions = [{line:-2,cell:0},{line:-1,cell:0}];
      let line = 0; selectedLine = 0;
      for (const [index,item] of logical.entries()) { if (index === selectedLogical && selectedLogical > 2) selectedLine = positions.length; const inner = workspaceWidth - 4;
      for (const source of item.md ? markdownLines(clean(item.text)) : clean(item.text).split(/\r?\n/)) {
        let cell = 0;
        const wrapped = !item.md ? wrap(source, inner).map(text => ({...item,text}))
          : source.skip ? [] : (source.rule ? [[{text:'─'.repeat(inner),role:'overlay1'}]] : wrapSpans(source.prefix, source.spans, inner)).map(spans => ({...item,spans,text:spans.map(s=>s.text).join('')}));
        for (const row of wrapped) { rows.push(row); positions.push({line,cell}); cell += cellWidth(row.text); }
        line++;
      } }
      positions.push({line,cell:0},{line:line+1,cell:0});
      return box(rows, workspaceWidth, model.panes[journey.paneId]?.agent?.status === 'blocked' ? 'yellow' : 'accent', true, 'panel_bg');
    };
    lines.push(style(pad(compact(title(workspace),workspaceWidth),workspaceWidth),'mauve'));
    const attention = blocked(model, workspace.tabIds.flatMap(id=>model.tabs[id]?.paneIds ?? []));
    lines.push(style(pad(`${workspace.tabIds.length} tabs · ${attention} needs input`,workspaceWidth),attention ? 'yellow':'overlay0'), '');
    let pending=[];
    const flush = () => { if (!pending.length) return; let cards=pending.map(({tab,pane})=>card(tab,pane,cellSize)); const height=Math.max(...cards.map(c=>c.length)); cards=cards.map((c,i)=>c.length<height ? card(pending[i].tab,pending[i].pane,cellSize,height-c.length) : c); cards.forEach((c,i)=>{ while(c.length<height)c.splice(c.length-2,0,c[c.length-2]); rectangles.push({paneId:pending[i].pane.id,x:i*(cellSize+2),y:lines.length,width:cellSize,height}); }); if(pending.some(({pane})=>pane.id===journey?.paneId)) anchor=lines.length;
      for(let y=0;y<cards[0].length;y++) lines.push(cards.map(card=>card[y]).join('  ')); lines.push('');pending=[]; };
    for(const tabId of workspace.tabIds) {
      const tab=model.tabs[tabId], ids=tab.paneIds.filter(id=>model.panes[id]); const expanded=journey?.level !== 'overview' && journey?.tabId===tabId;
      if(expanded || ids.length>1) { flush(); if(ids.includes(journey?.paneId)) anchor=lines.length;
        if(expanded) { lines.push(...reading(tab)); end=lines.length; }
        else { lines.push(style(pad(compact(`Tab ${tab.number ?? ''} · ${fullTitle(tab)} · ${ids.length} panes`,workspaceWidth),workspaceWidth),'mauve')); for(const id of ids) { if(id===journey?.paneId) anchor=lines.length; const tile=card(tab,model.panes[id],workspaceWidth); rectangles.push({paneId:id,x:0,y:lines.length,width:workspaceWidth,height:tile.length}); lines.push(...tile); } }
        lines.push('');
      } else if(ids.length) { pending.push({tab,pane:model.panes[ids[0]]}); if(pending.length===2) flush(); }
    }
    flush(); return {lines,anchor,end,positions,selectedLine,rectangles,selected:workspaceId===journey?.workspaceId};
  });
  const body=[],rectangles=[];let anchor=0,end=null,positions=[],selectedLine=0;
  for(let start=0;start<chunks.length;start+=columns) { const row=chunks.slice(start,start+columns),offset=body.length,selected=row.find(chunk=>chunk.selected);
    row.forEach((chunk,x)=>rectangles.push(...chunk.rectangles.map(r=>({...r,x:r.x+x*(workspaceWidth+3),y:r.y+offset}))));
    if(selected) { anchor=offset+selected.anchor;end=selected.end===null ? null : offset+selected.end;positions=selected.positions;selectedLine=selected.selectedLine; }
    for(let y=0;y<Math.max(...row.map(chunk=>chunk.lines.length));y++) body.push(row.map(chunk=>pad(chunk.lines[y]||'',workspaceWidth)).join('   ')); body.push('');
  }
  return {body:body.length ? body:['No native panes available.'],anchor,end,positions,selectedLine,rectangles};
}
export function mapFrame(state,width=100,height=24,now=Date.now()) {
  width=Math.max(1,width);height=Math.max(3,height);
  const {body,anchor,end,positions,selectedLine,rectangles}=mapLines(state,width,now),journey=state.journey;
  const footers=width<cellWidth('arrows/hjkl select · [/] pane · Enter details · d digest · f focus · n blocked · r refresh · Esc/q') && height>=6 ? ['arrows/hjkl select · [/] pane','Enter details · d digest · f focus','n blocked · r refresh · Esc/q'].map(line=>compact(line,width)) : [compact('arrows/hjkl select · [/] pane · Enter details · d digest · f focus · n blocked · r refresh · Esc/q',width)];
  const panes=Object.values(state.model.panes),count=status=>panes.filter(p=>p.agent?.recognized && p.agent.status===status).length;
  const summary=`!${count('blocked')} W${count('working')} R${count('idle')} · ${state.model.workspaceOrder.length}ws ${Object.keys(state.model.tabs).length}t`;
  const headers=['Herdr Overview',summary];
  const capacity=Math.max(0,height-headers.length-footers.length-(state.notice ? 1:0)),max=Math.max(0,body.length-capacity);
  let relative=Math.max(0,journey?.detailScroll||0);
  if(end!==null && !journey?.readingPosition && !relative) relative=selectedLine;
  // Serialized source-line/cell positions survive layout reflow; row offsets do not.
  if(end!==null && journey?.readingPosition) { const p=journey.readingPosition; const match=positions.findLastIndex(x=>x.line<p.line || x.line===p.line && x.cell<=p.cell); relative=Math.max(0,match)+(journey.scrollDelta||0); }
  const limit=end===null ? max : Math.max(0,end-anchor-capacity);
  relative=Math.max(0,Math.min(limit,relative));
  let offset=end===null ? Math.min(max,Math.max(0,journey?.overviewScroll || 0)) : Math.min(max,anchor+relative);
  if(end===null && journey?.ensureVisible !== false) { const r=rectangles.find(r=>r.paneId===journey?.paneId); if(r) { if(r.y<offset)offset=r.y; else if(r.y+r.height>offset+capacity)offset=Math.min(r.y, r.y+r.height-capacity); } offset=Math.max(0,Math.min(max,offset)); }
  if(journey) { if(end===null) {journey.overviewScroll=offset; journey.ensureVisible=false;} }
  if(journey) { journey.detailScroll=relative;journey.readingPosition=end===null ? null : journey.readingPosition && !journey.scrollDelta ? journey.readingPosition : positions[relative];journey.scrollDelta=0; }
  const palette=state.theme?.palette;
  const style=(text,role)=>`${paint(palette?.[role])}${paint(palette?.panel_bg,true)}${pad(compact(text,width),width)}\x1b[0m`;
  const visible=body.slice(offset,offset+capacity);while(visible.length<capacity)visible.push(style('','text'));
  const text = [style(headers[0],'accent'), paint(palette?.panel_bg,true) + [[`!${count('blocked')}`,count('blocked')?'yellow':'overlay0'],[` W${count('working')}`,'green'],[` R${count('idle')}`,'blue'],[` · ${state.model.workspaceOrder.length}ws ${Object.keys(state.model.tabs).length}t`,'subtext0']].map(([text,role])=>paint(palette?.[role])+text).join('') + ' '.repeat(Math.max(0,width-cellWidth(summary))) + '\x1b[0m',...visible,...(state.notice?[style(state.notice,'yellow')]:[]),...footers.map(line=>style(line,'overlay0'))].join('\n');
  return {text,rectangles,viewport:{x:0,y:headers.length,width,height:capacity,offset,max}};
}
export function renderMap(...args) { return mapFrame(...args).text; }
