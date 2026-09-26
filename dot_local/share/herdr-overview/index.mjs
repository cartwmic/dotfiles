#!/usr/bin/env node
import { reconcileOverview } from "./src/coordinator.mjs";
import { runOverviewPane } from "./src/pane.mjs";
import { displayNameResetFromContext } from "./src/display-name-policy.mjs";
import { runDeadlineWakeup } from "./src/deadline-wakeup.mjs";

const entrypoint = process.argv[2];
try {
  if (entrypoint === "startup" || entrypoint === "reconcile") {
    await reconcileOverview({
      openPane: true,
      coordinatorWake: true,
      resumeDeadlines: entrypoint === "startup",
    });
  } else if (entrypoint === "deadline-wakeup") {
    const [workspaceId, deadline, stateDir, socketPath] = process.argv.slice(3);
    if (!workspaceId || !deadline || !stateDir || !socketPath) {
      throw new Error("usage: node index.mjs deadline-wakeup <workspace-id> <deadline> <state-dir> <socket-path>");
    }
    await runDeadlineWakeup({ workspaceId, deadline, stateDir, socketPath });
  } else if (entrypoint === "event") {
    let event = null;
    try { event = JSON.parse(process.env.HERDR_PLUGIN_EVENT_JSON || "null"); } catch { /* A malformed hook payload still gets a safe snapshot refresh. */ }
    const eventName = String(event?.event ?? event?.type ?? "").replace(/^([a-z]+)_/, "$1.");
    await reconcileOverview({ openPane: eventName === "workspace.created", event });
  } else if (entrypoint === "auto-name-pane" || entrypoint === "auto-name-tab") {
    let context = {};
    try { context = JSON.parse(process.env.HERDR_PLUGIN_CONTEXT_JSON || "{}"); }
    catch { throw new Error("invalid HERDR_PLUGIN_CONTEXT_JSON for automatic naming action"); }
    const kind = entrypoint === "auto-name-pane" ? "pane" : "tab";
    await reconcileOverview({
      openPane: false,
      resetName: displayNameResetFromContext(context, kind),
    });
  } else if (entrypoint === "overview") {
    await runOverviewPane();
  } else {
    throw new Error("usage: node index.mjs <startup|reconcile|deadline-wakeup|event|auto-name-pane|auto-name-tab|overview>");
  }
} catch (error) {
  process.stderr.write(`herdr-overview: ${error.stack || error.message}\n`);
  process.exitCode = 1;
}
