#!/bin/sh
# Live proof for the one-ssh-connection-per-job change (dotfiles PR "kgate-ssh-mux"). Run after the PR is merged and chezmoi has applied ~/.local/bin/kgate.
# Runs one real homelab job that waits 15 s for a pod it cannot get (pinned to a node that does not exist), and one that runs a command, and samples
# every 0.1 s the TCP connections to the control planes' sshd that belong to the job (its ssh processes and its ssh master).
# Expected for each: exit 75 and exit 0, connections_opened=1 and peak_simultaneous=1 (the old client opened about one per poll: 6 to 9), and
# "ssh masters=0, folders still there=0" a second and a half after the job ends. Reads the control-plane addresses from KGATE_SSH or ~/.config/kgate/host.
set -eu
image=${KGATE_PROOF_IMAGE:-$(sed -n 's/^image *= *"\(.*\)"/\1/p' "$HOME/git/coordinator/kgate.toml" | head -1)}
[ -n "$image" ] || { echo "no image: set KGATE_PROOF_IMAGE" >&2; exit 64; }
hosts=${KGATE_SSH:-$(cat "$HOME/.config/kgate/host")}
addrs=$(printf '%s\n' "$hosts" | tr ',' '\n' | sed 's/.*@//' | grep .)
repo=$(mktemp -d /tmp/kgate-ssh-mux-proof.XXXXXX)
trap 'rm -rf "$repo"' EXIT
cd "$repo"
git init -q
printf 'image = "%s"\ncpu = 1\nmemory = "256Mi"\n' "$image" > kgate.toml
git add kgate.toml
git -c user.name=proof -c user.email=proof@example.invalid commit -q -m proof
ADDRS="$addrs" python3 - <<'PY'
import glob, os, re, subprocess, sys, threading, time
addrs = os.environ["ADDRS"].split()
folders = set()
def ps():
    procs = {}
    for line in subprocess.run(["ps", "-eo", "pid=,ppid=,args="], capture_output=True, text=True).stdout.splitlines():
        pid, ppid, args = line.split(None, 2)
        procs[int(pid)] = (int(ppid), args)
    return procs
def conns(root):
    procs = ps()
    mine = {root}
    grew = True
    while grew:
        grew = False
        for pid, (ppid, _) in procs.items():
            if ppid in mine and pid not in mine:
                mine.add(pid); grew = True
    for p, (_, a) in procs.items():   # ssh retitles its master "ssh: /tmp/kgate-mux-XXXX/<hash> [mux]"
        m = a.startswith("ssh") and re.search(r"(/tmp/kgate-mux-[^/ ]+)/", a)
        if m:
            folders.add(m.group(1)); mine.add(p)
    out = subprocess.run(["ss", "-tnpH", "state", "established"] + sum([["dst" if i == 0 else "or", "%s:22" % a] if i == 0 else ["or", "dst", "%s:22" % a] for i, a in enumerate(addrs)], []),
                         capture_output=True, text=True).stdout
    return {l.split()[2] for l in out.splitlines() if (m := re.search(r"pid=(\d+)", l)) and int(m.group(1)) in mine}
for label, argv in (("waiting job (exit 75 expected)", ["kgate", "--sched-wait", "15", "--node", "no-such-node", "--", "true"]),
                    ("running job (exit 0 expected)", ["kgate", "--", "sh", "-c", "sleep 8; echo hello"])):
    folders.clear()
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out = []
    threading.Thread(target=lambda: out.extend(proc.stdout), daemon=True).start()
    peak, seen = 0, set()
    while proc.poll() is None:
        c = conns(proc.pid); peak = max(peak, len(c)); seen |= c
        time.sleep(0.1)
    time.sleep(1.5)
    left = [a for _, (_, a) in ps().items() if a.startswith("ssh") and any(f in a for f in folders)]
    print("%s: exit=%d peak_simultaneous=%d connections_opened=%d" % (label, proc.returncode, peak, len(seen)))
    print("  mux folders %s; ssh masters left=%d, folders still there=%d" % (sorted(folders) or "NONE (old client)", len(left), sum(os.path.exists(f) for f in folders)))
PY
