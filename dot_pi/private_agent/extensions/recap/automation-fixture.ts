// Scripted external system for isolated PTY proof, never a live provider.
import { createAssistantMessageEventStream } from '@earendil-works/pi-ai';
import { Type } from '@sinclair/typebox';
import { appendFileSync, existsSync } from 'node:fs';
const log = (event: any) => appendFileSync(process.env.RECAP_PROOF_LOG!, JSON.stringify({ ...event, time: Date.now() }) + '\n');
const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
export default function (pi: any) {
  let retry = false;
  pi.registerProvider('recap-proof', {
    api: 'openai-completions', baseUrl: 'http://unused.invalid', apiKey: 'dummy',
    models: ['main', 'recap'].map(id => ({ id, name: id, reasoning: false, input: ['text'], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 100000, maxTokens: 4096 })),
    streamSimple(model: any, context: any, options: any) {
      const stream = createAssistantMessageEventStream();
      void (async () => {
        const message: any = { role: 'assistant', api: model.api, provider: model.provider, model: model.id, timestamp: Date.now(), content: [], stopReason: 'stop', usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } } };
        const user = context.messages.filter((m: any) => m.role === 'user').at(-1);
        const prompt = JSON.stringify(user?.content);
        log({ event: 'call', model: model.id, prompt });
        if (model.id === 'recap') {
          while (existsSync(process.env.RECAP_PROOF_GATE!)) await delay(50);
          message.content = [{ type: 'text', text: 'PROOF_RECAP public progress and next steps.' }];
        } else if (prompt.includes('retry-case') && !retry) { retry = true; message.stopReason = 'error'; message.errorMessage = '429 rate limit proof'; }
        else if (prompt.includes('error-case')) { message.stopReason = 'error'; message.errorMessage = 'Nonretryable proof failure'; }
        else if (prompt.includes('abort-case')) { message.stopReason = 'aborted'; message.errorMessage = 'Proof abort'; }
        else if (context.messages.at(-1)?.role === 'toolResult') message.content = [{ type: 'text', text: 'PROOF_FINAL tool completed.' }];
        else { message.stopReason = 'toolUse'; message.content = [{ type: 'toolCall', id: 'silent-' + Date.now(), name: 'proof_silent', arguments: { updates: prompt.includes('retry-case') } }]; }
        stream.push({ type: 'start', partial: message });
        if (['error', 'aborted'].includes(message.stopReason)) stream.push({ type: 'error', reason: message.stopReason, error: message });
        else stream.push({ type: 'done', reason: message.stopReason, message });
        stream.end();
      })();
      return stream;
    },
  });
  pi.registerTool({ name: 'proof_silent', label: 'Silent proof', description: 'Silent long operation', parameters: Type.Object({ updates: Type.Optional(Type.Boolean()) }), async execute(_id: string, args: any, _signal: any, update: any) {
    log({ event: 'tool-start' });
    for (let i = 0; i < 23; i++) { await delay(300); if (args.updates) { log({ event: 'tool-update' }); update({ content: [{ type: 'text', text: `Public progress ${i}` }], details: undefined }); } }
    log({ event: 'tool-end' });
    return { content: [{ type: 'text', text: 'PROOF_TOOL_RESULT' }], details: undefined };
  } });
  pi.on('agent_start', () => log({ event: 'agent-start' }));
  pi.on('agent_end', () => log({ event: 'agent-end' }));
  pi.on('agent_settled', () => log({ event: 'settled' }));
  pi.on('session_before_compact', (event: any) => ({ compaction: { summary: 'Proof compaction', firstKeptEntryId: event.preparation.firstKeptEntryId, tokensBefore: event.preparation.tokensBefore } }));
  pi.on('session_compact', () => log({ event: 'compact' }));
}
