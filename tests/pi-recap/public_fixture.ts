// Scripted external model/tool, loaded through Pi's public provider API.
import { createAssistantMessageEventStream } from '@earendil-works/pi-ai';
import { Type } from '@sinclair/typebox';
import { appendFileSync, existsSync, readFileSync, writeFileSync } from 'node:fs';
const log = (event: any) => appendFileSync(process.env.RECAP_PROOF_LOG!, JSON.stringify({ ...event, time: Date.now() }) + '\n');
const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
export default function (pi: any) {
  // Private keyboard launcher reaches the actual public slash-command handler
  // without consuming the owner's unsent main-editor draft.
  if (process.env.RECAP_PROOF_UX === '1') {
    pi.registerShortcut('alt+g', { description: 'Proof: open public recap view', handler: () => { pi.sendUserMessage('/recap view', { expandPromptTemplates: true }); } });
    pi.registerShortcut('alt+h', { description: 'Proof: open public recap help', handler: () => { pi.sendUserMessage('/recap help', { expandPromptTemplates: true }); } });
  }
  pi.registerProvider('recap-proof', {
    api: 'openai-completions', baseUrl: 'http://unused.invalid', apiKey: 'dummy',
    models: ['main', ...(process.env.RECAP_PROOF_UX === '1' ? ['main-next'] : []), 'recap', 'unusable'].map(id => ({ id, name: id, reasoning: false, input: ['text'], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: id === 'unusable' ? 1024 : id === 'recap' ? Number(process.env.RECAP_PROOF_CONTEXT ?? 100000) : 100000, maxTokens: id === 'recap' ? Number(process.env.RECAP_PROOF_MAX_OUTPUT ?? 4096) : 4096 })),
    streamSimple(model: any, context: any, options: any) {
      const stream = createAssistantMessageEventStream();
      void (async () => {
        const message: any = { role: 'assistant', api: model.api, provider: model.provider, model: model.id, timestamp: Date.now(), content: [], stopReason: 'stop', usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } } };
        const prompt = context.messages.filter((m: any) => m.role === 'user').at(-1)?.content.map((c: any) => c.text ?? '').join('\n') ?? '';
        if (model.id === 'recap' || (process.env.RECAP_PROOF_UX === '1' && process.argv.some(arg => arg.endsWith('/backend.mjs')))) {
          const counter = process.env.RECAP_PROOF_COUNTER!;
          const number = existsSync(counter) ? Number(readFileSync(counter, 'utf8')) + 1 : 1;
          writeFileSync(counter, String(number));
          const reduction = prompt.startsWith('Reduce this complete chunk,');
          log({ event: 'call', model: model.id, number, reduction, prompt, maxTokens: options?.maxTokens });
          if (number === 1 || process.env.RECAP_PROOF_UX === '1') while (existsSync(process.env.RECAP_PROOF_GATE!)) await delay(50);
          // Each invocation is independent; deadlines must cover the whole reduction,
          // not reset for each of these successful, individually short calls.
          if (existsSync(process.env.RECAP_PROOF_SLOW!) && !reduction) await delay(3000);
          const facts = [...new Set(prompt.match(/FACT_[a-z_]+=[a-z0-9_-]+/g) ?? [])];
          let text: string;
          if (reduction) text = facts.join(' ') || 'No additional outcome in this chunk.';
          else {
            const topic = facts.filter(f => f.startsWith('FACT_topic=')).at(-1)?.split('=')[1] ?? 'unknown';
            const result = facts.find(f => f.startsWith(`FACT_result=${topic}-`))?.split('=')[1] ?? 'unconfirmed';
            const pending = facts.find(f => f.startsWith(`FACT_pending=${topic}-`))?.split('=')[1] ?? 'unspecified';
            const next = facts.find(f => f.startsWith(`FACT_next=${topic}-`))?.split('=')[1] ?? 'inspect';
            const earlier = facts.filter(f => f.startsWith('FACT_topic=') && f !== `FACT_topic=${topic}`).map(f => {
              const name = f.split('=')[1];
              return `Earlier captured ${name}: ${facts.find(v => v.startsWith(`FACT_result=${name}-`))?.split('=')[1]}; unfinished ${facts.find(v => v.startsWith(`FACT_pending=${name}-`))?.split('=')[1]}; next ${facts.find(v => v.startsWith(`FACT_next=${name}-`))?.split('=')[1]}. `;
            }).join('');
            text = earlier + `Observed ${topic}: the tool confirmed ${result}. Unfinished work: ${pending}. Present state: evidence collected, follow-up pending. Next: ${next}.`;
          }
          if (process.env.RECAP_PROOF_UX === '1' && !reduction) text = '観察 \x1b[36m' + text + '\x1b[0m\n' + Array.from({ length: 36 }, (_, i) => `詳しい${i + 1}: ${facts.join(' ')}; evidence preserved for review.`).join('\n');
          log({ event: 'response', model: model.id, number, reduction, text });
          message.content = [{ type: 'text', text }];
          const fault = process.env.HOME + '/unfinished';
          if (existsSync(fault) && readFileSync(fault, 'utf8') === (reduction ? 'reduction' : 'final')) message.stopReason = 'length';
          if (existsSync(process.env.HOME + '/context-rejection')) { message.stopReason = 'error'; message.errorMessage = 'maximum context length exceeded PRIVATE_CONTEXT_SENTINEL'; }
          if (existsSync(process.env.HOME + '/private-error')) {
            console.error('PRIVATE_STDERR_SENTINEL auth/path/private');
            message.stopReason = 'error'; message.errorMessage = 'PRIVATE_PROVIDER_SENTINEL auth/path/private';
          }
        } else {
          const topic = /orchard|harbor|older|newer/.exec(prompt)?.[0] ?? 'unknown';
          log({ event: 'call', model: model.id, topic });
          if (process.env.RECAP_PROOF_COMPACTION && (prompt.includes('Create a structured context checkpoint summary') || prompt.includes('Update the existing structured summary') || prompt.includes('earlier context from an ongoing conversation'))) {
            log({ event: 'native-summary', prompt });
            message.content = [{ type: 'text', text: 'Native checkpoint: historical investigation summarized; original tool evidence intentionally omitted.' }];
          } else if (prompt === 'Initialize proof') message.content = [{ type: 'text', text: 'Ready to observe work.' }];
          else if (context.messages.at(-1)?.role === 'toolResult') {
            message.content = [{ type: 'text', text: `Investigation of ${topic} collected evidence; follow-up is still unfinished.` }];
            if (process.env.RECAP_PROOF_COMPACTION === 'automatic' && topic === 'harbor') { message.usage.input = 99000; message.usage.totalTokens = 99001; }
          }
          else { message.stopReason = 'toolUse'; message.content = [{ type: 'toolCall', id: 'evidence-' + Date.now(), name: 'proof_evidence', arguments: { topic } }]; }
        }
        stream.push({ type: 'start', partial: message });
        stream.push({ type: 'done', reason: message.stopReason, message });
        stream.end();
      })();
      return stream;
    },
  });
  pi.registerVirtualModel({ provider: 'recap-router', id: 'auto', name: 'Recap route', contextWindow: 100000, maxTokens: 4096, async route(request: any, ctx: any) {
    const model = ctx.modelRegistry.find('recap-proof', 'recap');
    const preflight = ['--budget', '--preflight'].includes(process.argv.at(-1)!);
    log({ event: 'route-start', preflight, pid: process.pid });
    if (preflight && existsSync(process.env.HOME + '/budget-delay')) await delay(Number(readFileSync(process.env.HOME + '/budget-delay', 'utf8')));
    if (existsSync(process.env.HOME + '/budget-gate')) {
      log({ event: 'budget-wait', pid: process.pid });
      while (existsSync(process.env.HOME + '/budget-gate')) await delay(50);
    }
    log({ event: 'budget-resolved', pid: process.pid });
    if (existsSync(process.env.HOME + '/budget-failure')) throw new Error('Scripted route metadata unavailable');
    return { model: !preflight && existsSync(process.env.HOME + '/smaller-route') ? ctx.modelRegistry.find('recap-proof', 'unusable') : model, thinkingLevel: 'off' };
  } });
  pi.registerTool({ name: 'proof_evidence', label: 'Evidence', description: 'Scripted evidence collection', parameters: Type.Object({ topic: Type.String() }), async execute(_id: string, args: any, signal: AbortSignal) {
    const topic = args.topic;
    const padding = (process.env.RECAP_PROOF_OVERSIZED === '1' || existsSync(process.env.HOME + '/oversized')) ? (process.env.RECAP_PROOF_CONTEXT ? ' j'.repeat(4500) : 'Observed detail without additional outcome. '.repeat(65)) : '';
    const text = `FACT_topic=${topic} FACT_result=${topic}-checks-passed ${padding}FACT_pending=${topic}-deployment-unfinished ${padding}FACT_next=${topic}-review-before-deploy`;
    log({ event: 'tool-result', topic, text, toolCallId: _id });
    while (existsSync(process.env.HOME + '/tool-gate')) {
      if (signal?.aborted) { log({ event: 'tool-aborted', topic, toolCallId: _id }); break; }
      await delay(50);
    }
    log({ event: 'tool-completed', topic, toolCallId: _id, aborted: !!signal?.aborted });
    return { content: [{ type: 'text', text }], details: undefined };
  } });
  pi.on('tool_execution_end', (event: any) => log({ event: 'tool-end', toolCallId: event.toolCallId, isError: event.isError }));
  pi.on('agent_settled', () => log({ event: 'settled' }));
  if (process.env.RECAP_PROOF_COMPACTION) {
    pi.on('session_before_compact', (event: any, ctx: any) => log({ event: 'before-compact', reason: event.reason, sessionId: ctx.sessionManager.getSessionId(), branch: ctx.sessionManager.getBranch() }));
    pi.on('session_compact', (event: any, ctx: any) => log({ event: 'compacted', reason: event.reason, fromExtension: event.fromExtension, projection: ctx.sessionManager.buildSessionProjection().messages }));
    pi.on('session_compact_failed', (event: any) => log({ event: 'compact-failed', reason: event.reason, error: event.errorMessage }));
  }
}
