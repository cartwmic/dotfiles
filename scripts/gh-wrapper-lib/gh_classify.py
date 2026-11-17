"""Which GitHub rate-limit bucket a gh command spends, and whether it is a read or a write. Pure functions: no I/O, no environment.

The wrapper (scripts/gh-wrapper) parses the command line and passes the facts in; this module only maps them, so any other gh caller can use it too.
docs/gh-wrapper.md has the table in words.

Buckets: "core" (REST), "graphql", "search", "free" (`gh api rate_limit` costs nothing). A command this table does not cover is "core". A command
is a read only when the caller says so; the wrapper does for the commands in its READ table, so everything else, unknown commands included, counts as a
write, and a layer that refuses reads never refuses a command it cannot tell.
"""
import re
from collections import namedtuple

Classification = namedtuple("Classification", "klass bucket write")

# `gh <group> <verb>` commands whose API calls were measured (GH_DEBUG=api on 2026-11-16): the bucket they spend. Every command not named here is
# "core", `pr diff` included (it spends one GraphQL and one REST call).
GRAPHQL = {("pr", "view"), ("pr", "list"), ("pr", "checks"), ("pr", "status")}
GRAPHQL_GROUPS = {"issue"}
SEARCH_GROUPS = {"search"}

SAFE_NAME = re.compile(r"^[a-z][a-z-]*$")


def mask_path(path):
    """An API path with the ids and shas in it as `*`: numbers, and 7 to 40 hex digits holding at least one digit. The query string goes."""
    parts = path.split("?", 1)[0].strip("/").split("/")
    return "/".join("*" if re.fullmatch(r"\d+|(?=[0-9a-f]*\d)[0-9a-f]{7,40}", p) else p for p in parts)


def classify_api(method, path, mutation):
    """`gh api`. method: the HTTP method gh will use, upper case. path: the endpoint without host or leading slash. mutation: for GraphQL, True / False
    when the query text is known to be / not be a mutation, None when it cannot be told (a query read from a file or from --input)."""
    path = path.split("?", 1)[0].strip("/")
    if path in ("graphql", "api/graphql"):
        return Classification("api POST graphql", "graphql", mutation is not False)
    bucket = "free" if path == "rate_limit" else "search" if path == "search" or path.startswith("search/") else "core"
    return Classification("api %s %s" % (method, mask_path(path)), bucket, method not in ("GET", "HEAD"))


def classify(name, read, api=None):
    """name: the wrapper's command name: `<group> <verb>`, a bare group, `api` or `unrecognised`. read: the command only reads (the wrapper's READ
    table, and `search`); for `api` the facts decide instead. api: the facts for classify_api, as a tuple (method, path, mutation), or None when the
    arguments could not be read."""
    if name == "api":
        return classify_api(*api) if api else Classification("api", "core", True)
    group, _, verb = name.partition(" ")
    if group == "unrecognised" or not SAFE_NAME.match(group):
        return Classification("unrecognised", "core", True)
    bucket = "graphql" if (group, verb) in GRAPHQL or group in GRAPHQL_GROUPS else "search" if group in SEARCH_GROUPS else "core"
    return Classification(name, bucket, not read)
