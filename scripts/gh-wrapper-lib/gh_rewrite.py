"""Cheaper by default: the rewrites the gh wrapper makes to a call the caller did not ask to change. docs/gh-wrapper.md, "Cheaper by default".

- `gh run watch` with no -i/--interval gets `--interval 60`. Each poll is about 4 REST calls, so gh's default of 3 seconds costs about 55 calls a minute.
- `gh pr checks --watch` with no -i/--interval gets `--interval 60` (gh's default is 10; each poll is GraphQL).
- A non-urgent `gh api` GET read on the core or search bucket gets `--cache 15s`. Not: a call that names another method, sends fields or a body, already has
  --cache, or asks for help. `api rate_limit` (free) and GraphQL (`api POST graphql` in gh_classify) are never touched. GH_URGENT=1 keeps a read fresh.

Profiles: the two watch defaults run wherever the wrapper runs, the work Mac included. The `gh api` cache runs only where the budget file says on (personal).
The wrapper loads this layer on every profile (gh_layers.ALWAYS) and passes it call.budget_on.

A caller-set interval is honoured, never clamped. A call whose flags cannot be read (an unknown flag, a value flag with no value) is left as it is.

`plan` is pure: the arguments in, the arguments out. `before` is the layer hook: it reads GH_URGENT and edits the call. What it exposes for the log layer is
call.action "rewrite" and call.rewrite ("interval 60", "cache 15s") when it changed the call, and call.notes["interval"] on every watch call: the interval
gh polls at, the caller's own or the default, an int when it is a number.
"""
import os

WATCH_INTERVAL = 60     # seconds, for a watch the caller did not time
API_CACHE = "15s"       # the gh api cache time for a non-urgent read
TRUE_VALUES = {"1", "t", "T", "TRUE", "true", "True"}      # what gh's flag library (strconv.ParseBool) reads as true

# The flags each command reads, in the wrapper's FLAGS format (scripts/gh-wrapper): "s:long" is a short and a long flag, a trailing "=" means the flag takes
# a value. From `gh <command> --help` at gh 2.103.3. The api row is the wrapper's own, and tests/leak-guard/test_gh_rewrite.py keeps the two equal.
RUN_WATCH = "R:repo=,h:help,i:interval=,compact,exit-status"
PR_CHECKS = "R:repo=,h:help,i:interval=,q:jq=,json=,t:template=,w:web,fail-fast,required,watch"
API = ("allow-escape-sequences,cache=,F:field=,H:header=,hostname=,i:include,input=,q:jq=,X:method=,paginate,p:preview=,f:raw-field=,silent,slurp,"
       "t:template=,verbose,h:help")


def table(spec):
    """({long name: takes a value}, {letter: long name}) of a FLAGS-format spec."""
    longs, shorts = {}, {}
    for item in spec.split(","):
        short, _, rest = item.rpartition(":")
        longs[rest.rstrip("=")] = rest.endswith("=")
        if short:
            shorts[short] = rest.rstrip("=")
    return longs, shorts


def read_flags(args, spec):
    """(flags, positionals): flags is [(long name, value or None)] in order, positionals are the other arguments (all of them after a bare `--`). None when
    a flag is not in the spec, or a value flag has no value. A value flag takes the next argument whatever it looks like, as gh does; a short flag cluster
    ends at a value flag, so the rest of that argument is its value (`-Rcartwmic/x` is -R with a value, not -c, -a, ...)."""
    longs, shorts = table(spec)
    flags, positionals, i = [], [], 0
    while i < len(args):
        a = args[i]
        if a == "--":
            return flags, positionals + args[i + 1:]
        if a.startswith("--"):
            name, eq, val = a[2:].partition("=")
            if name not in longs:
                return None
            if longs[name] and not eq:
                if i + 1 >= len(args):
                    return None
                i += 1
                val = args[i]
            elif not eq:
                val = None
            flags.append((name, val))
        elif a.startswith("-") and len(a) > 1:
            j = 1
            while j < len(a):
                name = shorts.get(a[j])
                if name is None:
                    return None
                if longs[name]:
                    rest = a[j + 1:]
                    if rest:
                        val = rest[1:] if rest.startswith("=") else rest
                    elif i + 1 < len(args):
                        i += 1
                        val = args[i]
                    else:
                        return None
                    flags.append((name, val))
                    break
                flags.append((name, None))
                j += 1
        else:
            positionals.append(a)
        i += 1
    return flags, positionals


def insert(args, extra):
    """`args` with `extra` before a bare `--`, or at the end: a flag after `--` would be read as text."""
    at = args.index("--") if "--" in args else len(args)
    return args[:at] + extra + args[at:]


def interval_value(text):
    return int(text) if text.isdigit() else text


def watch(args, spec, switch):
    """A watch command: (args, rewrite, interval). `switch` is the flag that makes the command watch (`--watch` for pr checks); None when it always does."""
    read = read_flags(args[1:], spec)
    if read is None:
        return args, None, None
    flags, _ = read
    if switch:
        last = [val for name, val in flags if name == switch]
        if not last or (last[-1] is not None and last[-1] not in TRUE_VALUES):      # gh keeps the last value of a flag
            return args, None, None
    given = [val for name, val in flags if name == "interval"]
    if given:
        return args, None, interval_value(given[-1])
    return insert(args, ["--interval", str(WATCH_INTERVAL)]), "interval %d" % WATCH_INTERVAL, WATCH_INTERVAL


def cached(args, urgent):
    """A `gh api` GET read: (args, rewrite, None). Only a read that sends nothing, names no method but GET, has no cache of its own and is not urgent."""
    if urgent:
        return args, None, None
    read = read_flags(args[1:], API)
    if read is None:
        return args, None, None
    flags, positionals = read
    names = {name for name, _ in flags}
    methods = [val for name, val in flags if name == "method"]
    if not positionals or names & {"help", "field", "raw-field", "input", "cache"} or (methods and methods[-1].upper() != "GET"):
        return args, None, None
    return insert(args, ["--cache", API_CACHE]), "cache %s" % API_CACHE, None


def plan(klass, bucket, args, urgent, budget_on):
    """(args, rewrite, interval) for one gh call: the arguments gh should get, what was rewritten (None when nothing was), and for a watch the interval it
    polls at (None when the call is not a watch). `klass` and `bucket` are gh_classify's for the call. The watch default is on whatever the budget says;
    the cache only where the budget file says on."""
    if klass == "run watch":
        return watch(args, RUN_WATCH, None)
    if klass == "pr checks":
        return watch(args, PR_CHECKS, "watch")
    if budget_on and klass.startswith("api GET ") and bucket in ("core", "search"):      # `api rate_limit` is free and GraphQL is `api POST graphql`
        return cached(args, urgent)
    return args, None, None


def before(call):
    """The layer hook. Changes call.args when a rewrite applies, and exposes the rewrite and the watch interval for the log layer."""
    args, rewrite, interval = plan(call.klass, call.bucket, call.args, urgent=os.environ.get("GH_URGENT") == "1", budget_on=call.budget_on)
    if interval is not None:
        call.notes["interval"] = interval
    if rewrite is not None:
        call.args, call.rewrite, call.action = args, rewrite, "rewrite"
