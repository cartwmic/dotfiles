import { readFileSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// The session-recap CLI owns the presentation zone (time_zone in its config,
// config.local.toml wins). Records stay UTC; only the display is converted.
export function recapTimeZone(env = process.env) {
  const dir = path.join(env.XDG_CONFIG_HOME || path.join(env.HOME || os.homedir(), '.config'), 'session-recap');
  let zone = 'local';
  for (const name of ['config.toml', 'config.local.toml']) {
    try { const m = readFileSync(path.join(dir, name), 'utf8').match(/^\s*time_zone\s*=\s*"([^"]*)"/m); if (m) zone = m[1]; } catch {}
  }
  return zone;
}

// Same shape as Pi recap: "2026-10-03 06:19:35 GMT−7 [America/Los_Angeles]".
// Unparseable timestamps or zones are shown unchanged rather than guessed.
// label=false drops the [zone] suffix for narrow cards; the offset stays.
export function displayTime(timestamp, zone = 'local', label = true) {
  const date = new Date(timestamp ?? '');
  if (!timestamp || Number.isNaN(date.getTime()) || !/(Z|[+-]\d\d:?\d\d)$/i.test(timestamp)) return timestamp;
  try {
    const f = new Intl.DateTimeFormat('sv-SE', { ...(zone === 'local' ? {} : { timeZone: zone }), year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23', timeZoneName: 'shortOffset' });
    return label ? `${f.format(date)} [${zone === 'local' ? f.resolvedOptions().timeZone : zone}]` : f.format(date);
  } catch { return timestamp; }
}
