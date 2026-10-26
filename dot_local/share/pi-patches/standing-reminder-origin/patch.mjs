// Entry point (apply loop, onchange hash, proofs). Selects the payload for the installed Pi minor series; see ../pi-select.mjs.
import { dispatchByPiVersion } from "../pi-select.mjs";

dispatchByPiVersion(import.meta.url, {
	name: "standing-reminder-origin",
	packageEnv: "PI_STANDING_REMINDER_ORIGIN_PACKAGE",
	variants: { "1.1": "patch.pi-1.1.mjs", "1.2": "patch.pi-1.2.mjs" },
});
