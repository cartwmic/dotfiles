"""The layer seam of the gh wrapper: the optional steps that run around a gh call. docs/gh-wrapper.md.

A layer is a module in this directory. Adding one is adding the file: the names below are the order, and a name with no file is skipped. Each layer
may define either hook, both taking the `Call`:

    before(call)   runs before gh, in LAYERS order. It may change call.args, set call.action / call.rewrite, or raise Stop(rc, message) to refuse the call.
    after(call)    runs once after the call ends, whatever the outcome (call.rc is set): gh's own, a Stop, or a leak-guard block. It runs in reverse
                   order.

A layer's own exception never changes the call: it is reported on standard error and the call goes on. A Stop does, since it is the layer's decision.
"""
import importlib
import os
import sys
import time

LAYERS = ("gh_policy", "gh_rewrite", "gh_budget", "gh_log")
# The layers that run when the budget file says off (the work Mac, docs/gh-wrapper.md). gh_rewrite is one: its watch-interval default runs on every profile,
# and it reads call.budget_on for the rest. gh_policy is the other: it has its own switch (~/.config/gh-wrapper/policy), not the budget file's. The rest run
# only when the budget file says on.
ALWAYS = ("gh_policy", "gh_rewrite")


class Stop(Exception):
    """A layer refuses the call: `message` goes to standard error and the wrapper exits `rc` without running gh."""

    def __init__(self, rc, message):
        super().__init__(message)
        self.rc, self.message = rc, message


class Call:
    """One gh call as the layers see it. `args` are the arguments after `gh`; `klass`, `bucket` and `write` come from gh_classify. `budget_on` is whether
    ~/.config/gh-wrapper/budget says on, which the wrapper reads once for every call. `parsed` is the call's flags as the wrapper read them, for the commands
    it parses for the layers (FOR_LAYERS in the wrapper): ([(long name, value or None)], [positional arguments]) of the arguments after the group, or None
    when the command is not one of them or its flags could not be read. A layer reads flags from here and keeps no flag table of its own. `real` is the
    real gh, for a layer that must read state from GitHub."""

    def __init__(self, args, classification, budget_on=False, parsed=None, real=None):
        self.args = list(args)
        self.klass, self.bucket, self.write = classification
        self.budget_on = budget_on
        self.parsed = parsed
        self.real = real
        self.id = os.getpid()
        self.t0 = time.time()
        self.action = "pass"      # pass | rewrite | refused | exempt
        self.rewrite = None
        self.rc = None
        self.notes = {}      # anything a layer wants a later layer to log


def load(names=LAYERS):
    """The layer modules that exist, in order: `names`, by default all of them."""
    found = []
    for name in names:
        try:
            found.append(importlib.import_module(name))
        except ModuleNotFoundError as e:
            if e.name != name:
                warn(name, e)
        except Exception as e:
            warn(name, e)
    return found


def warn(name, error):
    print("gh-wrapper: layer %s failed (%s: %s); the call goes on" % (name, type(error).__name__, error), file=sys.stderr)


def wants_exit(layers):
    """True when a layer has an `after` hook, so the wrapper must wait for gh instead of replacing itself with it."""
    return any(hasattr(m, "after") for m in layers)


def before(layers, call):
    """Run the `before` hooks. Returns the Stop that ended them, or None."""
    for m in layers:
        if hasattr(m, "before"):
            try:
                m.before(call)
            except Stop as stop:
                call.action = "refused"
                return stop
            except Exception as e:
                warn(m.__name__, e)
    return None


def after(layers, call, rc):
    call.rc = rc
    for m in reversed(layers):
        if hasattr(m, "after"):
            try:
                m.after(call)
            except Exception as e:
                warn(m.__name__, e)
