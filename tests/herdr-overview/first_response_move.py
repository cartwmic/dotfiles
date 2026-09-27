#!/usr/bin/env python3
"""Prove a real Pi pane.move before its first scripted response publishes.

Run against a fresh `proof.py herdr-prepare` fixture. This proof starts its
own recorded scripted provider. Always run `proof.py herdr-cleanup` for this
run afterward, including on failure.
"""
import argparse
import json
import shlex
import shutil
from pathlib import Path

import proof as p


def prove(run_id: str, output: Path) -> None:
    root, state, env = p.load_run(run_id)
    provider = p.ensure_scripted_provider(root, state, env)
    if Path(provider["release_file"]).exists() or p.provider_requests(root):
        raise p.ProofBlocked("first-response proof requires an unused scripted provider")
    real_pi = shutil.which("pi")
    if not real_pi:
        raise p.ProofBlocked("Pi is required for the actual first-response journey")
    old = state["fixture"]["pi_pane_id"]
    target_workspace = state["fixture"]["workspaces"][1]
    target = target_workspace["workspace_id"]
    session_id = f"herdr-first-move-{run_id}"
    prompt = f"First response pending move {run_id}: report the current task."
    data = Path(env["XDG_DATA_HOME"]) / "session-recap"
    outcome = {"run_id": run_id, "status": "FAIL", "old_pane_id": old, "target_workspace_id": target}
    try:
        extension = root / "scripted-pi-provider.mjs"
        p.make_pi_provider_extension(extension)
        p.write_exec(root / "bin/pi", "#!/bin/sh\nset -eu\n"
                     'if [ -r "$HERDR_OVERVIEW_TEST_PROVIDER_URL_FILE" ]; then\n'
                     '  IFS= read -r HERDR_OVERVIEW_TEST_PROVIDER_URL < "$HERDR_OVERVIEW_TEST_PROVIDER_URL_FILE"\n'
                     '  export HERDR_OVERVIEW_TEST_PROVIDER_URL\n'
                     'fi\n'
                     f'exec {shlex.quote(real_pi)} "$@"\n')
        Path(env["HERDR_OVERVIEW_TEST_PROVIDER_URL_FILE"]).write_text(provider["url"] + "\n")
        env["HERDR_OVERVIEW_TEST_PROVIDER_URL"] = provider["url"]
        p.herdr_cmd(state, env, "agent", "start", "first-move-pi", "--kind", "pi", "--pane", old,
                    "--timeout", "120000", "--", "--provider", "herdr-proof-scripted", "--model", "scripted-model",
                    "--extension", str(p.ROOT / "dot_pi/private_agent/extensions/herdr-overview/index.ts"),
                    "--extension", str(extension), "--no-skills", "--no-prompt-templates", "--no-themes",
                    "--no-context-files", "--no-tools", "--offline", "--approve", "--session-dir", str(root / "pi-sessions"),
                    "--session-id", session_id, timeout=130)
        submitted = p.herdr_cmd(state, env, "agent", "prompt", "first-move-pi", prompt, timeout=30)
        outcome["prompt_submission"] = {"exit": submitted.returncode, "stdout": p.bounded(submitted.stdout, 400)}
        p.wait_for(lambda: p.provider_requests(root)[0] if p.provider_requests(root) else None,
                   "Pi's first real provider request", timeout=60)
        working = p.wait_for(lambda: p.read_pi_prompt(data, old), "first working prompt", timeout=20)
        if working["text"] != prompt or working["working"] is not True:
            raise p.ProofFailure("the first Pi input was not stored as a working prompt")
        p.invoke_overview(state, env)
        p.wait_for(lambda: (p.plugin_state(root).get("model", {}).get("panes", {}).get(old, {}).get("prompt") or {}).get("text") == prompt,
                   "first prompt in the visible overview", timeout=20)
        p.invoke_auto_name(state, "pane", old)
        p.wait_for(lambda: (p.plugin_state(root).get("displayNameOwnership", {}).get(f"pane:{old}") or {}).get("mode") == "automatic",
                   "automatic name ownership before the move", timeout=20)
        native_before = p.one_by(p.snapshot(state)["panes"], "pane_id", old)
        moved = p.herdr_cmd(state, env, "pane", "move", old, "--new-tab", "--workspace", target, "--no-focus")
        result = json.loads(moved.stdout)["result"]["move_result"]
        new = result["pane"]["pane_id"]
        if result["previous_pane_id"] != old or new == old:
            raise p.ProofFailure("native pane.move did not rekey the pending Pi pane")
        outcome["new_pane_id"] = new
        native_after = p.one_by(p.snapshot(state)["panes"], "pane_id", new)
        if native_before["terminal_id"] != native_after["terminal_id"]:
            raise p.ProofFailure("native pane.move changed the Pi terminal identity")

        def moved_working():
            current = p.plugin_state(root)
            pane = current.get("model", {}).get("panes", {}).get(new, {})
            ownership = current.get("displayNameOwnership", {}).get(f"pane:{new}", {})
            if (pane.get("prompt") or {}).get("text") == prompt and ownership.get("mode") == "automatic":
                return current
            return None

        current = p.wait_for(moved_working, "working prompt and automatic ownership on the rekeyed pane", timeout=25)
        if old in current["model"]["panes"] or f"pane:{old}" in current["displayNameOwnership"]:
            raise p.ProofFailure("moved Pi pane retained its obsolete native identity")
        outcome["working_prompt_on_new_pane"] = True
        outcome["ownership_after_move"] = current["displayNameOwnership"][f"pane:{new}"]["mode"]
        p.select_workspace(state, env, target_workspace)
        detail = p.open_pane_from_workspace(
            state, env, new,
            match_detail=lambda text: p.current_prompt_detail_visible(text, new, prompt, require_id=False),
        )
        if not p.current_prompt_detail_visible(detail, new, prompt, require_id=False):
            raise p.ProofFailure("visible Board detail omitted the moved working prompt")
        outcome["visible_working_detail"] = True

        Path(provider["release_file"]).touch()
        latest = p.wait_for(lambda: p.read_latest_pi_record(data, new)[0],
                            "first published Pi recap under the new pane ID", timeout=40)
        if latest.get("source_id") != session_id or latest.get("workspace_id") != target:
            raise p.ProofFailure("first Pi publication has wrong source or destination membership")
        settled = p.read_pi_prompt(data, new)
        if not settled or settled["text"] != prompt or settled["working"] is not False:
            raise p.ProofFailure("first Pi prompt did not settle on the rekeyed native pane")
        outcome["published_record_id"] = latest["record_id"]
        outcome["published_pane_id"] = latest["pane_id"]
        outcome["settled_prompt_pane_id"] = settled["pane_id"]

        def published_detail():
            text = p.overview_text(state, env)
            return text if p.current_prompt_detail_visible(text, new, prompt, require_id=False) \
                and p.published_recap_detail_visible(text, latest["summary"]) else None

        p.wait_for(published_detail, "visible current prompt and published recap on destination Board detail", timeout=30)
        outcome["visible_published_detail"] = True
        p.wait_for(lambda: p.one_by(p.snapshot(state)["panes"], "pane_id", new).get("label") == latest["summary"],
                   "automatic pane label updated after first publication", timeout=20)
        outcome["automatic_native_label"] = latest["summary"]

        def destination_group():
            entry = p.latest_entry(data, "workspace", target)
            if not entry or not entry.get("latest_success_id"):
                return None
            _path, record = p.find_record(data, entry["latest_success_id"])
            return record if latest["record_id"] in record.get("member_record_ids", []) else None

        grouped = p.wait_for(destination_group, "destination group containing the moved first recap", timeout=45)
        outcome["destination_group_id"] = grouped["record_id"]
        outcome["status"] = "PASS"
    except Exception as exc:
        outcome["failure"] = str(exc)
        try:
            current = p.plugin_state(root)
            outcome["failure_state"] = {
                "pane_ids": list((current.get("model") or {}).get("panes", {})),
                "new_pane_prompt": ((current.get("model") or {}).get("panes", {}).get(outcome.get("new_pane_id"), {}) or {}).get("prompt"),
                "ownership": current.get("displayNameOwnership"),
                "terminal_associations": (current.get("recapCoordinator") or {}).get("piTerminalIdsBySessionId"),
            }
        except (OSError, ValueError):
            pass
        raise
    finally:
        Path(provider["release_file"]).touch()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(outcome, indent=2) + "\n")
        print(json.dumps(outcome, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    prove(args.run_id, args.output)
