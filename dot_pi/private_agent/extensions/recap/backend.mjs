import { pathToFileURL } from 'node:url';
import { realpathSync } from 'node:fs';

/** One UTF-8 byte per token is deliberately conservative (no tokenizer dependency).
 * Leave room for system instructions, message/reduction framing, and the answer.
 * Reasoning adapters can add thinking to maxTokens: reserve their entire model
 * output ceiling when reasoning is enabled rather than assuming it is free.
 */
export function budgets(model, selection, thinkingLevel = 'off') {
  const context = model.contextWindow, limit = model.maxTokens;
  const requested = selection.options.maxTokens ?? 4096;
  const input = selection.inputBudget ?? 24000;
  if (![context, limit, requested, input].every(n => Number.isSafeInteger(n) && n > 0)) throw new Error('Recap model limits unavailable');
  const maxTokens = Math.min(requested, limit, Math.floor(context / 4));
  const outputReserve = thinkingLevel === 'off' ? maxTokens : limit;
  const inputBudget = Math.min(input, context - outputReserve - Buffer.byteLength(selection.instructions, 'utf8') - 1024);
  if (maxTokens < 1 || inputBudget < 256) throw new Error('Recap model budget unusable');
  return { inputBudget, maxTokens };
}

/** Independent direct provider request. No prompt(), binding, tools or session archive.
 * budgetOnly resolves whitelisted limits without a provider generation request.
 */
export async function generate(sdk, agentDir, cwd, selection, input, budgetOnly = false) {
  const modelRuntime = await sdk.ModelRuntime.create({ authPath: `${agentDir}/auth.json`, modelsPath: `${agentDir}/models.json` });
  const settingsManager = sdk.SettingsManager.create(cwd, agentDir);
  const resourceLoader = new sdk.DefaultResourceLoader({ cwd, agentDir, settingsManager });
  await resourceLoader.reload();
  const { session } = await sdk.createAgentSession({ cwd, agentDir, modelRuntime, settingsManager, resourceLoader, sessionManager: sdk.SessionManager.inMemory(cwd), tools: [], noTools: true });
  try {
    const model = modelRuntime.getModel(selection.model.provider, selection.model.id);
    if (!model) throw new Error('Selected recap model unavailable');
    const messages = [{ role: 'user', content: [{ type: 'text', text: input }], timestamp: Date.now() }];
    const { thinkingLevel = 'off', ...options } = selection.options;
    // Resolve publicly once per request, then invoke that physical model. Display
    // metadata on a virtual selection is not authoritative for its routed limits.
    const route = model.api === 'pi-virtual' ? await modelRuntime.resolveModel(model, messages, { reason: 'direct', thinkingLevel }) : { model, thinkingLevel };
    const effective = budgets(route.model, selection, route.thinkingLevel);
    if (budgetOnly) return effective;
    // A router may choose a smaller target for a reduced chunk than at preflight.
    // Refuse the actual call; never trim material or substitute another model.
    if (Buffer.byteLength(input, 'utf8') > effective.inputBudget) throw new Error('Recap input exceeds routed model budget');
    // Match public virtual completeSimple's cross-provider auth isolation.
    const { apiKey, headers, env, ...nonAuthOptions } = options;
    const requestOptions = model.api === 'pi-virtual' && route.model.provider !== model.provider ? nonAuthOptions : options;
    const result = await modelRuntime.completeSimple(route.model, { systemPrompt: selection.instructions, messages }, { ...requestOptions, maxTokens: effective.maxTokens, reasoning: route.thinkingLevel });
    if (result.stopReason !== 'stop') throw new Error('Recap provider did not finish');
    const text = result.content.filter(c => c.type === 'text').map(c => c.text).join('\n');
    if (!text.trim()) throw new Error('Recap provider returned no text');
    return text;
  } finally { session.dispose(); }
}
if (process.argv[1] && import.meta.url === pathToFileURL(realpathSync(process.argv[1])).href) {
  try {
    const [sdkPath, agentDir, cwd, config, mode] = process.argv.slice(2);
    const selection = JSON.parse(config);
    if (!selection.model?.provider || !selection.model?.id || typeof selection.instructions !== 'string' || !selection.options) throw new Error('Invalid selection');
    let input = '';
    for await (const chunk of process.stdin) input += chunk;
    const sdk = await import(pathToFileURL(sdkPath).href);
    const result = await generate(sdk, agentDir, cwd, selection, input, ['--budget', '--preflight'].includes(mode));
    if (mode === '--preflight') {
      // The generic supervisor treats argv as opaque; only this Pi helper owns
      // model policy. Keep the original user ceilings for actual routed calls.
      const effective = { ...selection, options: { ...selection.options, maxTokens: result.maxTokens } };
      process.stdout.write(JSON.stringify({ input_budget_bytes: result.inputBudget, command: [process.execPath, process.argv[1], sdkPath, agentDir, cwd, JSON.stringify(effective)] }));
    } else process.stdout.write(mode === '--budget' ? JSON.stringify(result) : result);
  } catch { process.stderr.write('Recap backend failed\n'); process.exitCode = 1; }
}
