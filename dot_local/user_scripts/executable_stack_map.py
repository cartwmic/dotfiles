#!/usr/bin/env python3
"""Build the agent stack map: one self-contained HTML page that explains how dotfiles, the coordinator, agent-kit and Loop Engine fit together.

    stack_map.py --out PAGE.html [--fetch] [--repos-root DIR] [--content FILE] [--facts-json]

The script reads each repository at `origin/main` with `git show` and `git ls-tree`, never the working tree. Facts (versions, pins, seats,
providers, skills, setup scripts, coordinator tables, agent-kit exports, Loop Engine crates) are parsed from files and drawn with the line
they came from. The plain-English text is docs/stack-map/content.md (dotfiles, origin/main, or --content FILE); its citations
`[[repo:path:LINE|snippet]]` are checked against the files and its ```flow block is drawn as a diagram.

Exit 0 only when every extractor found what it expects and every citation holds. Otherwise exit 1, nothing is written, and each failure is
printed as `repo:path:line: reason` (line 0 when no line applies). The same commits always give the same bytes: no clock, no absolute paths.
Every run appends one JSON line to $STACK_MAP_LOG (default $XDG_STATE_HOME/stack-map/log.jsonl, default ~/.local/state).
"""

import argparse
import html
import json
import os
import re
import subprocess
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

REPOS = ("dotfiles", "coordinator", "agent-kit", "loop-engine")
GITHUB = "https://github.com/cartwmic/"
CONTENT_PATH = "docs/stack-map/content.md"
KIT_PACKAGE = "@cartwmic/agent-kit"
LE_ALIAS_VALUE = "github:cartwmic/loop-engine"
HARNESS = "dot_local/share/agent-harness"
# Dotfiles has no version file; every other repo must have one, so a lost version still fails the run.
VERSION_SOURCE = {"dotfiles": None, "coordinator": "package.json", "agent-kit": "package.json", "loop-engine": "Cargo.toml"}
# The state directory layout is documented, not computed: each entry is checked by finding its snippet in the named file.
STATE_LAYOUT = (
    ("config.json", "the daemon's settings (`coordinator config set`)", "coordinator", "src/config-file.ts", "'config.json'"),
    ("KILL", "present while the kill switch is on", "coordinator", "src/coordinatord/cli.ts", "$COORDINATOR_STATE_DIR/KILL"),
    ("pane-bin/", "wrapper commands (`ledger`, `coordinator`) the daemon writes for agent panes", "coordinator", "README.md", "<state>/pane-bin"),
    ("rank", "the priority stack of workstreams, published for other tools", "coordinator", "src/coordinatord/cli.ts", "<state dir>/rank"),
)
# The sections content.md must have, found by words in their `##` headings, in the order the page shows them.
SECTIONS = (
    ("start", "Start here", ("start here",)),
    ("picture", "The one-minute picture", ("one-minute", "one minute")),
    ("repos", "What each repository is for", ("repo",)),
    ("flow", "How a piece of work moves", ("moves", "flow")),
    ("change", "Where do I change X?", ("where do i change", "change x")),
    ("glossary", "Glossary", ("glossary",)),
)

CITE = re.compile(r"\[\[([A-Za-z0-9_-]+):([^:\]|]+):(\d+)(?:-(\d+))?\|(.+?)\]\]")
CODE_SPAN = re.compile(r"`([^`]+)`")


class Failures:
    """Every failure of a run, as `repo:path:line: reason`, each once."""

    def __init__(self):
        self.items = []

    def add(self, repo, path, line, reason):
        item = "%s:%s:%s: %s" % (repo, path, line, reason)
        if item not in self.items:
            self.items.append(item)


class Repo:
    """One repository read at the commit origin/main named when the run started."""

    def __init__(self, name, root, fail):
        self.name, self.root, self.fail = name, root, fail
        self._shown = {}
        self.sha = (self.git("rev-parse", "--verify", "-q", "origin/main^{commit}") or "").strip()
        if not self.sha:
            fail.add(name, "origin/main", 0, "no origin/main in this repository (looked in %s)" % root)
            self.date = ""
            return
        self.date = (self.git("show", "-s", "--format=%cI", self.sha) or "").strip()[:10]

    def git(self, *args):
        try:
            done = subprocess.run(["git", "-C", str(self.root), *args], capture_output=True, text=True, encoding="utf-8", env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
        except OSError:
            return None
        return done.stdout if done.returncode == 0 else None

    def show(self, path):
        if path not in self._shown:
            self._shown[path] = self.git("show", "%s:%s" % (self.sha, path)) if self.sha else None
        return self._shown[path]

    def need(self, path):
        """The file's text, or a failure `repo:path:0: missing` and None."""
        text = self.show(path)
        if text is None:
            self.fail.add(self.name, path, 0, "missing at origin/main")
        return text

    def ls(self, directory=""):
        """[(type, name)] directly under the directory (`blob` or `tree`), in git's order."""
        out = self.git("ls-tree", "-z", self.sha, *([directory + "/"] if directory else [])) if self.sha else None
        found = []
        for entry in (out or "").split("\0"):
            if entry:
                meta, name = entry.split("\t", 1)
                found.append((meta.split()[1], name.rsplit("/", 1)[-1]))
        return found

    def exists(self, path):
        return bool(self.sha) and self.git("cat-file", "-e", "%s:%s" % (self.sha, path)) is not None

    def url(self, path, line=None, tree=False):
        return "%s%s/%s/%s/%s%s" % (GITHUB, self.name, "tree" if tree else "blob", self.sha, path, "#L%d" % line if line else "")

    def commit_url(self):
        return "%s%s/commit/%s" % (GITHUB, self.name, self.sha)

    def cite(self, path, line):
        """A superscript link `repo path:LINE` to the file at this commit."""
        return '<sup class="cite"><a href="%s">%s %s:%d</a></sup>' % (self.url(path, line), self.name, esc(path), line)


def esc(text):
    return html.escape(str(text), quote=True)


def line_of(text, pattern, start=0):
    """1-based number of the first line from `start` (0-based index) that has the regex `pattern`, or None."""
    rx = re.compile(pattern)
    for index, line in enumerate(text.split("\n")[start:], start):
        if rx.search(line):
            return index + 1
    return None


def locate(repo, text, path, snippet, label):
    """The line of `path` that holds the literal snippet; a failure naming `label` when none does."""
    number = line_of(text, re.escape(snippet))
    if number is None:
        repo.fail.add(repo.name, path, 0, "expected %s: %r not found" % (label, snippet))
        return 0
    return number


def plain(text):
    """Markdown text without its marks: links keep their words, code and bold lose their marks."""
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return re.sub(r"[`*]", "", text).strip()


# --- fact extractors: each returns plain data, every fact with the line it came from -------------------------------------------------


def first_sentence(text):
    """The first sentence of the first prose paragraph of a markdown file, and its 1-based line ((\"\", 0) when there is no prose)."""
    rows, start = [], 0
    for index, line in enumerate(text.split("\n")):
        if re.match(r"^(\s*$|#|\||[-*>]|<|```|\[!|!\[|\d+\.\s)", line):
            if rows:
                break
            continue
        if not rows:
            start = index + 1
        rows.append(line.strip())
    if not rows:
        return "", 0
    sentence = re.split(r"(?<=[.!?])\s", plain(" ".join(rows)))[0]
    return (sentence if len(sentence) <= 300 else sentence[:297].rsplit(" ", 1)[0] + "..."), start


def purpose_of(repo):
    text = repo.need("README.md")
    sentence, line = first_sentence(text) if text is not None else ("", 0)
    if text is not None and not sentence:
        repo.fail.add(repo.name, "README.md", 0, "no prose paragraph found for the one-line purpose")
    return {"text": sentence, "line": line}


def version_of(repo):
    source = VERSION_SOURCE[repo.name]
    if source is None:
        return {"text": "no version file; identified by commit", "path": "", "line": 0}
    text = repo.need(source)
    if text is None:
        return {"text": "", "path": source, "line": 0}
    try:
        if source == "package.json":
            version = json.loads(text)["version"]
            line = line_of(text, r'"version"\s*:')
        else:
            version = tomllib.loads(text)["workspace"]["package"]["version"]
            line = line_of(text, r"^version\s*=", (line_of(text, r"^\[workspace\.package\]") or 1) - 1)
    except (ValueError, KeyError, TypeError) as error:
        repo.fail.add(repo.name, source, 0, "no version found (%s)" % error)
        return {"text": "", "path": source, "line": 0}
    return {"text": str(version), "path": source, "line": line or 0}


def extract_repo_cards(repos):
    return {name: {"sha": repo.sha[:7], "date": repo.date, "version": version_of(repo), "purpose": purpose_of(repo)} for name, repo in repos.items()}


def kit_pin(repo, path):
    text = repo.need(path)
    if text is None:
        return {"repo": repo.name, "path": path, "line": 0, "version": ""}
    try:
        version = json.loads(text)["dependencies"][KIT_PACKAGE]
    except (ValueError, KeyError, TypeError):
        repo.fail.add(repo.name, path, 0, "no dependency on %s" % KIT_PACKAGE)
        return {"repo": repo.name, "path": path, "line": 0, "version": ""}
    return {"repo": repo.name, "path": path, "line": line_of(text, re.escape('"%s"' % KIT_PACKAGE)) or 0, "version": version}


def extract_pins(repos, cards):
    dot = repos["dotfiles"]
    kit = [kit_pin(repos["coordinator"], "package.json"), kit_pin(dot, "dot_local/share/agent-kit/package.json")]
    kit_now = cards["agent-kit"]["version"]["text"]
    tools = []
    path = "dot_config/mise/config.toml"
    text = dot.need(path)
    if text is not None:
        try:
            data = tomllib.loads(text)
        except ValueError as error:
            dot.fail.add("dotfiles", path, 0, "not valid TOML (%s)" % error)
            data = {}
        names = sorted(name for name, target in data.get("tool_alias", {}).items() if target == LE_ALIAS_VALUE)
        if not names:
            dot.fail.add("dotfiles", path, 0, "no [tool_alias] entry points at %s" % LE_ALIAS_VALUE)
        start = (line_of(text, r"^\[tools\]") or 1) - 1
        for name in names:
            entry = data.get("tools", {}).get(name)
            version = entry.get("version") if isinstance(entry, dict) else entry
            line = line_of(text, r"^%s\s*=" % re.escape(name), start)
            if not version or not line:
                dot.fail.add("dotfiles", path, 0, "no [tools] pin for the Loop Engine tool %s" % name)
                continue
            tools.append({"name": name, "version": str(version), "line": line})
    le_now = cards["loop-engine"]["version"]["text"]
    kit_versions = {pin["version"] for pin in kit}
    le_versions = {tool["version"] for tool in tools}
    return {
        "agent_kit": {"pins": kit, "main": kit_now, "pins_agree": len(kit_versions) == 1, "behind_main": kit_versions != {kit_now}},
        "loop_engine": {"path": path, "tools": tools, "main": le_now, "pins_agree": len(le_versions) <= 1, "behind_main": le_versions != {le_now}},
    }


def table_rows(lines, start):
    """The cells of each table row after the header and separator, with the 1-based line, from the table that starts at `start` (0-based)."""
    rows = []
    for index in range(start + 2, len(lines)):
        if not lines[index].startswith("|"):
            break
        rows.append(([cell.strip() for cell in lines[index].strip().strip("|").split("|")], index + 1))
    return rows


def parse_dicts(line):
    """The `(dict "k" v "k" v)` groups of one Go template line, as dicts of str and bool."""
    out = []
    for body in re.findall(r"\(dict\s+([^()]*)\)", line):
        tokens = re.findall(r'"[^"]*"|[^\s"]+', body)
        pairs = {}
        for key, value in zip(tokens[0::2], tokens[1::2]):
            pairs[key.strip('"')] = {"true": True, "false": False}.get(value, value.strip('"'))
        out.append(pairs)
    return out


def extract_seats(repos):
    dot = repos["dotfiles"]
    path = HARNESS + "/canonical/instructions/profile-personal.md"
    seats, text = [], dot.need(path)
    if text is not None:
        lines = text.split("\n")
        head = next((i for i, line in enumerate(lines) if line.strip() == "## Agent seats and models"), None)
        table = None if head is None else next((i for i in range(head, len(lines)) if lines[i].startswith("| Seat")), None)
        if table is None:
            dot.fail.add("dotfiles", path, 0, "no `## Agent seats and models` section with a Seat | Model table")
        else:
            seats = [{"seat": cells[0], "model": cells[1], "line": number} for cells, number in table_rows(lines, table) if len(cells) >= 2]
        if not seats:
            dot.fail.add("dotfiles", path, 0, "the seats table has no rows")
    t3_path = "dot_t3/private_userdata/modify_settings.json.tmpl"
    instances, t3 = [], dot.need(t3_path)
    if t3 is not None:
        lines = t3.split("\n")
        owned = []
        for number, line in enumerate(lines, 1):
            if "$seats" in line and "(dict" in line:
                for seat in parse_dicts(line):
                    if "id" not in seat or "window" not in seat:
                        dot.fail.add("dotfiles", t3_path, number, "a seat entry has no id or window")
                        continue
                    instances.append({"id": "seat-" + seat["id"], "window": seat["window"], "advisor": seat.get("advisor", True), "helpers_on_haiku": bool(seat.get("subagent")),
                                      "five_minute_cache": bool(seat.get("cache5m")), "mcp_file": seat.get("mcp", ""), "line": number})
            if "$owned" in line and ('list "' in line or "append" in line):
                owned += [(name, number) for name in re.findall(r'"([a-z][a-z0-9-]*)"', line)]
        for name, number in owned:
            instances.append({"id": name, "window": "", "advisor": None, "helpers_on_haiku": False, "five_minute_cache": False, "mcp_file": "", "line": number})
        if not any(item["id"].startswith("seat-") for item in instances):
            dot.fail.add("dotfiles", t3_path, 0, "no $seats entries found")
    return {"table": {"path": path, "rows": seats}, "t3": {"path": t3_path, "instances": instances}}


def extract_providers(repos):
    dot = repos["dotfiles"]
    pi_path, mcp_path = "dot_pi/private_agent/private_models.json.tmpl", HARNESS + "/canonical/mcp/servers.json.tmpl"
    providers, text = [], dot.need(pi_path)
    if text is not None:
        gate = ""
        for number, line in enumerate(text.split("\n"), 1):
            cond = re.match(r'^\{\{-? if eq \.profile "([a-z-]+)" \}\}', line)
            if cond:
                gate = cond.group(1)
            elif re.match(r"^\{\{-? if \$\w+ \}\}", line):
                gate = "work, when local data is set"
            elif re.match(r"^\{\{-? end\b", line):
                gate = ""
            head = re.match(r'^    "([a-z0-9-]+)": (\{|\{\{)', line)
            if head:
                providers.append({"name": head.group(1), "profile": gate or "both", "models": [], "line": number})
            elif providers:
                for model in re.findall(r'"id":\s*"([^"{}]+)"', line):
                    providers[-1]["models"].append(model)
        if not providers or not any(p["models"] for p in providers):
            dot.fail.add("dotfiles", pi_path, 0, "no Pi providers with model ids found")
    servers, mcp = [], dot.need(mcp_path)
    if mcp is not None:
        servers = [{"name": m.group(1), "line": number} for number, line in enumerate(mcp.split("\n"), 1) for m in [re.match(r'^    "([^"]+)": \{', line)] if m]
        if not servers:
            dot.fail.add("dotfiles", mcp_path, 0, "no MCP servers found")
    return {"pi": {"path": pi_path, "providers": providers}, "mcp": {"path": mcp_path, "servers": servers}}


def extract_harness(repos):
    dot = repos["dotfiles"]
    out = {}
    for key, rel, want in (("skills", "canonical/skills", "tree"), ("hooks", "hooks", "blob"), ("adapters", "adapters", "tree"), ("instructions", "canonical/instructions", "blob")):
        out[key] = {"path": "%s/%s" % (HARNESS, rel), "names": [name for kind, name in dot.ls("%s/%s" % (HARNESS, rel)) if kind == want]}
        if not out[key]["names"]:
            dot.fail.add("dotfiles", out[key]["path"], 0, "no %s found" % key)
    out["cursor"] = dot.exists("dot_cursor")
    if not out["cursor"]:
        dot.fail.add("dotfiles", "dot_cursor", 0, "missing at origin/main (Cursor projection)")
    text = dot.need("AGENTS.md")
    out["profiles"] = {"path": "AGENTS.md", "names": [], "line": 0}
    if text is not None:
        line = line_of(text, r"^Profiles \(")
        if line is None:
            dot.fail.add("dotfiles", "AGENTS.md", 0, "no `Profiles (` line naming the profiles")
        else:
            paragraph = re.split(r"\n\s*\n", "\n".join(text.split("\n")[line - 1:]))[0]
            out["profiles"] = {"path": "AGENTS.md", "line": line, "names": list(dict.fromkeys(re.findall(r"`([a-z-]+)`", paragraph.split("):", 1)[-1])))}
    return out


def setup_script_line(text, name):
    for line in text.split("\n"):
        said = re.sub(r"^#+\s*", "", line).strip()
        if line.startswith("#") and not line.startswith("#!") and not re.match(r"#\s*(shellcheck|vim|-\*-)", line) and re.search(r"[A-Za-z]", said):
            return plain(said)[:200]
    return name


def extract_setup_scripts(repos):
    dot = repos["dotfiles"]
    names = [name for kind, name in dot.ls() if kind == "blob" and name.startswith("run_")]

    def order(name):
        m = re.match(r"^run_(?:once_|onchange_)?(before|after)_(\d+)_", name)
        return (0 if m and m.group(1) == "before" else 1, int(m.group(2)) if m else 10**6, name)

    scripts = []
    for name in sorted(names, key=order):
        text = dot.show(name) or ""
        scripts.append({"name": name, "line": setup_script_line(text, name)})
    if not scripts:
        dot.fail.add("dotfiles", "", 0, "no run_* setup scripts at the repository root")
    return scripts


def extract_coordinator(repos):
    co = repos["coordinator"]
    out = {}
    readme = co.need("docs/README.md")
    components = []
    if readme is not None:
        line = line_of(readme, r"Module notes:")
        for text, link in re.findall(r"\[([^\]]+)\]\((\.\./[^)]+)\)", readme.split("\n")[line - 1] if line else ""):
            path = os.path.normpath(os.path.join("docs", link))
            body = co.show(path)
            if body is None:
                co.fail.add("coordinator", path, line or 0, "module note named in docs/README.md is missing at origin/main")
                continue
            components.append({"name": text, "path": path, "line": line, "about": first_sentence(body)[0]})
        if not components:
            co.fail.add("coordinator", "docs/README.md", 0, "no `Module notes:` links found")
    out["components"] = components
    book = co.need("playbook.md")
    rules = [tag or "untagged" for tag in re.findall(r"(?m)^## [0-9a-f]{8}(?: · (\w+))?\s*$", book or "")]
    out["playbook"] = {"path": "playbook.md", "rules": len(rules), "by_tag": {tag: rules.count(tag) for tag in sorted(set(rules))}}
    if book is not None and not rules:
        co.fail.add("coordinator", "playbook.md", 0, "no rule headings (`## <8 hex> · <tag>`) found")
    ledger = co.need("src/ledger/index.ts")
    tables = []
    for number, line in enumerate((ledger or "").split("\n"), 1):
        m = re.match(r'^CREATE TABLE IF NOT EXISTS (\w+) \(', line)
        if m and m.group(1) not in [t["name"] for t in tables]:
            tables.append({"name": m.group(1), "line": number})
    out["ledger_tables"] = {"path": "src/ledger/index.ts", "tables": tables}
    if ledger is not None and not tables:
        co.fail.add("coordinator", "src/ledger/index.ts", 0, "no CREATE TABLE statements found")
    config = co.need("src/coordinatord/config.ts")
    keys, start = [], line_of(config or "", r"^export const CONFIG_KEYS = \{")
    if config is not None:
        for line in config.split("\n")[start or 0:]:
            if re.match(r"^\}", line):
                break
            m = re.match(r"^  ([A-Za-z0-9_]+): \{", line)
            if m:
                keys.append(m.group(1))
        if not start or not keys:
            co.fail.add("coordinator", "src/coordinatord/config.ts", 0, "no CONFIG_KEYS table found")
    out["config_keys"] = {"path": "src/coordinatord/config.ts", "line": start or 0, "count": len(keys)}
    cli = co.need("src/coordinatord/cli.ts")
    commands = []
    for line in (cli or "").split("\n"):
        m = re.match(r"^//   coordinator ([a-z][a-z-]*)", line)
        if m and m.group(1) not in commands:
            commands.append(m.group(1))
    out["cli"] = {"path": "src/coordinatord/cli.ts", "commands": commands}
    if cli is not None and not commands:
        co.fail.add("coordinator", "src/coordinatord/cli.ts", 0, "no `// coordinator <command>` usage lines found")
    journeys = [name for kind, name in co.ls("scripts/journeys") if name.endswith(".journey.ts")]
    out["journeys"] = {"path": "scripts/journeys", "count": len(journeys)}
    if not journeys:
        co.fail.add("coordinator", "scripts/journeys", 0, "no *.journey.ts files found")
    prd = co.need("docs/PRD.md")
    reqs = len(re.findall(r"(?m)^### LE-", prd or ""))
    out["prd"] = {"path": "docs/PRD.md", "requirements": reqs}
    if prd is not None and not reqs:
        co.fail.add("coordinator", "docs/PRD.md", 0, "no `### LE-` requirement headings found")
    layout = []
    for name, about, repo_name, path, snippet in STATE_LAYOUT:
        body = co.need(path)
        layout.append({"name": name, "about": about, "path": path, "line": locate(co, body, path, snippet, "the state-dir entry %s" % name) if body is not None else 0})
    out["state_layout"] = layout
    if not co.exists("bookends.toml"):
        co.fail.add("coordinator", "bookends.toml", 0, "missing at origin/main (the coordinator's Bookends gate)")
    return out


def extract_kit_and_engine(repos):
    kit, le = repos["agent-kit"], repos["loop-engine"]
    out = {}
    text = kit.need("package.json")
    groups = {}
    if text is not None:
        try:
            exports = [key[2:] for key in json.loads(text)["exports"] if key != "."]
        except (ValueError, KeyError, TypeError):
            exports = []
        for sub in exports:
            groups.setdefault(sub.split("/")[0], []).append(sub)
        if not exports:
            kit.fail.add("agent-kit", "package.json", 0, "no `exports` subpaths found")
    out["agent_kit"] = {"path": "package.json", "line": line_of(text or "", r'"exports"\s*:') or 0, "groups": {key: groups[key] for key in sorted(groups)}}
    root = le.need("Cargo.toml")
    members = []
    if root is not None:
        try:
            names = tomllib.loads(root)["workspace"]["members"]
        except (ValueError, KeyError, TypeError):
            names = []
            le.fail.add("loop-engine", "Cargo.toml", 0, "no [workspace] members found")
        for member in names:
            bins = []
            body = le.need(member + "/Cargo.toml")
            if body is not None:
                try:
                    bins = [b["name"] for b in tomllib.loads(body).get("bin", [])]
                except ValueError as error:
                    le.fail.add("loop-engine", member + "/Cargo.toml", 0, "not valid TOML (%s)" % error)
            members.append({"path": member, "bins": bins})
        if not any(m["bins"] for m in members):
            le.fail.add("loop-engine", "Cargo.toml", 0, "no [[bin]] names found in any workspace member")
    out["loop_engine"] = {"path": "Cargo.toml", "members": members}
    return out


def extract_facts(repos):
    cards = extract_repo_cards(repos)
    return {
        "repos": cards,
        "pins": extract_pins(repos, cards),
        "seats": extract_seats(repos),
        "providers": extract_providers(repos),
        "harness": extract_harness(repos),
        "setup_scripts": extract_setup_scripts(repos),
        "coordinator": extract_coordinator(repos),
        **extract_kit_and_engine(repos),
    }


def fact_counts(facts):
    h = facts["harness"]
    return [
        ("seats", len(facts["seats"]["table"]["rows"])),
        ("t3_instances", len(facts["seats"]["t3"]["instances"])),
        ("pi_providers", len(facts["providers"]["pi"]["providers"])),
        ("pi_models", sum(len(p["models"]) for p in facts["providers"]["pi"]["providers"])),
        ("mcp_servers", len(facts["providers"]["mcp"]["servers"])),
        ("skills", len(h["skills"]["names"])),
        ("hooks", len(h["hooks"]["names"])),
        ("setup_scripts", len(facts["setup_scripts"])),
        ("playbook_rules", facts["coordinator"]["playbook"]["rules"]),
        ("ledger_tables", len(facts["coordinator"]["ledger_tables"]["tables"])),
        ("config_keys", facts["coordinator"]["config_keys"]["count"]),
        ("journeys", facts["coordinator"]["journeys"]["count"]),
        ("kit_exports", sum(len(v) for v in facts["agent_kit"]["groups"].values())),
        ("engine_crates", len(facts["loop_engine"]["members"])),
    ]


# --- inline markdown, citations -------------------------------------------------------------------------------------------------------


class Masker:
    """Swaps code spans and citations for tokens, so a `|` inside them never splits a table row or a flow step; restores them after."""

    def __init__(self, render_cite):
        self.render_cite, self.store = render_cite, []

    def hide(self, text):
        def keep(value):
            self.store.append(value)
            return "\x00%d\x00" % (len(self.store) - 1)

        text = CITE.sub(lambda m: keep(self.render_cite(m)), text)
        return CODE_SPAN.sub(lambda m: keep("<code>%s</code>" % esc(m.group(1))), text)

    def show(self, text):
        return re.sub(r"\x00(\d+)\x00", lambda m: self.store[int(m.group(1))], text)

    def plain(self, masked):
        """Hidden text as plain words for the SVG: code spans keep their words, citations drop out."""
        def back(m):
            value = self.store[int(m.group(1))]
            return html.unescape(re.sub(r"</?code>", "", value)) if value.startswith("<code>") else ""

        return plain(re.sub(r"\x00(\d+)\x00", back, masked))


def inline(masked, masker):
    """Inline markdown of already-hidden text: escapes HTML, then links, bold and italic, then restores the hidden parts."""
    text = esc(masked)
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+|#[^)\s]*)\)", lambda m: '<a href="%s">%s</a>' % (m.group(2), m.group(1)), text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*([^*\s][^*]*?)\*(?![\w*])", r"<em>\1</em>", text)
    return masker.show(text)


# --- the content file: citations, flow, markdown ------------------------------------------------------------------------------------


class Content:
    """content.md: citations are checked in a pass over the raw lines, then the page renders from the checked results."""

    def __init__(self, text, repos, fail):
        self.text, self.repos, self.fail = text, repos, fail
        self.lines = re.sub(r"<!--.*?-->", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S).split("\n")  # comments vanish, line numbers stay
        self.citations = 0
        self.checked = {}
        self.masker = Masker(self.render_cite)
        self.flow = None  # the parsed flow steps
        self._scan()

    def _check(self, m, number):
        key = m.group(0)
        repo_name, path, first, last, snippet = m.group(1), m.group(2), int(m.group(3)), int(m.group(4) or m.group(3)), m.group(5).strip()
        self.citations += 1

        def bad(reason):
            self.fail.add(repo_name, path, first, "%s (content.md line %d)" % (reason, number))
            self.checked[key] = '<sup class="cite bad">%s:%s:%d</sup>' % (esc(repo_name), esc(path), first)

        repo = self.repos.get(repo_name)
        if repo is None:
            return bad("unknown repository in citation")
        body = repo.show(path)
        if body is None:
            return bad("cited file is missing at origin/main")
        lines = body.split("\n")
        if not snippet:
            return bad("citation has an empty snippet")
        if first < 1 or last < first or last > len(lines):
            return bad("cited line is outside the file (it has %d lines)" % len(lines))
        if snippet not in "\n".join(lines[first - 1:last]):
            seen = lines[first - 1].strip()[:100] if first == last else "lines %d-%d" % (first, last)
            return bad("snippet %r is not there (%s)" % (snippet, "line reads %r" % seen if first == last else seen))
        self.checked[key] = repo.cite(path, first)

    def _scan(self):
        fenced = None
        for number, line in enumerate(self.lines, 1):
            if line.startswith("```"):
                fenced = None if fenced is not None else line[3:].strip()
                continue
            if fenced is not None and fenced != "flow":
                continue
            for m in CITE.finditer(line):
                self._check(m, number)

    def render_cite(self, m):
        return self.checked.get(m.group(0)) or '<sup class="cite bad">%s</sup>' % esc(m.group(0))

    def inline(self, text):
        return inline(self.masker.hide(text), self.masker)

    # flow ---------------------------------------------------------------------------------------------------------------------------

    def parse_flow(self, rows, first_number):
        steps = []
        for offset, raw in enumerate(rows):
            number = first_number + offset
            if not raw.strip():
                continue
            m = re.match(r"^(\d+)\.\s*(.+)$", raw.strip())
            parts = self.masker.hide(m.group(2)).split("|") if m else []
            if not m or len(parts) != 3:
                self.fail.add("dotfiles", CONTENT_PATH, number, "flow step must read `N. Actor | what happens | where`")
                continue
            if int(m.group(1)) != len(steps) + 1:
                self.fail.add("dotfiles", CONTENT_PATH, number, "flow steps must be numbered 1, 2, 3 in order")
            actor, what, where = (part.strip() for part in parts)
            target = re.match(r"^([A-Za-z0-9_-]+):(\S+)$", self.masker.plain(where).replace(" ", ""))
            link = None
            if target and target.group(1) in self.repos:
                repo, path = self.repos[target.group(1)], target.group(2)
                if repo.exists(path):
                    link = (repo, path)
                else:
                    self.fail.add(repo.name, path, 0, "flow step %s names a path missing at origin/main (content.md line %d)" % (m.group(1), number))
            steps.append({"n": int(m.group(1)), "actor": self.masker.plain(actor), "what": what, "where": where, "link": link, "line": number})
        return steps

    # markdown -----------------------------------------------------------------------------------------------------------------------

    def render(self, lines, first_number, headings=None):
        """HTML for a run of markdown lines (`first_number` is the file line of lines[0])."""
        out, i = [], 0
        while i < len(lines):
            line, number = lines[i], first_number + i
            if line.startswith("```"):
                lang, body = line[3:].strip(), []
                i += 1
                while i < len(lines) and not lines[i].startswith("```"):
                    body.append(lines[i])
                    i += 1
                i += 1
                if lang == "flow":
                    self.flow = self.parse_flow(body, number + 1)
                    out.append("\x01FLOW\x01")
                else:
                    out.append("<pre><code>%s</code></pre>" % esc("\n".join(body)))
                continue
            if not line.strip():
                i += 1
                continue
            m = re.match(r"^(#{1,6})\s+(.*)$", line)
            if m:
                level = min(len(m.group(1)) + 1, 6) if headings is not None else len(m.group(1))
                out.append("<h%d>%s</h%d>" % (level, self.inline_line(m.group(2)), level))
                i += 1
                continue
            if re.match(r"^(-{3,}|\*{3,})\s*$", line):
                out.append("<hr>")
                i += 1
                continue
            if line.startswith("|") and i + 1 < len(lines) and re.match(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$", lines[i + 1]):
                end = i + 2
                while end < len(lines) and lines[end].startswith("|"):
                    end += 1
                out.append(self.table(lines[i:end]))
                i = end
                continue
            if re.match(r"^\s*([-*]|\d+\.)\s+", line):
                end = i
                while end < len(lines) and (re.match(r"^\s*([-*]|\d+\.)\s+", lines[end]) or (lines[end].strip() and lines[end].startswith("  "))):
                    end += 1
                out.append(self.list(lines[i:end], first_number + i))
                i = end
                continue
            if line.startswith(">"):
                end = i
                while end < len(lines) and lines[end].startswith(">"):
                    end += 1
                quote = self.render([re.sub(r"^>\s?", "", row) for row in lines[i:end]], first_number + i)
                out.append("<blockquote>%s</blockquote>" % quote)
                i = end
                continue
            end = i
            while end < len(lines) and lines[end].strip() and not re.match(r"^(```|#{1,6}\s|\||>|\s*([-*]|\d+\.)\s)", lines[end]):
                end += 1
            end = max(end, i + 1)
            out.append("<p>%s</p>" % self.inline_line(" ".join(row.strip() for row in lines[i:end])))
            i = end
        return "\n".join(out)

    def inline_line(self, text):
        return inline(self.masker.hide(text), self.masker)

    def table(self, rows):
        def cells(row):
            return [c.strip() for c in self.masker.hide(row).strip().strip("|").split("|")]

        head = cells(rows[0])
        body = [cells(row) for row in rows[2:]]
        th = "".join("<th>%s</th>" % inline(c, self.masker) for c in head)
        tr = "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % inline(c, self.masker) for c in row) for row in body)
        return '<div class="scroll"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (th, tr)

    def list(self, rows, first_number):
        ordered = bool(re.match(r"^\s*\d+\.", rows[0]))
        items = []
        for offset, row in enumerate(rows):
            m = re.match(r"^(\s*)([-*]|\d+\.)\s+(.*)$", row)
            if m and len(m.group(1)) < 2:
                items.append([m.group(3), []])
            elif items:
                items[-1][1].append(row[2:] if row.startswith("  ") else row)
        html_items = []
        for text, rest in items:
            nested = [r for r in rest if re.match(r"^\s*([-*]|\d+\.)\s+", r)]
            cont = [r.strip() for r in rest if r not in nested]
            sub = self.list(nested, first_number) if nested else ""
            html_items.append("<li>%s%s</li>" % (self.inline_line(" ".join([text] + cont)), sub))
        tag = "ol" if ordered else "ul"
        return "<%s>%s</%s>" % (tag, "".join(html_items), tag)

    def sections(self):
        """Split the content at its `##` headings: (intro html, {key: (title, html)}, extra [(title, html)])."""
        starts = [i for i, line in enumerate(self.lines) if re.match(r"^##\s+", line) and not self._in_fence(i)]
        intro_lines = self.lines[: starts[0]] if starts else self.lines
        intro = self.render([row for row in intro_lines if not re.match(r"^#\s", row)], 1)
        found, extra, used = {}, [], set()
        for n, start in enumerate(starts):
            stop = starts[n + 1] if n + 1 < len(starts) else len(self.lines)
            title = re.sub(r"^##\s+", "", self.lines[start]).strip()
            body = self.render(self.lines[start + 1:stop], start + 2, headings=True)
            key = next((k for k, _, words in SECTIONS if k not in used and any(w in title.lower() for w in words)), None)
            if key:
                used.add(key)
                found[key] = (plain(title), body)
            else:
                extra.append((plain(title), body))
        for key, name, words in SECTIONS:
            if key not in found:
                self.fail.add("dotfiles", CONTENT_PATH, 0, "no `## ` section for %r (a heading with %s)" % (name, " or ".join(repr(w) for w in words)))
        if self.flow is None:
            self.fail.add("dotfiles", CONTENT_PATH, 0, "no ```flow block")
        return intro, found, extra

    def _in_fence(self, index):
        return sum(1 for line in self.lines[:index] if line.startswith("```")) % 2 == 1


# --- SVG ----------------------------------------------------------------------------------------------------------------------------


def wrap(text, width):
    """Lines of at most `width` characters; a word longer than that is cut."""
    lines, cur = [], ""
    for word in text.split():
        while len(word) > width:
            if cur:
                lines.append(cur)
                cur = ""
            lines.append(word[:width])
            word = word[width:]
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = (cur + " " + word).strip()
    return lines + ([cur] if cur else [])


def tspans(lines, x, size, cls="", anchor="start", dy=0):
    return "".join('<text class="%s" x="%s" y="%s" text-anchor="%s" font-size="%s">%s</text>' % (cls, x, dy + i * round(size * 1.35, 1), anchor, size, esc(row)) for i, row in enumerate(lines))


def arch_svg(facts):
    pins, cards = facts["pins"], facts["repos"]
    kit, le = pins["agent_kit"], pins["loop_engine"]
    kit_label = "pin " + ("/".join(sorted({p["version"] for p in kit["pins"]})) if kit["pins_agree"] else " vs ".join(p["version"] for p in kit["pins"]))
    le_label = "mise " + ("/".join(sorted({t["version"] for t in le["tools"]})))
    harness = facts["harness"]
    boxes = {
        "coordinator": (14, 14, 150, 64, "coordinator", "v" + cards["coordinator"]["version"]["text"]),
        "dotfiles": (196, 14, 150, 64, "dotfiles", "@ " + cards["dotfiles"]["sha"]),
        "agent-kit": (14, 214, 150, 64, "agent-kit", "v" + cards["agent-kit"]["version"]["text"]),
        "loop-engine": (196, 214, 150, 64, "loop-engine", "v" + cards["loop-engine"]["version"]["text"]),
    }
    parts = ['<svg class="diagram" viewBox="0 0 360 468" role="img" aria-labelledby="arch-title"><title id="arch-title">How the four repositories depend on each other</title>',
             '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" class="arrowhead"/></marker></defs>']

    def edge(x1, y1, x2, y2, label, lx, ly, bad=False, path=None):
        parts.append('<path class="edge" d="%s" marker-end="url(#arrow)"/>' % (path or "M%s %sL%s %s" % (x1, y1, x2, y2)))
        width = len(label) * 7 + 10
        parts.append('<rect class="lab" x="%s" y="%s" width="%s" height="20" rx="4"/>' % (lx - width / 2, ly - 14, width))
        parts.append('<text class="%s" x="%s" y="%s" text-anchor="middle" font-size="12.5">%s</text>' % ("bad" if bad else "t", lx, ly, esc(label)))

    edge(60, 78, 60, 214, kit_label, 60, 150, not kit["pins_agree"])
    edge(300, 78, 300, 214, le_label, 300, 150, not le["pins_agree"])
    edge(110, 78, 240, 214, "bookends-check", 207, 184)
    edge(250, 78, 120, 214, kit_label, 218, 112, not kit["pins_agree"])
    for name, (x, y, w, h, title, sub) in boxes.items():
        parts.append('<rect class="box" x="%s" y="%s" width="%s" height="%s" rx="10"/>' % (x, y, w, h))
        parts.append('<text class="t strong" x="%s" y="%s" text-anchor="middle" font-size="16">%s</text>' % (x + w / 2, y + 28, esc(title)))
        parts.append('<text class="t muted" x="%s" y="%s" text-anchor="middle" font-size="13">%s</text>' % (x + w / 2, y + 48, esc(sub)))
    harnesses = ["Claude", "Codex", "Pi"] + (["Cursor"] if harness["cursor"] else []) + ["T3"]
    parts.append('<path class="edge" d="M346 46H356V400H346" marker-end="url(#arrow)"/>')
    parts.append('<rect class="box accent" x="14" y="350" width="332" height="100" rx="10"/>')
    parts.append('<text class="t strong" x="180" y="378" text-anchor="middle" font-size="16">this machine: agent-harness</text>')
    parts.append(tspans(wrap("%d skills, %d hooks, seat instances" % (len(harness["skills"]["names"]), len(harness["hooks"]["names"])), 38), 180, 13, "t muted", "middle", 400))
    parts.append(tspans(wrap("projected into " + ", ".join(harnesses), 38), 180, 13, "t muted", "middle", 420))
    parts.append('<rect class="lab" x="210" y="316" width="130" height="20" rx="4"/><text class="t" x="275" y="331" text-anchor="middle" font-size="12.5">projects into</text>')
    parts.append("</svg>")
    return "".join(parts)


def flow_svg(steps):
    actors = []
    for step in steps:
        if step["actor"] not in actors:
            actors.append(step["actor"])
    width, y, parts = 360, 10, []
    body = []
    for step in steps:
        color = actors.index(step["actor"]) % 6
        what = wrap(step["what_plain"], 36)
        where = wrap(step["where_plain"], 40)
        height = 34 + len(what) * 19 + (len(where) * 16 + 8 if where else 0)
        if body:
            body.append('<path class="edge" d="M180 %s V%s" marker-end="url(#arrow)"/>' % (y - 16, y - 1))
        body.append('<rect class="box" x="10" y="%s" width="340" height="%s" rx="10"/>' % (y, height))
        body.append('<rect class="stripe c%d" x="10" y="%s" width="8" height="%s" rx="4"/>' % (color, y, height))
        body.append('<circle class="num c%d" cx="38" cy="%s" r="12"/><text class="onfill" x="38" y="%s" text-anchor="middle" font-size="13">%d</text>' % (color, y + 22, y + 27, step["n"]))
        body.append('<text class="t strong" x="58" y="%s" font-size="14">%s</text>' % (y + 27, esc(step["actor"])))
        body.append(tspans(what, 30, 14, "t", "start", y + 50))
        if where:
            body.append(tspans(where, 30, 12.5, "t muted mono", "start", y + 50 + len(what) * 19 + 2))
        y += height + 16
    parts.append('<svg class="diagram" viewBox="0 0 %d %d" role="img" aria-labelledby="flow-title"><title id="flow-title">How a piece of work moves, step by step</title>' % (width, y - 6))
    parts.append('<defs><marker id="arrow2" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" class="arrowhead"/></marker></defs>')
    parts.append("".join(body).replace("url(#arrow)", "url(#arrow2)"))
    parts.append("</svg>")
    return "".join(parts)


# --- the page ----------------------------------------------------------------------------------------------------------------------

CSS = """
:root{color-scheme:light dark;--canvas:light-dark(#f9f8f6,#1c1a19);--primary-text:light-dark(#b5523b,#e8917a);--soft:light-dark(#f2efeb,#232120);--card:light-dark(#ebe6e0,#2b2826);
--strong:light-dark(#e3dcd4,#36322f);--hair:light-dark(#e6e0d9,#3c3734);--ink:light-dark(#1a1716,#f5f1ee);--body:light-dark(#403b38,#cec6c1);--muted:light-dark(#6e6863,#a69e98);
--ok:light-dark(#2f7d43,#7fcf92);--warn:light-dark(#8a6400,#e3b341);--bad:light-dark(#b23b3b,#e88080);--dark:light-dark(#1c1a19,#141211);--on-dark:#f9f8f6;
--c0:light-dark(#b5523b,#e8917a);--c1:light-dark(#5b7fa6,#86a7cc);--c2:light-dark(#7d7d2c,#b8b86a);--c3:light-dark(#2f7d43,#7fcf92);--c4:light-dark(#8a5a9a,#c39ad0);--c5:light-dark(#6e6863,#a69e98);
--display:"Cormorant Garamond","EB Garamond",Garamond,Georgia,"Times New Roman",serif;--sans:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
*{box-sizing:border-box}body{margin:0;background:var(--canvas);color:var(--body);font:17px/1.6 var(--sans);-webkit-text-size-adjust:100%}
main{max-width:860px;margin:0 auto;padding:32px 20px 64px}
h1,h2,h3{font-family:var(--display);font-weight:400;color:var(--ink);letter-spacing:-.02em;line-height:1.15}
h1{font-size:clamp(36px,8vw,56px);margin:0 0 8px}h2{font-size:clamp(28px,6vw,38px);margin:48px 0 12px}h3{font-size:26px;margin:28px 0 8px}h4{font-size:18px;color:var(--ink);margin:20px 0 4px}
a{color:var(--primary-text)}p,li{overflow-wrap:anywhere}code{font:14px var(--mono);background:var(--soft);padding:1px 5px;border-radius:4px;overflow-wrap:anywhere}
pre{background:var(--dark);color:var(--on-dark);padding:16px;border-radius:12px;overflow-x:auto;font:14px/1.5 var(--mono)}pre code{background:none;padding:0}
.eyebrow{color:var(--muted);font-size:13px;letter-spacing:1.5px;text-transform:uppercase;margin:0}
.lede{font-size:19px;color:var(--ink)}.muted{color:var(--muted)}.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:15px}th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--hair);vertical-align:top}th{color:var(--ink);font-weight:600}
td{overflow-wrap:anywhere}td:first-child{min-width:7em}
.cite{font-size:11px;margin-left:2px;line-height:0}.cite a{text-decoration:none;color:var(--muted)}.cite{white-space:nowrap}.cite.bad{color:var(--bad)}
nav ul{list-style:none;padding:0;display:flex;flex-wrap:wrap;gap:8px}nav a{display:inline-block;padding:6px 12px;background:var(--card);border-radius:999px;color:var(--ink);text-decoration:none;font-size:14px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin:12px 0}
.card{background:var(--card);border-radius:12px;padding:16px}.card h3{margin:0 0 4px;font-size:24px}.card p{margin:6px 0}.card .meta{font-size:14px;color:var(--muted)}
.ver{display:inline-block;background:var(--strong);color:var(--ink);border-radius:999px;padding:1px 10px;font-size:13px;margin-right:6px}
details{border:1px solid var(--hair);border-radius:12px;margin:12px 0;background:var(--soft)}summary{cursor:pointer;padding:14px 16px;font:500 18px var(--sans);color:var(--ink)}
details>div{padding:0 16px 16px}.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad);font-weight:600}
.chips{display:flex;flex-wrap:wrap;gap:6px;padding:0;list-style:none}.chips li{background:var(--card);border-radius:999px;padding:2px 10px;font:13px var(--mono)}
.diagram{display:block;width:100%;max-width:560px;height:auto;margin:16px auto}
.diagram .box{fill:var(--card);stroke:var(--hair);stroke-width:1.5}.diagram .box.accent{fill:var(--strong)}.diagram .edge{fill:none;stroke:var(--muted);stroke-width:2}
.diagram .arrowhead{fill:var(--muted)}.diagram .lab{fill:var(--canvas);stroke:var(--hair)}.diagram text{font-family:var(--sans)}.diagram .t{fill:var(--ink)}.diagram .strong{font-weight:600}
.diagram .muted{fill:var(--muted)}.diagram .mono{font-family:var(--mono)}.diagram text.bad{fill:var(--bad);font-weight:700}.diagram .onfill{fill:var(--canvas);font-weight:700;font-family:var(--sans)}
.diagram .stripe.c0,.diagram .num.c0{fill:var(--c0)}.diagram .stripe.c1,.diagram .num.c1{fill:var(--c1)}.diagram .stripe.c2,.diagram .num.c2{fill:var(--c2)}
.diagram .stripe.c3,.diagram .num.c3{fill:var(--c3)}.diagram .stripe.c4,.diagram .num.c4{fill:var(--c4)}.diagram .stripe.c5,.diagram .num.c5{fill:var(--c5)}
ol.steps li{margin:8px 0}footer{margin-top:64px;padding:24px;background:var(--dark);color:var(--on-dark);border-radius:12px;font-size:14px}footer code{background:#2b2826;color:var(--on-dark)}
blockquote{margin:12px 0;padding:4px 16px;border-left:3px solid var(--hair);color:var(--muted)}
@media(max-width:600px){body{font-size:18px}main{padding:20px 14px 48px}th,td{padding:8px 6px}}
@media print{details{border:0}}
"""


def src(repo, path, line):
    """A small cited-source link for a generated fact."""
    return '<sup class="cite"><a title="%s %s:%d" href="%s">L%d</a></sup>' % (repo.name, esc(path), line, repo.url(path, line), line) if line else ""


def table(head, rows):
    return '<div class="scroll"><table><thead><tr>%s</tr></thead><tbody>%s</tbody></table></div>' % (
        "".join("<th>%s</th>" % esc(h) for h in head), "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % c for c in row) for row in rows))


def chips(names):
    return '<ul class="chips">%s</ul>' % "".join("<li>%s</li>" % esc(n) for n in names)


def details(key, title, intro, body, sources, open_=False):
    """A collapsible section; `sources` are the (repo, path) files its facts were read from, each fact's L-number links to its line."""
    read = " ".join('<code><a href="%s">%s %s</a></code>' % (repo.url(path), repo.name, esc(path)) for repo, path in sources)
    return '<details id="%s"%s><summary>%s</summary><div><p class="muted">%s</p>%s<p class="muted">Read from: %s</p></div></details>' % (key, " open" if open_ else "", esc(title), esc(intro), body, read)


def repo_cards(facts, repos):
    out = []
    for name in REPOS:
        c, r = facts["repos"][name], repos[name]
        v = c["version"]
        ver = esc(v["text"]) if not v["path"] else "v%s%s" % (esc(v["text"]), src(r, v["path"], v["line"]))
        out.append('<div class="card"><h3>%s</h3><p><span class="ver">%s</span><span class="ver">%s · %s</span></p><p>%s%s</p></div>' % (
            esc(name), ver, esc(c["sha"]), esc(c["date"]), esc(c["purpose"]["text"]), src(r, "README.md", c["purpose"]["line"])))
    return '<div class="cards">%s</div>' % "".join(out)


def pins_html(facts, repos):
    kit, le = facts["pins"]["agent_kit"], facts["pins"]["loop_engine"]
    rows = []
    for pin in kit["pins"]:
        rows.append([esc(pin["repo"]) + " " + esc(pin["path"]) + src(repos[pin["repo"]], pin["path"], pin["line"]), "agent-kit", esc(pin["version"])])
    for tool in le["tools"]:
        rows.append([esc(le["path"]) + " " + esc(tool["name"]) + src(repos["dotfiles"], le["path"], tool["line"]), "Loop Engine", esc(tool["version"])])
    status = []
    status.append('<p class="%s">agent-kit pins: %s. agent-kit main is v%s%s.</p>' % (
        "ok" if kit["pins_agree"] else "bad", "both the same" if kit["pins_agree"] else "MISMATCH: the two pins differ", esc(kit["main"]),
        "; the pins are behind it" if kit["behind_main"] and kit["pins_agree"] else ""))
    status.append('<p class="%s">Loop Engine tool pins: %s. loop-engine main is v%s%s.</p>' % (
        "ok" if le["pins_agree"] else "bad", "all the same" if le["pins_agree"] else "MISMATCH: the tools are pinned to different versions", esc(le["main"]),
        "; the pins are behind it" if le["behind_main"] and le["pins_agree"] else ""))
    return "".join(status) + table(["Where", "What", "Pinned"], rows)


def seats_html(facts, repos):
    dot = repos["dotfiles"]
    seats, t3 = facts["seats"]["table"], facts["seats"]["t3"]
    a = table(["Seat", "Model"], [[esc(r["seat"]) + src(dot, seats["path"], r["line"]), esc(r["model"])] for r in seats["rows"]])
    rows = []
    for i in t3["instances"]:
        notes = []
        if i["advisor"] is False:
            notes.append("advisor off")
        elif i["advisor"]:
            notes.append("advisor on")
        notes += (["helpers on Haiku"] if i["helpers_on_haiku"] else []) + (["5-minute prompt cache"] if i["five_minute_cache"] else []) + (["tool list: " + i["mcp_file"]] if i["mcp_file"] else [])
        rows.append([esc(i["id"]) + src(dot, t3["path"], i["line"]), esc(i["window"] or "-"), esc(", ".join(notes) or "-")])
    return a + "<h4>T3 seat instances on this machine</h4>" + table(["Instance", "Window", "Notes"], rows)


def providers_html(facts, repos):
    dot = repos["dotfiles"]
    pi, mcp = facts["providers"]["pi"], facts["providers"]["mcp"]
    rows = [[esc(p["name"]) + src(dot, pi["path"], p["line"]), esc(p["profile"]), esc(", ".join(p["models"]) or "not listed in this file")] for p in pi["providers"]]
    return ("<p>Names and model ids only; keys are never read.</p>" + table(["Pi provider", "Profile", "Models"], rows)
            + "<h4>MCP servers the harnesses are given (some only on the work profile or one OS)</h4>" + chips(s["name"] for s in mcp["servers"]))


def harness_html(facts):
    h = facts["harness"]
    return ("<p>Harness projections: %s%s. Profiles: %s.</p>" % (", ".join(esc(n) for n in h["adapters"]["names"]), " and cursor (dot_cursor)" if h["cursor"] else "", ", ".join(esc(n) for n in h["profiles"]["names"]))
            + "<h4>%d skills</h4>%s<h4>%d hooks</h4>%s<h4>%d instruction files</h4>%s" % (
                len(h["skills"]["names"]), chips(h["skills"]["names"]), len(h["hooks"]["names"]), chips(h["hooks"]["names"]), len(h["instructions"]["names"]), chips(h["instructions"]["names"])))


def coordinator_html(facts, repos):
    co, c = repos["coordinator"], facts["coordinator"]
    comp = table(["Part", "Path", "What it is"], [[esc(x["name"]), esc(x["path"]) + src(co, x["path"], 1), esc(x["about"])] for x in c["components"]])
    stats = [["playbook rules", "%d (%s)" % (c["playbook"]["rules"], ", ".join("%s %d" % kv for kv in c["playbook"]["by_tag"].items())) + src(co, c["playbook"]["path"], 1)],
             ["ledger tables", "%d: %s" % (len(c["ledger_tables"]["tables"]), ", ".join(t["name"] for t in c["ledger_tables"]["tables"])) + src(co, c["ledger_tables"]["path"], c["ledger_tables"]["tables"][0]["line"] if c["ledger_tables"]["tables"] else 0)],
             ["settings keys (CONFIG_KEYS)", "%d" % c["config_keys"]["count"] + src(co, c["config_keys"]["path"], c["config_keys"]["line"])],
             ["`coordinator` commands", ", ".join(c["cli"]["commands"]) + src(co, c["cli"]["path"], 1)],
             ["black-box journeys", "%d files in %s" % (c["journeys"]["count"], c["journeys"]["path"])],
             ["product requirements", "%d `### LE-` headings" % c["prd"]["requirements"] + src(co, c["prd"]["path"], 1)]]
    layout = table(["In the state directory", "What it is (as documented)"], [[esc(x["name"]) + src(co, x["path"], x["line"]), esc(x["about"]).replace("`", "")] for x in c["state_layout"]])
    return comp + "<h4>By the numbers</h4>" + table(["What", "Value"], [[esc(a), b] for a, b in stats]) + "<h4>State directory</h4>" + layout


def kit_engine_html(facts, repos):
    kit, le = facts["agent_kit"], facts["loop_engine"]
    a = table(["Group", "Import paths"], [[esc(g), esc(", ".join(subs))] for g, subs in kit["groups"].items()])
    b = table(["Crate", "Program it builds"], [[esc(m["path"]), esc(", ".join(m["bins"]) or "library only")] for m in le["members"] if not m["path"].startswith("tests/")])
    return "<h4>agent-kit exports (package.json)%s</h4>%s<h4>Loop Engine workspace (Cargo.toml)%s</h4>%s" % (src(repos["agent-kit"], kit["path"], kit["line"]), a, src(repos["loop-engine"], le["path"], 1), b)


def build_page(facts, repos, content_parts, command, content):
    intro, found, extra = content_parts
    cards = facts["repos"]
    top = table(["Repository", "Commit of main", "Date"], [[esc(n), '<a href="%s">%s</a>' % (repos[n].commit_url(), esc(cards[n]["sha"])), esc(cards[n]["date"])] for n in REPOS])
    secs = {k: found[k] for k in found}
    flow = facts["flow"]
    flow_list = "".join("<li><strong>%s:</strong> %s %s</li>" % (esc(s["actor"]), content.inline(s["what"]), flow_where(s, content)) for s in flow)
    pieces = [
        '<p class="eyebrow">Agent stack map</p><h1>How the agent stack works</h1>',
        '<p class="lede">Generated from the main branch of four repositories. If a commit below differs from the repository\'s current main, this page is stale: run the command at the bottom.</p>', top,
        "<nav><ul>%s</ul></nav>" % "".join('<li><a href="#%s">%s</a></li>' % (k, esc(t)) for k, t in (
            ("start", "Start here"), ("picture", "One-minute picture"), ("arch", "Architecture"), ("repos", "Repositories"), ("flow", "How work moves"), ("facts", "Facts from the files"), ("change", "Where to change X"), ("glossary", "Glossary"))),
        intro,
        '<section id="start"><h2>%s</h2>%s</section>' % (esc(secs["start"][0]), secs["start"][1]),
        '<section id="picture"><h2>%s</h2>%s</section>' % (esc(secs["picture"][0]), secs["picture"][1]),
        '<section id="arch"><h2>Architecture</h2><p>The four repositories, and how each depends on the others. Numbers on the lines are the versions read from the files.</p>%s</section>' % arch_svg(facts),
        '<section id="repos"><h2>%s</h2>%s%s</section>' % (esc(secs["repos"][0]), repo_cards(facts, repos), secs["repos"][1]),
        '<section id="flow"><h2>%s</h2>%s</section>' % (esc(secs["flow"][0]), secs["flow"][1]),
        '<section id="facts"><h2>Facts read from the files</h2><p class="muted">Each fact links to the file and line it came from, at the commit above.</p>',
        details("d-seats", "Seats and models", "Which model each agent role runs on, and the T3 instances that start them.", seats_html(facts, repos), [(repos["dotfiles"], facts["seats"]["table"]["path"]), (repos["dotfiles"], facts["seats"]["t3"]["path"])], True),
        details("d-providers", "Model providers and tools", "The Pi providers and the MCP servers every harness is given.", providers_html(facts, repos), [(repos["dotfiles"], facts["providers"]["pi"]["path"]), (repos["dotfiles"], facts["providers"]["mcp"]["path"])], True),
        details("d-pins", "Version pins", "Which version of agent-kit and Loop Engine each place installs. A mismatch is flagged in red.", pins_html(facts, repos), [(repos["coordinator"], "package.json"), (repos["dotfiles"], facts["pins"]["loop_engine"]["path"]), (repos["dotfiles"], "dot_local/share/agent-kit/package.json")]),
        details("d-harness", "agent-harness: skills, hooks, adapters", "The shared layer that puts the same skills, tools and rules into every agent program.", harness_html(facts), [(repos["dotfiles"], facts["harness"][k]["path"]) for k in ("skills", "hooks", "adapters", "instructions")]),
        details("d-setup", "Dotfiles setup scripts", "Scripts chezmoi runs when the dotfiles are applied, in order.", table(["Script", "What it does"], [[esc(s["name"]), esc(s["line"])] for s in facts["setup_scripts"]]), [(repos["dotfiles"], "")]),
        details("d-coordinator", "The coordinator in numbers", "Its parts, tables and commands.", coordinator_html(facts, repos), [(repos["coordinator"], x["path"]) for x in (facts["coordinator"]["cli"], facts["coordinator"]["config_keys"], facts["coordinator"]["ledger_tables"], facts["coordinator"]["playbook"])]),
        details("d-kit", "agent-kit and Loop Engine", "What the two libraries expose.", kit_engine_html(facts, repos), [(repos["agent-kit"], "package.json"), (repos["loop-engine"], "Cargo.toml")]),
        "</section>",
        '<section id="change"><h2>%s</h2>%s</section>' % (esc(secs["change"][0]), secs["change"][1]),
    ] + ['<section><h2>%s</h2>%s</section>' % (esc(t), b) for t, b in extra] + [
        '<section id="glossary"><h2>%s</h2>%s</section>' % (esc(secs["glossary"][0]), secs["glossary"][1]),
        '<footer><p>Built by <code>%s</code> from <code>origin/main</code> of dotfiles, coordinator, agent-kit and loop-engine. The same commits give the same page. To refresh, run the command again (it fetches first).</p></footer>' % esc(command),
    ]
    flow_block = flow_svg(flow) + '<ol class="steps">%s</ol>' % flow_list
    pieces = [piece.replace("\x01FLOW\x01", flow_block) for piece in pieces]
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Agent stack map</title><style>%s</style></head><body><main>%s</main></body></html>\n' % (CSS, "\n".join(pieces))


def flow_where(step, content):
    if step["link"]:
        repo, path = step["link"]
        return '<code><a href="%s">%s:%s</a></code>' % (repo.url(path, tree=repo.show(path) is None), esc(repo.name), esc(path))
    return content.inline(step["where"])


# --- main ----------------------------------------------------------------------------------------------------------------------------


def write_log(entry):
    path = Path(os.environ.get("STACK_MAP_LOG") or Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "stack-map" / "log.jsonl")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
    except OSError as error:
        print("stack_map: could not write the run log %s: %s" % (path, error), file=sys.stderr)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", help="write the HTML page here")
    parser.add_argument("--fetch", action="store_true", help="git fetch origin main in each repository first")
    parser.add_argument("--repos-root", default=os.environ.get("STACK_MAP_REPOS_ROOT") or str(Path.home() / "git"), help="folder holding the four repositories (default ~/git)")
    parser.add_argument("--content", help="read the content from this file instead of docs/stack-map/content.md at dotfiles origin/main")
    parser.add_argument("--facts-json", action="store_true", help="print the extracted facts as JSON (no page unless --out is also given)")
    args = parser.parse_args(argv)
    if not args.out and not args.facts_json:
        parser.error("give --out PAGE.html, --facts-json, or both")
    began, fail = time.monotonic(), Failures()
    root = Path(args.repos_root).expanduser()
    if args.fetch:
        for name in REPOS:
            done = subprocess.run(["git", "-C", str(root / name), "fetch", "origin", "main"], capture_output=True, text=True)
            if done.returncode != 0:
                fail.add(name, "origin/main", 0, "git fetch origin main failed: " + (done.stderr.strip().splitlines() or [""])[-1])
    repos = {name: Repo(name, root / name, fail) for name in REPOS}
    facts = extract_facts(repos) if all(r.sha for r in repos.values()) else {}
    summary, page = [], None
    if facts and args.out:
        dot = repos["dotfiles"]
        text = Path(args.content).read_text(encoding="utf-8") if args.content else dot.need(CONTENT_PATH)
        if text is not None:
            content = Content(text, repos, fail)
            parts = content.sections()
            for step in content.flow or []:
                step["what_plain"], step["where_plain"] = content.masker.plain(step["what"]), content.masker.plain(step["where"])
            facts["flow"] = content.flow or []
            summary.append("citations verified: %d" % content.citations)
            if not fail.items:
                page = build_page(facts, repos, parts, "python3 ~/.local/user_scripts/stack_map.py --fetch --out stack-map.html", content)
    if facts and args.facts_json and not fail.items:
        print(json.dumps({k: v for k, v in facts.items() if k != "flow"}, indent=2, sort_keys=True))
    shas = {n: r.sha[:7] for n, r in repos.items()}
    write_log({"utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "action": "stack-map", "outcome": "failed" if fail.items else "ok", "failures": len(fail.items),
               "duration_ms": round((time.monotonic() - began) * 1000), "shas": shas, "wrote": bool(page)})
    if fail.items:
        for item in fail.items:
            print(item, file=sys.stderr)
        print("stack_map: %d failure(s); nothing written" % len(fail.items), file=sys.stderr)
        return 1
    report = sys.stderr if args.facts_json else sys.stdout  # stdout carries the JSON when it is asked for
    if page is not None:
        Path(args.out).write_text(page, encoding="utf-8")
        print("stack_map: wrote %s (%d bytes)" % (args.out, len(page.encode("utf-8"))), file=report)
    for name in REPOS:
        print("  %-12s %s %s" % (name, repos[name].sha[:7], repos[name].date), file=report)
    print("  facts: " + " ".join("%s=%d" % kv for kv in fact_counts(facts)), file=report)
    for line in summary:
        print("  " + line, file=report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
