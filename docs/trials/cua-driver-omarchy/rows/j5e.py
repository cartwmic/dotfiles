import sys, json, time, subprocess; sys.path.insert(0, "/home/cartwmic/.cache/cua-driver-trial/scripts")
import cua
E="/home/cartwmic/.local/share/coordinator/workstreams/read-agent-desktop/poc-cua/omarchy"
def show(r): print(json.dumps({k: r.get(k) for k in ["route","summary","effect","code","hint","delivery","_exit","_ms","reason","detail","verified","popup"] if r.get(k) is not None}, indent=1)[:1100])
LBL=cua.L("j5e")
w = cua.windows(); n = w["org.gnome.Nautilus"]; pid, wid = n["pid"], n["window_id"]
s = cua.snap(pid, wid, LBL, shot=True, shot_file="/tmp/bd28-cua/n1.png")
cell = [e for e in cua.els(s) if "readme_extra" in (e.get("label") or "")][0]
print("cell", cell["element_token"], cell["actions"])
print("== right_click by ref, foreground"); r = cua.call("right_click", {"pid": pid, "window_id": wid, "element_token": cell["element_token"], "delivery_mode":"foreground"}, LBL); show(r)
time.sleep(2)
cua.call("get_desktop_state", {"screenshot_out_file": E+"/j5-right-click-ref-foreground-nautilus.png"})
cua.call("end_session", {"session": LBL})
