// Files and the action log, both under the user's state directory.
import { appendFileSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { ShxError } from '../core/domain.mjs';

/** stateDir is ${XDG_STATE_HOME:-~/.local/state}/shx; `logName` is the action log's file name inside it. */
export function createFsStore(stateDir, logName = 'note-image.log') {
  return {
    files: {
      // An --out path is used as given (relative to the current directory); without one the picture goes under the state dir.
      async save({ path, name }, bytes) {
        const target = path ? resolve(path) : join(stateDir, 'images', name);
        mkdirSync(dirname(target), { recursive: true });
        writeFileSync(target, bytes);
        return target;
      },
      async read(path) {
        try {
          return readFileSync(resolve(path), 'utf8');
        } catch (e) {
          throw new ShxError('bad_input', `cannot read ${path}: ${e.message}`);
        }
      },
    },
    log: {
      async append(record) {
        mkdirSync(stateDir, { recursive: true });
        appendFileSync(join(stateDir, logName), JSON.stringify(record) + '\n');
      },
    },
  };
}
