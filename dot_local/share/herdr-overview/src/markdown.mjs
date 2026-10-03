// Small dependency-free markdown subset for recap/digest reading. Returns one
// entry per source line so the reader keeps source-line scroll positions.
// Span: {text, role?, bold?, italic?}. Entry: {prefix, spans} | {rule:true} | {skip:true}.
const INLINE = /(`+)([^`]|[^`][\s\S]*?[^`])\1(?!`)|\*\*(?=\S)([\s\S]*?\S)\*\*|__(?=\S)([\s\S]*?\S)__(?![\p{L}\p{N}])|~~(?=\S)([\s\S]*?\S)~~|(?<![\p{L}\p{N}*])\*(?=[^\s*])([\s\S]*?[^\s*])\*(?![\p{L}\p{N}*])|(?<![\p{L}\p{N}_])_(?=[^\s_])([\s\S]*?[^\s_])_(?![\p{L}\p{N}_])|\[([^\]]+)\]\(([^)\s]+)\)/gu;

export function inline(text, base = {}) {
  const out = [], push = (value, extra = {}) => { if (value) out.push({ ...base, ...extra, text: value }); };
  let last = 0;
  for (const m of text.matchAll(INLINE)) {
    push(text.slice(last, m.index));
    if (m[1]) push(m[2].trim() || m[2], { role: 'peach' });
    else if (m[3] ?? m[4]) out.push(...inline(m[3] ?? m[4], { ...base, bold: true }));
    else if (m[5]) push(m[5]);
    else if (m[6] ?? m[7]) out.push(...inline(m[6] ?? m[7], { ...base, italic: true }));
    else out.push(...inline(m[8], { ...base, role: 'blue' }));
    last = m.index + m[0].length;
  }
  push(text.slice(last));
  return out;
}

export function markdownLines(text) {
  let fence = null;
  return String(text ?? '').split(/\r?\n/).map(line => {
    const open = line.match(/^\s*(`{3,}|~{3,})/);
    if (fence) { if (open && open[1][0] === fence[0] && open[1].length >= fence.length) { fence = null; return { skip: true }; } return { prefix: [{ text: '  ' }], spans: line ? [{ text: line, role: 'peach' }] : [] }; }
    if (open) { fence = open[1]; return { skip: true }; }
    let m;
    if (/^\s{0,3}([-*_])(\s*\1){2,}\s*$/.test(line)) return { rule: true };
    if ((m = line.match(/^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$/))) return { prefix: [], spans: inline(m[1], { role: 'accent', bold: true }) };
    if ((m = line.match(/^\s{0,3}>\s?(.*)$/))) return { prefix: [{ text: '│ ', role: 'overlay1' }], spans: inline(m[1], { role: 'subtext0', italic: true }) };
    if ((m = line.match(/^(\s*)([-*+]|\d+[.)])\s+(.*)$/))) {
      const task = m[3].match(/^\[([ xX])\]\s+(.*)$/);
      const marker = /\d/.test(m[2]) ? m[2] : '•';
      return { prefix: [{ text: m[1] }, { text: marker + ' ', role: 'teal' }, ...(task ? [{ text: task[1] === ' ' ? '☐ ' : '☑ ', role: 'teal' }] : [])], spans: inline(task ? task[2] : m[3]) };
    }
    const lead = line.match(/^\s*/)[0];
    return { prefix: lead ? [{ text: lead }] : [], spans: inline(line.slice(lead.length)) };
  });
}

// Glanceable previews stay plain text; drop markdown markers rather than show them.
export function plainMarkdown(text) {
  return markdownLines(text).filter(l => !l.skip).map(l => l.rule ? '—' : [...l.prefix, ...l.spans].map(s => s.text).join('')).join('\n');
}
