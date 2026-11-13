// Files and the action log, both under the user's state directory.
import { appendFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';

/** stateDir is ${XDG_STATE_HOME:-~/.local/state}/shx. */
export function createFsStore(stateDir) {
  return {
    files: {
      // An --out path is used as given (relative to the current directory); without one the picture goes under the state dir.
      async save({ path, name }, bytes) {
        const target = path ? resolve(path) : join(stateDir, 'images', name);
        mkdirSync(dirname(target), { recursive: true });
        writeFileSync(target, bytes);
        return target;
      },
    },
    log: {
      async append(record) {
        mkdirSync(stateDir, { recursive: true });
        appendFileSync(join(stateDir, 'note-image.log'), JSON.stringify(record) + '\n');
      },
    },
  };
}
