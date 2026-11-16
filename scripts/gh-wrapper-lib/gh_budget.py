"""The budget guard of the gh wrapper: refuse a read that is not urgent when its GitHub rate-limit bucket is nearly empty. docs/gh-wrapper.md.

A layer for lib/gh_layers.py: `before(call)` raises Stop(75, message) or lets the call go. It never waits and never edits the call.

Which bucket a call spends, and whether it is a read, come from gh_classify (call.bucket, call.write). The guard acts only on a read of "core" or "graphql":
  - a write always passes, and so does any call with GH_URGENT=1 in its environment;
  - "free" (`gh api rate_limit`) and "search" are never refused;
  - a host other than github.com is skipped;
  - the bucket's `remaining` comes from `gh api rate_limit` (free), run through the real gh and cached 30 s in <state>/gh-wrapper/rate.json. If that read fails,
    or takes over 3 s, the call goes on: a guard that stops work when it is blind makes an outage worse.

GH_BUDGET_FLOOR=<n> sets the floor (default 600, 12% of the 5000 an hour). The layer leaves facts for the log layer in call.notes:
  urgent       "write" | "env" | "no"
  budget       "ok" | "refused" | "unread" | "skip" (not github.com) | "unchecked" (nothing to check)
  budget_left  the bucket's remaining calls, when this call knew them (a fresh cache entry counts; the layer reads the network only when it must decide)
"""
import hashlib
import json
import os
import subprocess
import time

from gh_layers import Stop

DEFAULT_FLOOR = 600
EXIT_REFUSED = 75          # EX_TEMPFAIL: try again later
CACHE_SECONDS = 30
READ_TIMEOUT = 3
GUARDED_BUCKETS = ("core", "graphql")
MARK = b"gh wrapper (managed by chezmoi"      # the wrapper's own mark; also matches the leak-guard one it replaced
HOST = "github.com"


# ---- the decision: no I/O ------------------------------------------------------------------------------------------------------------------------------

def urgency(write, environ):
    """Why a call is urgent: it is a write, or its environment says so. A write is not counted as an urgent read."""
    if write:
        return "write"
    return "env" if environ.get("GH_URGENT", "").lower() in ("1", "true", "yes") else "no"


def floor_from(environ):
    try:
        return max(0, int(environ.get("GH_BUDGET_FLOOR", "")))
    except ValueError:
        return DEFAULT_FLOOR


def bucket_state(resources, bucket):
    """(remaining, limit, reset) of a bucket from the `resources` of `gh api rate_limit`, or None when it is not there in the shape we expect."""
    try:
        b = resources[bucket]
        return int(b["remaining"]), int(b["limit"]), int(b["reset"])
    except (KeyError, TypeError, ValueError):
        return None


def message(bucket, klass, remaining, limit, floor, reset, now):
    """The one refusal line."""
    left = max(0, int(reset - now))
    wait = "in under a minute" if left < 60 else "in %dm" % -(-left // 60)
    return ('gh-wrapper: %s budget low: %d left of %d (floor %d), resets %s %s. Refused "%s" (not urgent). If this is a merge, deploy, workflow run or '
            'merge-gate read, run it with GH_URGENT=1; otherwise wait for the reset or use a cheaper read.'
            % (bucket, remaining, limit, floor, time.strftime("%H:%M %Z", time.localtime(reset)), wait, klass))


# ---- the edge: the cache and the rate read -------------------------------------------------------------------------------------------------------------

def cache_path(environ):
    state = environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return os.path.join(state, "gh-wrapper", "rate.json")


def cache_key(host, environ):
    """Host plus a hash of the token, so two accounts do not share an answer. The token itself is never written."""
    token = environ.get("GH_TOKEN") or environ.get("GITHUB_TOKEN") or ""
    return hashlib.sha256(("%s\0%s" % (host, token)).encode()).hexdigest()[:24]


def load_cache(path):
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def fresh(entry, now):
    return isinstance(entry, dict) and isinstance(entry.get("at"), (int, float)) and 0 <= now - entry["at"] < CACHE_SECONDS


def store(path, key, entry, cache, now):
    """Write the entry by temp file and rename. Entries older than an hour go. A failure to write is not a failure of the call."""
    cache = {k: v for k, v in cache.items() if isinstance(v, dict) and isinstance(v.get("at"), (int, float)) and now - v["at"] < 3600}
    cache[key] = entry
    tmp = "%s.%d.tmp" % (path, os.getpid())
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w") as f:
            json.dump(cache, f)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def real_gh(environ):
    """The first gh on PATH that is not this wrapper (the file carries the mark)."""
    for d in environ.get("PATH", "").split(os.pathsep):
        cand = os.path.join(d or ".", "gh")
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            try:
                with open(cand, "rb") as f:
                    if MARK in f.read(4096):
                        continue
            except OSError:
                continue
            return cand
    return None


def read_rates(environ):
    """`gh api rate_limit` through the real gh: the `resources` dict, or None when it could not be read in time."""
    real = real_gh(environ)
    if real is None:
        return None
    try:
        done = subprocess.run([real, "api", "rate_limit", "--hostname", HOST], capture_output=True, text=True, timeout=READ_TIMEOUT, stdin=subprocess.DEVNULL,
                              env=dict(environ, GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1"))
        if done.returncode != 0:
            return None
        resources = json.loads(done.stdout)["resources"]
        return resources if isinstance(resources, dict) else None
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return None


def rates(environ, now, fetch=True):
    """The buckets from the cache while it is under 30 s old, else (when `fetch`) from GitHub. None when unread; a failed read is cached too, so an outage
    costs one wait of up to 3 s per half minute and not one per call."""
    path, key = cache_path(environ), cache_key(HOST, environ)
    cache = load_cache(path)
    entry = cache.get(key)
    if fresh(entry, now):
        return entry.get("resources")
    if not fetch:
        return None
    resources = read_rates(environ)
    store(path, key, {"at": now, "resources": resources}, cache, now)
    return resources


# ---- the layer ----------------------------------------------------------------------------------------------------------------------------------------

def github_com(call, environ):
    host = environ.get("GH_HOST", "").strip().lower()
    if call.args[:1] == ["api"] and "--hostname" in call.args:
        i = call.args.index("--hostname")
        host = call.args[i + 1].lower() if i + 1 < len(call.args) else host
    return host in ("", HOST)


def before(call):
    environ = os.environ
    call.notes["urgent"] = urgent = urgency(call.write, environ)
    if not github_com(call, environ):
        call.notes["budget"] = "skip"
        return
    must_decide = urgent == "no" and call.bucket in GUARDED_BUCKETS
    now = time.time()
    resources = rates(environ, now, fetch=must_decide)
    state = bucket_state(resources, call.bucket) if resources else None
    if state:
        call.notes["budget_left"] = state[0]
    if not must_decide:
        call.notes["budget"] = "unchecked"
        return
    if state is None:
        call.notes["budget"] = "unread"      # fail open
        return
    remaining, limit, reset = state
    floor = floor_from(environ)
    if remaining >= floor:
        call.notes["budget"] = "ok"
        return
    call.notes["budget"] = "refused"
    raise Stop(EXIT_REFUSED, message(call.bucket, call.klass, remaining, limit, floor, reset, now))
