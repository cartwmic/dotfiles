#!/usr/bin/env python3
"""Drive real mise -> official installer/update -> patch loop in a private HOME.

Uses the installed Pi dependencies and canonical response-visibility helper.
Downloads the official installer and matching stock Pi/pi-ai tarballs, but routes
release management to a scripted local server and replaces npm ci with a private
copy. No live installation, credentials, paid calls, or global npm changes.
"""
import hashlib
import http.server
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import threading
import tomllib
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
PATCHES = ROOT / "dot_local/share/pi-patches"
SCOPE = "@earendil-works"
NAMES = ["install-pi", "update-pi", "apply-pi-patches"]


def require(value, message):
    if not value:
        raise RuntimeError(message)


def run(args, env=None, cwd=None, success=True):
    result = subprocess.run(args, env=env, cwd=cwd, text=True, capture_output=True, timeout=90)
    require((result.returncode == 0) == success, " ".join(map(str, args)) + "\n" + result.stdout + result.stderr)
    return result.stdout + result.stderr


def executable(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


def main():
    node, mise, curl, python = [shutil.which(x) for x in ["node", "mise", "curl", "python3"]]
    require(all([node, mise, curl, python]), "Node, mise, curl and Python are required")
    locator = PATCHES / "pi-root.mjs"
    pca = Path(run([node, "--input-type=module", "-e",
                   f'import {{piCodingAgentRoot}} from {json.dumps(locator.as_uri())}; console.log(piCodingAgentRoot());']).strip())
    release = pca.parents[2]
    require(release.name == "1.1.0", "this fixture is prepared for managed Pi 1.1.0")
    helper = Path(os.environ.get("PI_RESPONSE_VISIBILITY_HELPER",
                  str(Path.home() / ".pi/agent/git/github.com/cartwmic/pi-response-visibility/bin/core.mjs")))
    require(helper.is_file(), "install the canonical response-visibility package first")
    original = hashlib.sha256((pca / "dist/bundle/cli.js").read_bytes()).hexdigest()
    tasks = tomllib.loads((ROOT / "dot_config/mise/config.toml").read_text())["tasks"]

    with tempfile.TemporaryDirectory(prefix="pi-managed-proof-") as temporary:
        base = Path(temporary)
        stock = base / "stock"
        shutil.copytree(release / "node_modules", stock / "node_modules", symlinks=True)
        for name in ["pi-coding-agent", "pi-ai"]:
            target = stock / "node_modules" / SCOPE / name
            version = json.loads((target / "package.json").read_text())["version"]
            url = f"https://registry.npmjs.org/{SCOPE}/{name}/-/{name}-{version}.tgz"
            payload = urllib.request.urlopen(url, timeout=30).read()
            shutil.rmtree(target)
            target.mkdir()
            with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
                # Published package paths all start with package/.
                for entry in archive.getmembers():
                    require(entry.name.startswith("package/"), "unexpected tarball path")
                    entry.name = entry.name[len("package/"):]
                    if entry.name:
                        archive.extract(entry, target, filter="data")
        installer = base / "install.sh"
        installer.write_bytes(subprocess.check_output([curl, "-fsSL", "https://pi.dev/install.sh"], timeout=30))

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                server.requests.append((self.path, server.latest))
                if self.path in ["/latest-version", "/latest"]:
                    payload = {"version": server.latest, "packageName": f"{SCOPE}/pi-coding-agent"}
                elif self.path.endswith("/package.json"):
                    version = self.path.split("/")[1]
                    payload = {"name": "fixture", "version": version,
                               "dependencies": {f"{SCOPE}/pi-coding-agent": version}}
                elif self.path.endswith("/package-lock.json"):
                    version = self.path.split("/")[1]
                    payload = {"version": version, "lockfileVersion": 3, "packages": {
                        "": {"version": version, "dependencies": {f"{SCOPE}/pi-coding-agent": version}},
                        f"node_modules/{SCOPE}/pi-coding-agent": {"version": version}}}
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.latest = "1.1.0"
        server.requests = []
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            home = base / "home"
            tools = base / "tools"
            home.mkdir()
            tools.mkdir()
            (tools / "node").symlink_to(node)
            (tools / "mise").symlink_to(mise)
            (tools / "jq").symlink_to(shutil.which("jq"))
            # No inherited Pi roots or real-home XDG directories can escape the sandbox.
            env = {k: v for k, v in os.environ.items()
                   if not k.startswith(("PI_", "MISE_", "XDG_", "HERDR_", "NODE_"))
                   and not any(x in k for x in ["TOKEN", "API_KEY", "_MISE_"])}
            env.update(HOME=str(home), PATH=f"{tools}:{Path(node).parent}:/usr/bin:/bin",
                       XDG_CONFIG_HOME=str(home / ".config"), XDG_DATA_HOME=str(home / ".local/share"),
                       XDG_CACHE_HOME=str(home / ".cache"), XDG_STATE_HOME=str(home / ".local/state"),
                       MISE_YES="1", MISE_TASK_RUN_AUTO_INSTALL="false",
                       PI_INSTALLER_API_BASE=f"http://127.0.0.1:{server.server_port}",
                       PI_CHEZMOI_PROFILE="personal", PI_RESPONSE_VISIBILITY_HELPER=str(helper),
                       FIXTURE_STOCK=str(stock), FIXTURE_INSTALLER=str(installer),
                       FIXTURE_EVENTS=str(base / "events"), FIXTURE_CURL=curl,
                       FIXTURE_PREFIX=str(base / "legacy"))
            config = home / ".config/mise/config.toml"
            config.parent.mkdir(parents=True)
            # These are the exact source task contracts; omit unrelated tools/bootstrap.
            config.write_text("\n".join(
                f'[tasks."{name}"]\ndescription = {json.dumps(tasks[name]["description"])}\n'
                + (f'depends_post = {json.dumps(tasks[name]["depends_post"])}\n' if "depends_post" in tasks[name] else "")
                + "run = \'\'\'\n" + tasks[name]["run"] + "\'\'\'\n" for name in NAMES))
            deployed = home / ".local/share/pi-patches"
            shutil.copytree(PATCHES, deployed)
            script = home / ".local/user_scripts/apply_pi_patches.sh"
            script.parent.mkdir(parents=True)
            shutil.copy2(ROOT / "dot_local/user_scripts/executable_apply_pi_patches.sh", script)

            executable(tools / "chezmoi", """#!/bin/sh
printf '%s\\n' '{"profile":"personal"}'
""")
            executable(tools / "curl", f"""#!{python}
import os, shutil, subprocess, sys
args = sys.argv[1:]
if "https://pi.dev/install.sh" in args:
    with open(os.environ["FIXTURE_EVENTS"], "a") as f: f.write("installer\\n")
    shutil.copyfile(os.environ["FIXTURE_INSTALLER"], args[args.index("-o")+1])
else:
    sys.exit(subprocess.call([os.environ["FIXTURE_CURL"], *args]))
""")
            executable(tools / "npm", f"""#!{python}
import json, os, pathlib, shutil, sys
args = sys.argv[1:]
prefix = pathlib.Path(os.environ["FIXTURE_PREFIX"])
with open(os.environ["FIXTURE_EVENTS"], "a") as f: f.write("npm " + " ".join(args) + "\\n")
if args[:1] == ["ci"]:
    if os.environ.get("FIXTURE_FAIL_CI"): sys.exit(1)
    shutil.copytree(pathlib.Path(os.environ["FIXTURE_STOCK"]) / "node_modules", pathlib.Path.cwd() / "node_modules", symlinks=True)
    version = json.loads(pathlib.Path("package.json").read_text())["version"]
    p = pathlib.Path("node_modules/@earendil-works/pi-coding-agent/package.json")
    data = json.loads(p.read_text()); data["version"] = version; p.write_text(json.dumps(data))
elif args == ["prefix", "-g"]: print(prefix)
elif args == ["root", "-g"]: print(prefix / "lib/node_modules")
elif args[:1] == ["ls"]: sys.exit(0 if (prefix / "bin/pi").exists() else 1)
elif args[:1] == ["uninstall"]: (prefix / "bin/pi").unlink()
else: raise SystemExit("Unexpected npm invocation: " + str(args))
""")
            route = base / "route.mjs"
            route.write_text("""import fs from "node:fs";
fs.appendFileSync(process.env.FIXTURE_EVENTS, "route-loaded\\n");
let fetch = globalThis.fetch;
const routedFetch = (input, init) => {
  let url = String(input);
  fs.appendFileSync(process.env.FIXTURE_EVENTS, "fetch " + url + "\\n");
  if (url === 'https://pi.dev/api/latest-version')
    url = process.env.PI_INSTALLER_API_BASE + '/latest-version';
  if (!url.startsWith(process.env.PI_INSTALLER_API_BASE + '/'))
    throw new Error('Unexpected network request: ' + url);
  return fetch(url, init);
};
// Pi configures an undici dispatcher and replaces global fetch during startup.
// Keep the scripted network boundary even when that replacement occurs.
Object.defineProperty(globalThis, "fetch", {
  configurable: true, get: () => routedFetch, set: value => { fetch = value; }
});
""")
            env["NODE_OPTIONS"] = f"--import={route}"
            prefix = Path(env["FIXTURE_PREFIX"])
            (prefix / "lib/node_modules").mkdir(parents=True)
            executable(prefix / "bin/pi", "#!/bin/sh\necho legacy\n")
            env["PATH"] += f":{prefix / 'bin'}"

            def task(name, success=True):
                return run([mise, "run", "--skip-tools", name], env, base, success)

            def check():
                for patch in sorted(deployed.glob("*/patch.mjs")):
                    # Retired restore: absent legacy widgets are a successful apply
                    # no-op, but its historical --check requires an installed tree.
                    if patch.parent.name == "cursor-provider":
                        output = run([node, str(patch)], env, base)
                        require("nothing to patch" in output, "retired widget unexpectedly found")
                    else:
                        run([node, str(patch), "--check"], env, base)

            # Migration still occurs when a legacy pi already exists on PATH.
            task("install-pi")
            require(not (prefix / "bin/pi").exists(), "legacy npm Pi was not migrated")
            check()
            events = Path(env["FIXTURE_EVENTS"]).read_text()
            require(events.count("installer\n") == 1, "installer was not called exactly once")
            task("install-pi")
            require(Path(env["FIXTURE_EVENTS"]).read_text().count("installer\n") == 1, "repeat run reinstalled Pi")
            check()
            print("PASS: official installer, npm migration, all nine patches, repeat-run idempotence")

            server.latest = "1.1.1"
            update_output = task("update-pi")
            active = home / ".pi/agent/install"
            require((active / "current-version").read_text().strip() == "1.1.1", "update did not activate next release:\n" + repr(server.requests) + "\n" + Path(env["FIXTURE_EVENTS"]).read_text() + "\n" + update_output)
            check()
            print("PASS: real managed Pi update activates a clean fixture release; all nine patches follow it")

            # Upstream failure must stop before patching or changing the active version.
            server.latest = "1.1.2"
            failed_env = {**env, "FIXTURE_FAIL_CI": "1"}
            run([mise, "run", "--skip-tools", "update-pi"], failed_env, base, success=False)
            require((active / "current-version").read_text().strip() == "1.1.1", "failed update changed active release")
            check()
            # Patch failures must also propagate through the parent mise task.
            bad = deployed / "fixture-failure/patch.mjs"
            bad.parent.mkdir()
            bad.write_text("process.exit(1);\n")
            task("install-pi", success=False)
            bad.unlink()
            bad.parent.rmdir()
            print("PASS: install/update/patch failures return failure")

            # Fresh install: remove only this test's managed tree, no legacy executable.
            shutil.rmtree(home / ".pi/agent")
            server.latest = "1.1.0"
            task("install-pi")
            check()
            print("PASS: fresh managed installation and completed patch loop")
            standalone = {k: v for k, v in env.items() if k != "PI_CHEZMOI_PROFILE"}
            run([mise, "run", "--skip-tools", "apply-pi-patches"], standalone, base)
            executable(tools / "chezmoi", "#!/bin/sh\nexit 1\n")
            run([mise, "run", "--skip-tools", "apply-pi-patches"], standalone, base, success=False)
            run([mise, "run", "--skip-tools", "apply-pi-patches"],
                {**env, "PI_PATCHES_ROOT": str(base / "missing")}, base, success=False)
            print("PASS: standalone profile discovery; missing profile or patch source fails closed")
        finally:
            server.shutdown()
            server.server_close()
    require(hashlib.sha256((pca / "dist/bundle/cli.js").read_bytes()).hexdigest() == original,
            "live Pi was modified")
    print("PASS: live Pi unchanged; private resources removed")


if __name__ == "__main__":
    main()
