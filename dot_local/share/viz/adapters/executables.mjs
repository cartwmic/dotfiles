// Finding executables on disk and on PATH.
import { accessSync, constants, statSync } from 'node:fs';
import { delimiter, join } from 'node:path';

export function isExecutable(p) {
  try { accessSync(p, constants.X_OK); return statSync(p).isFile(); } catch { return false; }
}

export function which(name, path = process.env.PATH || '') {
  for (const dir of path.split(delimiter)) {
    if (dir && isExecutable(join(dir, name))) return join(dir, name);
  }
  return null;
}
