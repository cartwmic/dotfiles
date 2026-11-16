"""Cheaper by default: the rewrites the gh wrapper makes to a call the caller did not ask to change. docs/gh-wrapper.md, "Cheaper by default".

- `gh run watch` with no -i/--interval gets `--interval 60`. Each poll is about 4 REST calls, so gh's default of 3 seconds costs about 64 calls a minute (measured).
- `gh pr checks --watch` with no -i/--interval gets `--interval 60` (gh's default is 10; each poll is GraphQL).
- A non-urgent `gh api` GET read on the core or search bucket gets `--cache 15s`. Not: a call that names another method, sends fields or a body, already has
  --cache, or asks for help. `api rate_limit` (free) and GraphQL (`api POST graphql` in gh_classify) are never touched. GH_URGENT=1 keeps a read fresh.

Profiles: the two watch defaults run wherever the wrapper runs, the work Mac included. The `gh api` cache runs only where the budget file says on (personal).
The wrapper loads this layer on every profile (gh_layers.ALWAYS) and passes it call.budget_on.

A caller-set interval is honoured, never clamped. A call whose flags cannot be read (an unknown flag, a value flag with no value) is left as it is.

The flags are not parsed here. The wrapper parses `run watch`, `pr checks` and `api` with its own FLAGS rows (scripts/gh-wrapper, FOR_LAYERS) and passes them
as call.parsed, so the rows are regenerated and compared with gh like every other and this layer keeps no flag table or parser.

`plan` is pure: the arguments in, the arguments out. `before` is the layer hook: it reads GH_URGENT and edits the call. What it exposes for the log layer is
call.action "rewrite" and call.rewrite ("interval 60", "cache 15s") when it changed the call, and call.notes["interval"] on every watch call: the interval
gh polls at, the caller's own or the default, an int when it is a number.
"""
import os

WATCH_INTERVAL = 60     # seconds, for a watch the caller did not time
API_CACHE = "15s"       # the gh api cache time for a non-urgent read
TRUE_VALUES = {"1", "t", "T", "TRUE", "true", "True"}      # what gh's flag library (strconv.ParseBool) reads as true


def insert(args, extra):
    """`args` with `extra` before a bare `--`, or at the end: a flag after `--` would be read as text."""
    at = args.index("--") if "--" in args else len(args)
    return args[:at] + extra + args[at:]


def interval_value(text):
    return int(text) if text.isdigit() else text


def watch(args, parsed, switch):
    """A watch command: (args, rewrite, interval). `switch` is the flag that makes the command watch (`--watch` for pr checks); None when it always does."""
    if parsed is None:
        return args, None, None
    flags, _ = parsed
    if switch:
        last = [val for name, val in flags if name == switch]
        if not last or (last[-1] is not None and last[-1] not in TRUE_VALUES):      # gh keeps the last value of a flag
            return args, None, None
    given = [val for name, val in flags if name == "interval"]
    if given:
        return args, None, interval_value(given[-1])
    return insert(args, ["--interval", str(WATCH_INTERVAL)]), "interval %d" % WATCH_INTERVAL, WATCH_INTERVAL


def cached(args, parsed, urgent):
    """A `gh api` GET read: (args, rewrite, None). Only a read that sends nothing, names no method but GET, has no cache of its own and is not urgent."""
    if urgent or parsed is None:
        return args, None, None
    flags, positionals = parsed
    names = {name for name, _ in flags}
    methods = [val for name, val in flags if name == "method"]
    if not positionals or names & {"help", "field", "raw-field", "input", "cache"} or (methods and methods[-1].upper() != "GET"):
        return args, None, None
    return insert(args, ["--cache", API_CACHE]), "cache %s" % API_CACHE, None


def plan(klass, bucket, args, parsed, urgent, budget_on):
    """(args, rewrite, interval) for one gh call: the arguments gh should get, what was rewritten (None when nothing was), and for a watch the interval it
    polls at (None when the call is not a watch). `klass` and `bucket` are gh_classify's for the call, `parsed` is the wrapper's
    read of its flags (Call.parsed). The watch default is on whatever the budget says; the cache only where the budget file says on."""
    if klass == "run watch":
        return watch(args, parsed, None)
    if klass == "pr checks":
        return watch(args, parsed, "watch")
    if budget_on and klass.startswith("api GET ") and bucket in ("core", "search"):      # `api rate_limit` is free and GraphQL is `api POST graphql`
        return cached(args, parsed, urgent)
    return args, None, None


def before(call):
    """The layer hook. Changes call.args when a rewrite applies, and exposes the rewrite and the watch interval for the log layer."""
    args, rewrite, interval = plan(call.klass, call.bucket, call.args, call.parsed, urgent=os.environ.get("GH_URGENT") == "1", budget_on=call.budget_on)
    if interval is not None:
        call.notes["interval"] = interval
    if rewrite is not None:
        call.args, call.rewrite, call.action = args, rewrite, "rewrite"
