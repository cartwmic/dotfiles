// Entry point (apply loop, onchange hash). Selects the payload for the installed Pi minor series; see ../pi-select.mjs.
// patch.pi-1.1.mjs + edits.json: exact Pi 1.1.0. patch.pi-1.2.mjs + edits.pi-1.2.json: exact Pi 1.2.0. patch.pi-1.3.mjs + edits.pi-1.3.json: exact Pi 1.3.0.
// patch.pi-1.4.mjs + edits.pi-1.4.json: Pi 1.4.x, anchor-gated (bundle chunks found by content).
// patch.pi-1.5.mjs + edits.pi-1.5.json: Pi 1.5.0 and later, anchor-gated (same chunk lookup).
import { dispatchByPiVersion } from "../pi-select.mjs";

dispatchByPiVersion(import.meta.url, {
	name: "btw-native-session",
	variants: { "1.1": "patch.pi-1.1.mjs", "1.2": "patch.pi-1.2.mjs", "1.3": "patch.pi-1.3.mjs", "1.4": "patch.pi-1.4.mjs", "1.5": "patch.pi-1.5.mjs" },
});
