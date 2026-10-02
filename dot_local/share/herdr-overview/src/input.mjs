// Retain partial CSI packets; never reinterpret their bytes as viewer commands.
export class InputDecoder {
  pending = '';
  push(buffer) {
    this.pending += buffer.toString('utf8');
    const events = [];
    while (this.pending) {
      if (this.pending[0] !== '\x1b') {
        const c = this.pending[0]; this.pending = this.pending.slice(1);
        events.push(c === '\r' || c === '\n' ? 'enter' : c === '\x03' ? 'q' : c); continue;
      }
      if (this.pending.length === 1) break;
      if (this.pending[1] !== '[') { this.pending = ''; break; }
      const packet = this.pending.startsWith('\x1b[<') ? this.pending.match(/^\x1b\[<[^Mm\x1b]*[Mm]/) : this.pending.match(/^\x1b\[[0-?]*[ -/]*[@-~]/);
      if (!packet) {
        const restart = this.pending.indexOf('\x1b', 1);
        if (restart > 0) { this.pending = this.pending.slice(restart); continue; }
        if (this.pending.length > 128) this.pending = '';
        break;
      }
      this.pending = this.pending.slice(packet[0].length);
      const arrow = packet[0].match(/^\x1b\[([ABCD])$/);
      if (arrow) events.push({A:'k',B:'j',C:'l',D:'h'}[arrow[1]]);
      const mouse = packet[0].match(/^\x1b\[<(\d+);(\d+);(\d+)([Mm])$/);
      if (mouse) {
        const button = Number(mouse[1]);
        if (mouse[4] === 'M' && (button === 0 || button === 64 || button === 65)) events.push({type:button === 0 ? 'click':'wheel', x:Number(mouse[2])-1,y:Number(mouse[3])-1,delta:button === 64 ? -3:3});
      }
    }
    return events;
  }
  flush() { const escape = this.pending === '\x1b'; this.pending = ''; return escape ? ['escape'] : []; }
}
export function hitPane(frame, x, y) {
  const v = frame?.viewport;
  if (!v || x < 0 || x >= v.width || y < v.y || y >= v.y+v.height) return null;
  return frame.rectangles.find(r => x >= r.x+2 && x < r.x+r.width-2 && y-v.y+v.offset >= r.y+2 && y-v.y+v.offset < r.y+r.height-2)?.paneId ?? null;
}
