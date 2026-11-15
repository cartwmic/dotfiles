import sys, json, time, subprocess, statistics; sys.path.insert(0, "/home/cartwmic/.cache/cua-driver-trial/scripts")
import cua
E="/home/cartwmic/.local/share/coordinator/workstreams/read-agent-desktop/poc-cua/omarchy"
CROP="400x130+220+55"   # display area in the 638x798 window screenshot
def crop(src, dst): subprocess.run(["magick", src, "-crop", CROP, "+repage", dst], check=True)
def diff(a, b):
    p = subprocess.run(["compare", "-metric", "AE", a, b, "null:"], capture_output=True, text=True); 
    try: return int(float(p.stderr.strip().split()[0]))
    except Exception: return -1
w = cua.windows(); n = w["omacalc"]; pid, wid = n["pid"], n["window_id"]
order = ["All clear","1","2","Multiply","3","4","Equals"]
results = []
for run in (1,2,3):
    LBL = cua.L(f"n3r{run}")
    t0 = time.time()
    s = cua.snap(pid, wid, LBL)
    snap_ms = s["_ms"]
    tok = {e["label"]: e["element_token"] for e in cua.els(s) if e.get("label")}
    clicks = []; errs = []
    for name in order:
        r = cua.call("click", {"pid": pid, "window_id": wid, "element_token": tok[name]}, LBL)
        clicks.append(r["_ms"])
        if r["_exit"] != 0: errs.append((name, r.get("code")))
    time.sleep(0.5)
    ss = f"{E}/n3-run{run}-window.png"
    r = cua.call("get_window_state", {"pid": pid, "window_id": wid, "include_accessibility_tree": False, "screenshot_out_file": ss}, LBL)
    shot_ms = r["_ms"]
    crop(ss, f"{E}/n3-run{run}-display-crop.png")
    cua.call("end_session", {"session": LBL})
    results.append(dict(run=run, snap_ms=snap_ms, clicks=clicks, shot_ms=shot_ms, errs=errs, total_s=round(time.time()-t0,2)))
    print(json.dumps(results[-1]))
ref = f"{E}/n3-reference-display-408.png"
subprocess.run(["cp", f"{E}/n3-run1-display-crop.png", ref])
for run in (1,2,3): print("run", run, "diff vs ref (pixels):", diff(f"{E}/n3-run{run}-display-crop.png", ref))
# negative control: AC only then crop
LBL = cua.L("n3neg"); s = cua.snap(pid, wid, LBL); tok = {e["label"]: e["element_token"] for e in cua.els(s) if e.get("label")}
cua.call("click", {"pid": pid, "window_id": wid, "element_token": tok["All clear"]}, LBL); time.sleep(0.5)
ss=f"{E}/n3-neg-afterAC-window.png"; cua.call("get_window_state", {"pid": pid, "window_id": wid, "include_accessibility_tree": False, "screenshot_out_file": ss}, LBL)
crop(ss, f"{E}/n3-neg-afterAC-crop.png"); print("negative control diff after AC vs 408 ref:", diff(f"{E}/n3-neg-afterAC-crop.png", ref))
cua.call("end_session", {"session": LBL})
allc = [c for r in results for c in r["clicks"]]
print("clicks n", len(allc), "median ms", statistics.median(allc), "max", max(allc), "p90", sorted(allc)[int(len(allc)*0.9)-1])
print("snap ms", [r["snap_ms"] for r in results])
