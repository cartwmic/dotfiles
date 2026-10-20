import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { registerNotifyOwner } from "./helpers.ts";

export default function (pi: ExtensionAPI): void {
  registerNotifyOwner(pi as never, Type as never);
}
