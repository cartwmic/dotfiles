import sys, json, time; sys.path.insert(0, "/home/cartwmic/.cache/cua-driver-trial/scripts")
import cua
E="/home/cartwmic/.local/share/coordinator/workstreams/read-agent-desktop/poc-cua/omarchy"
def show(r): print("  ", json.dumps({k: r.get(k) for k in ["route","summary","effect","code","delivery","_exit","_ms","reason","detail"] if r.get(k) is not None})[:400])
w = cua.windows(); n = w["cmake-gui"]; pid, wid = n["pid"], n["window_id"]; b = n["bounds"]
LBL = cua.L("j7b")
def src():
    s = cua.snap(pid, wid, LBL, shot=True, shot_file="/tmp/bd28-cua/c7.png")
    e = [e for e in cua.els(s) if e["role"]=="text" and (e.get("label") or "").startswith(("Where is the source","hello","q"))]
    return s, e
for _ in range(4):
    s, e = src()
    if e: break
    time.sleep(1)
print("count", s.get("element_count"), {k:s.get(k) for k in ("code","degraded","truncated")})
print("values before:", [(x["element_token"], x.get("value"), x["frame"]) for x in e])
tgt = e[0]; f = tgt["frame"]
x = int(f["x"]+f["w"]/2 - b["x"]); y = int(f["y"]+f["h"]/2 - b["y"])
print("1. type_text 'hello' by ref (AT-SPI)"); r = cua.call("type_text", {"pid":pid,"window_id":wid,"element_token":tgt["element_token"],"text":"hello"}, LBL); show(r)
s, e = src(); print("   value now:", [(x_.get("value")) for x_ in e])
print("2. foreground click into the field x,y", x, y); r = cua.call("click", {"pid":pid,"window_id":wid,"x":x,"y":y,"delivery_mode":"foreground"}, LBL); show(r)
print("3. hotkey ctrl+a (foreground)"); r = cua.call("hotkey", {"pid":pid,"window_id":wid,"keys":["ctrl","a"],"delivery_mode":"foreground"}, LBL); show(r)
print("4. press_key q (foreground)"); r = cua.call("press_key", {"pid":pid,"window_id":wid,"key":"q","delivery_mode":"foreground"}, LBL); show(r)
time.sleep(0.5)
s, e = src(); print("   values after:", [(x_.get("value")) for x_ in e])
cua.call("get_window_state", {"pid":pid,"window_id":wid,"include_accessibility_tree":False,"screenshot_out_file":E+"/j7-ctrl-a-then-q.png"}, LBL)
cua.call("end_session", {"session": LBL})
