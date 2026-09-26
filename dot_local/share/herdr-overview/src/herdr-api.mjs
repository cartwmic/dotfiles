import net from "node:net";
import { randomUUID } from "node:crypto";
import { HERDR_PROTOCOL } from "./model.mjs";

export class HerdrApiError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "HerdrApiError";
    this.code = code;
  }
}

export class HerdrApi {
  constructor({ socketPath = process.env.HERDR_SOCKET_PATH, timeoutMs = 10_000 } = {}) {
    if (!socketPath) throw new Error("HERDR_SOCKET_PATH is required");
    this.socketPath = socketPath;
    this.timeoutMs = timeoutMs;
  }

  request(method, params = {}) {
    const id = `herdr-overview:${randomUUID()}`;
    return new Promise((resolve, reject) => {
      const socket = net.createConnection({ path: this.socketPath });
      let buffer = "";
      let settled = false;
      const finish = (callback, value) => {
        if (settled) return;
        settled = true;
        socket.destroy();
        callback(value);
      };
      socket.setTimeout(this.timeoutMs, () => finish(reject, new Error(`Herdr API ${method} timed out`)));
      socket.once("error", (error) => finish(reject, error));
      socket.once("connect", () => socket.write(`${JSON.stringify({ id, method, params })}\n`));
      socket.on("data", (chunk) => {
        buffer += chunk.toString("utf8");
        let newline;
        while ((newline = buffer.indexOf("\n")) >= 0) {
          const line = buffer.slice(0, newline);
          buffer = buffer.slice(newline + 1);
          if (!line.trim()) continue;
          let message;
          try {
            message = JSON.parse(line);
          } catch (error) {
            finish(reject, new Error(`invalid Herdr API response: ${error.message}`));
            return;
          }
          if (message.id !== id) continue;
          if (message.error) {
            finish(reject, new HerdrApiError(message.error.code, message.error.message));
          } else {
            finish(resolve, message.result);
          }
          return;
        }
      });
    });
  }

  subscribe(subscriptions, onEvent, onError = () => {}) {
    const id = `herdr-overview:${randomUUID()}`;
    return new Promise((resolve, reject) => {
      const socket = net.createConnection({ path: this.socketPath });
      let buffer = "";
      let acknowledged = false;
      const fail = (error) => {
        if (!acknowledged) reject(error);
        else onError(error);
        socket.destroy();
      };
      socket.setTimeout(0);
      socket.once("error", fail);
      socket.once("close", () => {
        if (!acknowledged) reject(new Error("Herdr event subscription closed before acknowledgement"));
      });
      socket.once("connect", () => socket.write(`${JSON.stringify({ id, method: "events.subscribe", params: { subscriptions } })}\n`));
      socket.on("data", (chunk) => {
        buffer += chunk.toString("utf8");
        let newline;
        while ((newline = buffer.indexOf("\n")) >= 0) {
          const line = buffer.slice(0, newline);
          buffer = buffer.slice(newline + 1);
          if (!line.trim()) continue;
          let message;
          try {
            message = JSON.parse(line);
          } catch (error) {
            fail(new Error(`invalid Herdr event response: ${error.message}`));
            return;
          }
          if (message.id === id) {
            if (message.error) { fail(new HerdrApiError(message.error.code, message.error.message)); return; }
            acknowledged = true;
            resolve({ close: () => socket.destroy() });
            continue;
          }
          if (acknowledged && message.event) {
            try { Promise.resolve(onEvent(message)).catch(onError); }
            catch (error) { onError(error); }
          }
        }
      });
    });
  }

  async snapshot() {
    const result = await this.request("session.snapshot");
    const snapshot = result?.snapshot;
    if (!snapshot || snapshot.protocol !== HERDR_PROTOCOL) {
      throw new Error(`Herdr protocol ${HERDR_PROTOCOL} required; server reports ${snapshot?.protocol ?? "unknown"}`);
    }
    return snapshot;
  }

  async readPane(paneId, { lines = 12, source = "recent_unwrapped" } = {}) {
    const result = await this.request("pane.read", { pane_id: paneId, source, lines, format: "text", strip_ansi: true });
    return result?.read?.text ?? "";
  }

  async processInfo(paneId) {
    const result = await this.request("pane.process_info", { pane_id: paneId });
    return result?.process_info ?? null;
  }

  focusPane(paneId) {
    return this.request("pane.focus", { pane_id: paneId });
  }

  renamePane(paneId, label) {
    return this.request("pane.rename", { pane_id: paneId, label });
  }

  renameTab(tabId, label) {
    return this.request("tab.rename", { tab_id: tabId, label });
  }

  resetDisplayName(kind, id) {
    if (!new Set(["pane", "tab"]).has(kind) || typeof id !== "string" || !id) {
      throw new TypeError("automatic naming reset requires a pane or tab ID");
    }
    return this.request("plugin.action.invoke", {
      action_id: `overview.auto_name_${kind}`,
      context: kind === "pane" ? { focused_pane_id: id } : { tab_id: id },
    });
  }

  closePane(paneId) {
    return this.request("pane.close", { pane_id: paneId });
  }

  openOverviewPane({ placement = "tab", focus = false } = {}) {
    return this.request("plugin.pane.open", {
      plugin_id: "overview",
      entrypoint: "overview",
      placement,
      focus,
    });
  }
}
