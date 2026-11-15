import sys, json, time; sys.path.insert(0, "/home/cartwmic/.cache/cua-driver-trial/scripts")
import cua
def show(r): print(json.dumps({k: r.get(k) for k in ["route","summary","effect","code","hint","delivery","_exit","_ms","reason","detail","verified","status","refusal"] if r.get(k) is not None})[:700])
w = cua.windows(); n = w["org.gnome.Nautilus"]; pid, wid = n["pid"], n["window_id"]
f = w["foot"]; cua.call("bring_to_front", {"pid": f["pid"], "window_id": f["window_id"]}); time.sleep(0.5)
LBL = cua.L("n4"); 
s = cua.snap(pid, wid, LBL, shot=True, shot_file="/tmp/bd28-cua/n4a.png"); snap1 = s["snapshot_id"]
cells = [(e["element_token"], e["label"]) for e in cua.els(s) if e["role"]=="grid cell"]
print("snap1", snap1, cells)
folder = [t for t,l in cells if "cua." in l][0]; fileTok = [t for t,l in cells if "readme_extra" in l][0]
print("== A: open folder 'cua' by ref (double-click, count=2), background"); r = cua.call("click", {"pid": pid, "window_id": wid, "element_token": folder, "count": 2}, LBL); show(r)
time.sleep(2)
print("== B: click OLD ref for readme_extra.sh WITHOUT re-snapshot (UI changed underneath)"); r = cua.call("click", {"pid": pid, "window_id": wid, "element_token": fileTok}, LBL); show(r)
s2 = cua.snap(pid, wid, LBL, shot=True, shot_file="/tmp/bd28-cua/n4b.png")
print("snap2", s2["snapshot_id"], "invalidated:", s2.get("invalidated_snapshot_ids"), [ (e["element_token"], e["label"]) for e in cua.els(s2) if e["role"]=="grid cell"][:4])
print("== C: click OLD ref from snap1 after re-snapshot"); r = cua.call("click", {"pid": pid, "window_id": wid, "element_token": fileTok}, LBL); show(r)
cua.call("end_session", {"session": LBL})
