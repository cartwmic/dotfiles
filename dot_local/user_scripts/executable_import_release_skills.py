#!/usr/bin/env python3
"""Import Loop Engine skill bundles from an immutable release tag into the canonical skills tree.

    import_release_skills.py import TAG [--source DIR] [--repo OWNER/REPO] [--expect-commit SHA]
                                        [--pins] [--apply] [--prune]
    import_release_skills.py verify-deployed [NAME ...] [--source DIR]

`import` shows, per skill bundle, what the tag changes in
<source>/dot_local/share/agent-harness/canonical/skills and writes nothing until --apply.
The tag is resolved to one commit; every imported file is read from that commit's archive and
must match the git blob hash in the commit's tree. Files that sit in a bundle but not in the tag
are orphans: --apply refuses while any exist, and --prune deletes them. --pins also moves the
four Loop Engine tool pins (loop-engine, lean-change, policy-document, research) in
dot_config/mise/config.toml to the tag's version (mise keeps older installed versions, so frozen
runs keep theirs; this tool never uninstalls anything). The software-change pin was removed from
that file: releases no longer ship it, and installed copies are untouched.

`verify-deployed` compares the canonical bundles in the source with the deployed copies byte for
byte (extra deployed files are orphans: chezmoi apply does not delete them) and checks that each
harness skill directory links to the deployed bundle. It is read-only.

Layout of a bundle (the layout the owner's imports have always used):
  skills/<name>/** or crates/<crate>/skills/<name>/**   -> <name>/**
  crates/<crate>/README.md, docs/**, data/**            -> using-<crate>/references/README.md, docs/**, data/**
  ROOT_REFERENCES: named docs/ files of a repo-root skill -> <name>/references/<file>

Python 3 standard library; needs an authenticated `gh` for `import`.
"""

import argparse
import base64
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
from pathlib import Path

DEFAULT_REPO = "cartwmic/loop-engine"
CANONICAL_SKILLS = Path("dot_local/share/agent-harness/canonical/skills")
MISE_CONFIG = Path("dot_config/mise/config.toml")
SKILL_FILE = re.compile(r"^((?:crates/[^/]+/)?)skills/([^/]+)/SKILL\.md$")
CRATE_REFERENCE_DIRS = ("docs", "data")
# docs/ files of a repo-root skill that ship in its references/ directory.
ROOT_REFERENCES = {
    "using-loop-engine": (
        "agent-usage.md",
        "operational-ux-capture.schema.json",
        "operational-ux-contracts.md",
        "PRD.md",
    ),
}
PIN_LINE = re.compile(r'^((?:loop-engine|lean-change|policy-document|research) = \{ version = ")([^"]+)(")', re.M)
PIN_COUNT = 4
# Names chezmoi would read as attributes, or drop (an empty file is not deployed without empty_).
CHEZMOI_SPECIAL = re.compile(
    r"^(?:\.|(?:after|before|create|dot|empty|encrypted|exact|executable|external|literal|modify|once|onchange|"
    r"private|readonly|remove|run|symlink)_)|\.tmpl$"
)
HARNESS_SKILL_DIRS = (".claude/skills", ".codex/skills", ".pi/agent/skills", ".agents/skills")


class Failure(Exception):
    pass


def gh(*args):
    try:
        result = subprocess.run(["gh", *args], stdin=subprocess.DEVNULL, capture_output=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Failure("cannot run gh: %s" % error)
    if result.returncode != 0:
        raise Failure("gh %s failed: %s" % (" ".join(args[:3]), result.stderr.decode("utf-8", "replace").strip()))
    return result.stdout


def gh_json(*args):
    return json.loads(gh(*args))


def git_blob_sha(data):
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


# --- the release -------------------------------------------------------------------------------


def resolve_tag(repo, tag):
    """Commit sha of an existing, published, non-prerelease release tag."""
    release = gh_json("release", "view", tag, "-R", repo, "--json", "tagName,isDraft,isPrerelease")
    if release.get("tagName") != tag or release.get("isDraft") or release.get("isPrerelease"):
        raise Failure("%s is not a published release of %s" % (tag, repo))
    obj = gh_json("api", "repos/%s/git/ref/tags/%s" % (repo, tag))["object"]
    for _ in range(5):  # an annotated tag points at a tag object
        if obj["type"] == "commit":
            return obj["sha"]
        if obj["type"] != "tag":
            raise Failure("tag %s points at a %s, not a commit" % (tag, obj["type"]))
        obj = gh_json("api", "repos/%s/git/tags/%s" % (repo, obj["sha"]))["object"]
    raise Failure("tag %s is nested too deep" % tag)


def plan_bundles(tree):
    """{name: {destination path in the bundle: (path in the repo, blob sha, mode)}} from a git tree listing."""
    files = {entry["path"]: entry for entry in tree if entry["type"] == "blob"}
    bundles = {}
    for path in sorted(files):
        match = SKILL_FILE.match(path)
        if not match:
            continue
        base, name = match.groups()
        if name in bundles:
            raise Failure("two skills named %s in the tag" % name)
        crate = base.split("/")[1] if base else ""
        references = crate != "" and name == "using-" + crate  # a crate's README, docs and data go to its own skill only
        wanted = {}
        for source, entry in files.items():
            if source.startswith("%sskills/%s/" % (base, name)):
                wanted[source[len("%sskills/%s/" % (base, name)):]] = source
            elif references and source == base + "README.md":
                wanted["references/README.md"] = source
            elif references and any(source.startswith("%s%s/" % (base, d)) for d in CRATE_REFERENCE_DIRS):
                wanted["references/" + source[len(base):]] = source
        for filename in ROOT_REFERENCES.get(name, ()) if not base else ():
            if "docs/" + filename not in files:
                raise Failure("%s expects docs/%s in the tag" % (name, filename))
            wanted["references/" + filename] = "docs/" + filename
        bundles[name] = {destination: (source, files[source]["sha"], files[source]["mode"]) for destination, source in wanted.items()}
    if not bundles:
        raise Failure("the tag has no skill bundles")
    return bundles


def check_bundle_files(bundles):
    for name, entries in bundles.items():
        if name in (".", "..") or "/" in name or CHEZMOI_SPECIAL.search(name):
            raise Failure("bundle name %r would be read by chezmoi as an attribute or is not a plain name" % name)
        for destination, (source, _sha, mode) in entries.items():
            if mode not in ("100644", "100755"):  # an executable bit is dropped, as in every earlier import
                raise Failure("%s: %s has mode %s; only plain files are imported" % (name, source, mode))
            if destination.startswith("/") or any(part in ("", ".", "..") for part in destination.split("/")):
                raise Failure("%s: %s is not a plain relative path" % (name, destination))
            if any(CHEZMOI_SPECIAL.search(part) for part in destination.split("/")):
                raise Failure("%s: %s would be read by chezmoi as an attribute or dropped; rename support is not built" % (name, destination))


def fetch_files(repo, commit, bundles):
    """{(name, destination): bytes}, each checked against the blob hash in the commit's tree."""
    archive = tarfile.open(fileobj=io.BytesIO(gh("api", "repos/%s/tarball/%s" % (repo, commit))), mode="r:*")
    members = {}
    for member in archive.getmembers():
        if member.isfile():
            top, _, rest = member.name.partition("/")
            if not top.endswith(commit[:7]):
                raise Failure("the archive is not commit %s (found %s)" % (commit[:7], top))
            members[rest] = member
    contents = {}
    for name, entries in bundles.items():
        for destination, (source, sha, _mode) in entries.items():
            if source not in members:
                raise Failure("%s is in the tree but not in the archive" % source)
            data = archive.extractfile(members[source]).read()
            if not data:
                raise Failure("%s is empty; chezmoi would not deploy it" % source)
            if git_blob_sha(data) != sha:
                raise Failure("%s does not match its blob hash in the tag" % source)
            contents[(name, destination)] = data
    return contents


# --- the local tree ----------------------------------------------------------------------------


def local_files(bundle_dir):
    found = {}
    if bundle_dir.is_symlink():
        raise Failure("%s is a symlink; bundles hold plain files" % bundle_dir)
    for root, dirs, names in os.walk(bundle_dir):
        for directory in dirs:
            if (Path(root) / directory).is_symlink():
                raise Failure("%s is a symlink; bundles hold plain directories" % (Path(root) / directory))
        for filename in names:
            path = Path(root) / filename
            if path.is_symlink():
                raise Failure("%s is a symlink; bundles hold plain files" % path)
            found[path.relative_to(bundle_dir).as_posix()] = path.read_bytes()
    return found


def deployed_names(files):
    """Source file names as chezmoi apply deploys them (the executable_ attribute is not part of the name)."""
    return {"/".join(part.removeprefix("executable_") for part in path.split("/")): data for path, data in files.items()}


def diff_bundle(bundle_dir, wanted):
    """(added, changed, orphans) destination paths, sorted."""
    have = local_files(bundle_dir)  # also rejects a symlinked root, dangling or not; a missing directory gives {}
    added = sorted(d for d in wanted if d not in have)
    changed = sorted(d for d in wanted if d in have and have[d] != wanted[d])
    orphans = sorted(d for d in have if d not in wanted)
    return added, changed, orphans


def pins_in(text):
    return PIN_LINE.findall(text)


def write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(".%s.import" % path.name)
    temporary.write_bytes(data)
    os.replace(temporary, path)


# --- commands ----------------------------------------------------------------------------------


def do_import(args):
    source = Path(args.source)
    skills = source / CANONICAL_SKILLS
    if not skills.is_dir():
        raise Failure("no canonical skills tree at %s" % skills)
    version = args.tag[1:] if args.tag.startswith("v") else args.tag
    commit = resolve_tag(args.repo, args.tag)
    if args.expect_commit and not commit.startswith(args.expect_commit):
        raise Failure("tag %s is now commit %s, not %s: it moved" % (args.tag, commit, args.expect_commit))
    listing = gh_json("api", "repos/%s/git/trees/%s?recursive=1" % (args.repo, commit))
    if listing.get("truncated"):
        raise Failure("the tag's tree listing is truncated")
    bundles = plan_bundles(listing["tree"])
    check_bundle_files(bundles)
    contents = fetch_files(args.repo, commit, bundles)
    print("tag %s of %s = commit %s; %d bundles, %d files, every file matches its tree hash" % (args.tag, args.repo, commit, len(bundles), len(contents)))

    plan = {}
    for name, entries in bundles.items():
        wanted = {destination: contents[(name, destination)] for destination in entries}
        plan[name] = (wanted, *diff_bundle(skills / name, wanted))
    orphans = 0
    for name, (wanted, added, changed, gone) in sorted(plan.items()):
        orphans += len(gone)
        print("%-34s +%d added  ~%d changed  -%d orphan  =%d same" % (name, len(added), len(changed), len(gone), len(wanted) - len(added) - len(changed)))
        for label, paths in (("add", added), ("change", changed), ("ORPHAN", gone)):
            for path in paths:
                print("    %-7s %s/%s" % (label, name, path))

    pin_text = None
    if args.pins:
        config = source / MISE_CONFIG
        text = config.read_text(encoding="utf-8")
        found = pins_in(text)
        if len(found) != PIN_COUNT:
            raise Failure("expected %d Loop Engine pins in %s, found %d" % (PIN_COUNT, MISE_CONFIG, len(found)))
        pin_text = PIN_LINE.sub(lambda m: m.group(1) + version + m.group(3), text)
        print("pins: %s -> %s (%s)" % (", ".join(sorted({old for _a, old, _b in found})), version, MISE_CONFIG))

    if not args.apply:
        print("dry run: nothing written (add --apply)")
        return 0
    if orphans and not args.prune:
        print("refusing to apply: %d orphan file(s) in the bundles (inspect them, then add --prune)" % orphans, file=sys.stderr)
        return 3
    for name, (wanted, added, changed, gone) in plan.items():
        for destination in added + changed:
            write_atomic(skills / name / destination, wanted[destination])
        for destination in gone:
            (skills / name / destination).unlink()
        for root, dirs, _names in os.walk(skills / name, topdown=False):  # drop directories the prune emptied
            for directory in dirs:
                try:
                    (Path(root) / directory).rmdir()
                except OSError:
                    pass
    if pin_text is not None:
        write_atomic(source / MISE_CONFIG, pin_text.encode("utf-8"))
    print("applied to %s" % source)
    print("next: review git diff; chezmoi --source %s apply --dry-run --verbose ~/.local/share/agent-harness/canonical/skills ~/.config/mise/config.toml," % source)
    print("      get approval, apply those targets, then run: import_release_skills.py verify-deployed --source %s" % source)
    return 0


def deployed_root():
    return Path(os.environ.get("AGENT_HARNESS_CANONICAL_ROOT") or Path.home() / ".local/share/agent-harness/canonical") / "skills"


def do_verify(args):
    skills = Path(args.source) / CANONICAL_SKILLS
    names = args.names or sorted(p.name for p in skills.iterdir() if (p / "SKILL.md").is_file())
    deployed = deployed_root()
    problems = []
    for name in names:
        if not (skills / name / "SKILL.md").is_file():
            problems.append("%s: no such bundle in the source" % name)
            continue
        want, have = deployed_names(local_files(skills / name)), (local_files(deployed / name) if (deployed / name).is_dir() else None)
        if have is None:
            problems.append("%s: not deployed at %s" % (name, deployed / name))
        else:
            problems += ["%s: missing from the deployment: %s" % (name, p) for p in sorted(set(want) - set(have))]
            problems += ["%s: differs in the deployment: %s" % (name, p) for p in sorted(p for p in set(want) & set(have) if want[p] != have[p])]
            problems += ["%s: ORPHAN in the deployment (apply does not delete it): %s" % (name, p) for p in sorted(set(have) - set(want))]
        for harness in HARNESS_SKILL_DIRS:
            link = Path.home() / harness / name
            if link.exists() or link.is_symlink():
                if not link.is_symlink() or link.resolve() != (deployed / name).resolve():
                    problems.append("%s: %s does not link to %s" % (name, link, deployed / name))
            elif harness != ".agents/skills":
                problems.append("%s: no link at %s" % (name, link))
    for problem in problems:
        print(problem)
    print("%d bundle(s) checked, %d problem(s)" % (len(names), len(problems)))
    return 1 if problems else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    default_source = os.environ.get("CHEZMOI_SOURCE_DIR") or str(Path.home() / ".local/share/chezmoi")
    commands = parser.add_subparsers(dest="command", required=True)
    importing = commands.add_parser("import", help="show or apply a release tag's skill bundles")
    importing.add_argument("tag")
    importing.add_argument("--repo", default=DEFAULT_REPO)
    importing.add_argument("--expect-commit", help="fail unless the tag resolves to a commit starting with this")
    importing.add_argument("--pins", action="store_true", help="also move the four mise tool pins to the tag's version")
    importing.add_argument("--apply", action="store_true")
    importing.add_argument("--prune", action="store_true", help="with --apply: delete orphan files in the bundles")
    verifying = commands.add_parser("verify-deployed", help="check the deployed bundles and harness links against the source")
    verifying.add_argument("names", nargs="*")
    for command in (importing, verifying):
        command.add_argument("--source", default=default_source, help="chezmoi source (default: CHEZMOI_SOURCE_DIR, else ~/.local/share/chezmoi)")
    args = parser.parse_args(argv)
    try:
        return do_import(args) if args.command == "import" else do_verify(args)
    except Failure as error:
        print("import_release_skills: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
