import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { builtinProviders } from "@earendil-works/pi-ai/providers/all";

// Registers a local Winnow-12B server as the Pi classifier model winnow/winnow-12b.
// Winnow speaks TypeSafe's native System One protocol, so this reuses Pi's built-in
// TypeSafe classifier and changes only the address. Setup: README.md in this directory.
const BASE_URL = "http://127.0.0.1:8091";
const README = "~/.pi/agent/extensions/winnow-local/README.md";
const START =
  "cd ~/git/winnow-inference && python3 scripts/serve.py --profile apple-silicon --text-only --alias winnow-12b";
const HINT = `Is local Winnow running? Start it with: ${START}. First-time setup: ${README}`;

export default function (pi: ExtensionAPI) {
  const typesafe = builtinProviders().find((p) => p.id === "typesafe");
  if (!typesafe?.classify) return; // Pi changed its built-in TypeSafe provider; see README troubleshooting.
  const classify = typesafe.classify.bind(typesafe);

  pi.registerProvider("winnow", {
    baseUrl: `${BASE_URL}/v1`,
    apiKey: "local", // Winnow ignores it; Pi needs a value to mark the model available.
    models: [
      {
        type: "classifier",
        id: "winnow-12b", // Must match the server's --alias; Winnow rejects other names.
        name: "Winnow 12B (local)",
        api: "typesafe-system-one",
        input: ["text"],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 65536,
      },
    ],
    classifiers: {
      "typesafe-system-one": {
        classify: async (model, context, options) => {
          const result = await classify(model, context, options);
          if (result.stopReason === "error") result.errorMessage = `${result.errorMessage} — ${HINT}`;
          return result;
        },
      },
    },
  });

  pi.registerCommand("winnow", {
    description: "Check the local Winnow System One server and show how to start it",
    handler: async (_args, ctx) => {
      let up = false;
      try {
        up = (await fetch(`${BASE_URL}/health`, { signal: AbortSignal.timeout(2000) })).ok;
      } catch {}
      if (up) ctx.ui.notify(`Winnow is running at ${BASE_URL} (classifier winnow/winnow-12b).`, "info");
      else ctx.ui.notify(`Winnow is not reachable at ${BASE_URL}. ${HINT}`, "warning");
    },
  });
}
