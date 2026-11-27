// shx-waiting entry: wires the real adapters into the core and prints the waiting threads. Contract and layout: README.md.
// Exit 1 means "something waits", so no failure may end in 1: every module is loaded inside the try, and an uncaught
// error ends in 3, never in Node's own 1.
const die = (e) => {
  process.stderr.write(`[shx-waiting] ERROR: unexpected failure: ${e && e.stack ? e.stack : e}\n`);
  process.exit(3);
};
process.on('uncaughtException', die);
process.on('unhandledRejection', die);

try {
  const { randomBytes } = await import('node:crypto');
  const { homedir } = await import('node:os');
  const { join } = await import('node:path');
  const { api } = await import('./adapters/shartifacts_http.mjs');
  const { createFsStore } = await import('./adapters/fs_store.mjs');
  const { runWaiting } = await import('./core/waiting.mjs');

  const env = process.env;
  // The server the skill documents; SHARTIFACTS_URL or a URL argument overrides it.
  const DEFAULT_BASE = 'https://shartifacts.internal.cartwmic.com';
  const store = createFsStore(join(env.XDG_STATE_HOME || join(homedir(), '.local', 'state'), 'shx'), 'waiting.log');
  const { stdout, stderr, exitCode } = await runWaiting(process.argv.slice(2), {
    api,
    files: store.files,
    log: store.log,
    clock: { now: () => Date.now() },
    random: { hex: () => randomBytes(3).toString('hex') },
    warn: (line) => process.stderr.write(line + '\n'),
  }, { base: env.SHARTIFACTS_URL || DEFAULT_BASE });
  if (stdout) process.stdout.write(stdout + '\n');
  if (stderr) process.stderr.write(stderr + '\n');
  process.exitCode = exitCode;
} catch (e) {
  die(e);
}
