import { pathToFileURL } from 'node:url';
import { realpathSync } from 'node:fs';

const isContextRejection = message => typeof message === 'string' && !/rate.?limit|too many requests|throttl/i.test(message) && /context[_ ]length[_ ]exceeded|maximum context length|(?:exceeds the |exceeded )context window|context window exceeded|too many tokens|prompt (?:is )?too long/i.test(message);

import { LimitFailure, budgets } from './budgets.mjs';
export { LimitFailure, budgets };

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
    if (!model) throw new LimitFailure('model_limits', 'Selected recap model unavailable');
    // Generic preflight supplies material only. Pi owns the captured background
    // and framing; resolve/estimate the same complete prompt used at generation.
    if (budgetOnly) input = selection.instructions + '\n\n' + (selection.budgetBackground ? 'Background only (not new activity):\n' + selection.budgetBackground + '\n\nNew material:\n' : '') + input;
    const messages = [{ role: 'user', content: [{ type: 'text', text: input }], timestamp: Date.now() }];
    const { thinkingLevel = 'off', ...options } = selection.options;
    // Resolve publicly once per request, then invoke that physical model. Display
    // metadata on a virtual selection is not authoritative for its routed limits.
    const route = model.api === 'pi-virtual' ? await modelRuntime.resolveModel(model, messages, { reason: 'direct', thinkingLevel }) : { model, thinkingLevel };
    const effective = budgets(route.model, selection, route.thinkingLevel, sdk.estimateTokens, input);
    if (budgetOnly) return effective;
    // A router may choose a smaller target for a reduced chunk than at preflight.
    // Refuse the actual call; never trim material or substitute another model.
    if (effective.estimatedInputTokens > effective.availableTokens) throw new LimitFailure('context_limit', 'Recap input exceeds routed model context estimate');
    // Match public virtual completeSimple's cross-provider auth isolation.
    const { apiKey, headers, env, ...nonAuthOptions } = options;
    const requestOptions = model.api === 'pi-virtual' && route.model.provider !== model.provider ? nonAuthOptions : options;
    let result;
    try {
      result = await modelRuntime.completeSimple(route.model, { systemPrompt: selection.instructions, messages }, { ...requestOptions, maxTokens: effective.maxTokens, reasoning: route.thinkingLevel });
    } catch (error) {
      if (isContextRejection(error?.message)) throw new LimitFailure('context_limit', 'Recap provider rejected context size');
      throw error;
    }
    if (result.stopReason !== 'stop') {
      // Classify known context rejections; never return the provider's text.
      if (result.stopReason === 'error' && isContextRejection(result.errorMessage)) throw new LimitFailure('context_limit', 'Recap provider rejected context size');
      throw new Error('Recap provider did not finish');
    }
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
      // model policy. Preserve the selected output options for actual routed calls.
      const effective = { ...selection, options: { ...selection.options, maxTokens: result.maxTokens } };
      process.stdout.write(JSON.stringify({ input_budget_bytes: result.inputBudget, command: [process.execPath, process.argv[1], sdkPath, agentDir, cwd, JSON.stringify(effective)] }));
    } else process.stdout.write(mode === '--budget' ? JSON.stringify(result) : result);
  } catch (error) {
    // Closed machine protocol only, never arbitrary provider stderr/auth/paths.
    if (error instanceof LimitFailure) process.stdout.write(`SESSION_RECAP_FAILURE:${error.reason}\n`);
    else process.stderr.write('Recap backend failed\n');
    process.exitCode = 1;
  }
}
