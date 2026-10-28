// Store port on the filesystem: $VIZ_STATE_DIR/<id>/ per render, built in a
// .staging-* directory and renamed into place; actions.jsonl gets one line per call.
import {
  appendFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, renameSync, rmSync, writeFileSync,
} from 'node:fs';
import { join } from 'node:path';

const ACTIONS_FILE = 'actions.jsonl';

export function createFsStore(root) {
  return {
    root,

    isTaken(id) { return existsSync(join(root, id)); },

    stage(files) {
      mkdirSync(root, { recursive: true });
      const dir = mkdtempSync(join(root, '.staging-'));
      for (const [name, data] of Object.entries(files)) writeFileSync(join(dir, name), data);
      return { dir, path: (name) => join(dir, name) };
    },

    add(staging, name, data) { writeFileSync(join(staging.dir, name), data); },

    finalPaths(id, names) { return Object.fromEntries(names.map((n) => [n, join(root, id, n)])); },

    commit(staging, id) { renameSync(staging.dir, join(root, id)); },

    discard(staging) { rmSync(staging.dir, { recursive: true, force: true }); },

    readRenders() {
      let entries = [];
      try { entries = readdirSync(root, { withFileTypes: true }); } catch { return []; }
      const renders = [];
      for (const e of entries) {
        if (!e.isDirectory() || e.name.startsWith('.')) continue;
        try { renders.push(JSON.parse(readFileSync(join(root, e.name, 'meta.json'), 'utf8'))); } catch { /* not a render */ }
      }
      return renders;
    },

    readRender(id) {
      try { return JSON.parse(readFileSync(join(root, id, 'meta.json'), 'utf8')); } catch { return null; }
    },

    readFile(id, name) { return readFileSync(join(root, id, name)); },

    appendAction(record) {
      mkdirSync(root, { recursive: true });
      appendFileSync(join(root, ACTIONS_FILE), JSON.stringify(record) + '\n');
    },
  };
}
