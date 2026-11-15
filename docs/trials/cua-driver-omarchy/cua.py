"""Small helper for the Cua Driver Omarchy trial: call cua-driver tools in the NESTED session, return parsed JSON and ms."""
import json, os, subprocess, time, re
HOME = os.path.expanduser("~")
CUAD = f"{HOME}/.cache/cua-driver-trial/src/cua-driver-rs-0.51.5-linux-arm64/cua-driver"
ENV = dict(os.environ, CUA_DRIVER_RS_ENABLE_WAYLAND="1", CUA_DRIVER_RS_HOME=f"{HOME}/.cache/cua-driver-trial/home")
# nested env (signature + wayland-2) read from env.sh
for line in open(f"{HOME}/.cache/cua-driver-trial/nested/env.sh"):
    m = re.match(r"export (HYPRLAND_INSTANCE_SIGNATURE|WAYLAND_DISPLAY)=(.*)", line.strip())
    if m: ENV[m.group(1)] = m.group(2)

def call(tool, args=None, session=None):
    a = dict(args or {})
    if session: a["session"] = session
    t = time.time()
    p = subprocess.run([CUAD, "call", tool, json.dumps(a)], capture_output=True, text=True, env=ENV)
    ms = round((time.time() - t) * 1000)
    out = p.stdout.strip()
    try: j = json.loads(out)
    except Exception: j = {"_raw": out, "_err": p.stderr.strip()}
    j["_exit"] = p.returncode; j["_ms"] = ms
    return j

def hypr(*a):
    return subprocess.run(["hyprctl", *a], capture_output=True, text=True, env=ENV).stdout.strip()

def windows():
    return {(w["app_name"]): w for w in call("list_windows")["windows"]}

def snap(pid, wid, session, shot=None, shot_file=None):
    a = {"pid": pid, "window_id": wid, "tree_format": "elements"}
    if shot_file: a["screenshot_out_file"] = shot_file
    elif not shot: a["include_screenshot"] = False
    return call("get_window_state", a, session)

def els(s): return s.get("elements", [])

def L(name):
    """Unique session label (ended labels cannot be reused)."""
    return f"{name}-{int(time.time())}"
