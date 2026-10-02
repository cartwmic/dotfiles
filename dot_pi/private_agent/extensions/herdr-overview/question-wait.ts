import type { ExtensionAPI, ExtensionContext } from '@earendil-works/pi-coding-agent';
import { exactTerminalForCaller, requestHerdr } from './helpers.ts';

const source = 'herdr:overview-question';
// The question package emits actual wait edges, not tool invocation edges.
export function registerQuestionWait(pi: ExtensionAPI): void {
  let session: string | undefined, enabled = false, active = false, generation = 0;
  let sequence = Date.now() * 1000;
  let queue: Promise<void> = Promise.resolve();
  let terminal: string | undefined;
  const publish = (waiting: boolean) => {
    const token = generation, sessionId = session;
    const socket = process.env.HERDR_SOCKET_PATH, caller = process.env.HERDR_PANE_ID;
    if (!socket || !caller) return queue;
    queue = queue.then(async () => {
      const pane = await exactTerminalForCaller(socket, caller);
      if (token !== generation || sessionId !== session || !pane?.terminalId) return;
      if (terminal && terminal !== pane.terminalId) return;
      terminal = pane.terminalId;
      await requestHerdr(socket, 'pane.report_metadata', {
        pane_id: pane.paneId, source, agent: 'pi', applies_to_source: 'herdr:pi', seq: ++sequence,
        ...(waiting ? {state_labels: {blocked: 'Awaiting answer'}} : {clear_state_labels: true}),
      });
    }).catch(error => console.warn(`[herdr-overview] question label unavailable: ${error.message}`));
    return queue;
  };
  const transition = (waiting: boolean) => {
    if (waiting === active) return queue;
    active = waiting;
    generation++;
    pi.events.emit('herdr:blocked', {active: waiting, label: 'Awaiting answer'});
    return publish(waiting);
  };
  const start = async (_event: unknown, ctx: ExtensionContext) => {
    await transition(false);
    generation++;
    session = ctx.sessionManager.getSessionId();
    terminal = undefined;
    enabled = ctx.hasUI === true && (ctx.mode === 'tui' || ctx.mode === 'rpc') && process.env.HERDR_ENV === '1';
    if (enabled) await publish(false);
  };
  pi.on('session_start', start);
  pi.on('session_shutdown', async () => { await transition(false); enabled = false; generation++; session = undefined; });
  pi.events.on('rpiv:ask-user:blocked', data => {
    if (!enabled || typeof (data as {active?: unknown})?.active !== 'boolean') return;
    void transition((data as {active: boolean}).active);
  });
}
