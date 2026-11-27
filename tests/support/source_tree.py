"""The source tree the tests in this folder run chezmoi on, with no network.

chezmoi downloads every archive in .chezmoiexternal.toml whenever it reads the source (`managed`, `cat`, `apply`, `status`, ... for any
target; only `execute-template` and `data` do not). No flag turns that off: `--exclude=externals` and `--refresh-externals=never` still
download on an empty cache. A GitHub 503 on one of those archives once failed the whole profile-coverage step (the CI run of dotfiles#907).
These tests check what the source declares, not what an upstream archive holds, so they read a copy of the source in which each archive
URL points at a small archive generated here (`file://`), shaped by that external's own `include` pattern. Everything else in the copy is
the real file, so the real chezmoi still reads the real externals table, and templates that read `.chezmoiexternal.toml` (the seat files)
still can.

`chezmoi_env()` also points HTTPS_PROXY at a closed port, so a test that reaches the network anyway fails on every run, with the address
in the message, instead of once in a while when GitHub is slow.
"""
import atexit
import io
import os
import re
import shutil
import tarfile
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EXTERNALS = ".chezmoiexternal.toml"
# A `url = "....tar.gz"` line and the first `include = ["..."]` after it in the same table.
ARCHIVE = re.compile(r'url = "(https://[^"\n]+\.tar\.gz)"\n(?:(?!\n\[)[^\n]*\n)*?\s*include = \["([^"\n]+)"\]')
_source = None


def _link_or_copy(src, dst):
    try:
        os.link(src, dst)
    except OSError:  # another filesystem
        shutil.copy2(src, dst)


def _stand_in_archive(include):
    """A .tar.gz with one file that `include` (for example `*/skills/review-map/**`) matches, under one top folder like a GitHub archive."""
    if not (include.startswith("*/") and include.endswith("/**")):
        raise AssertionError("tests/support/source_tree.py cannot build an archive for include %r: teach _stand_in_archive its shape" % include)
    # SKILL.md is the name tests/profiles/test_formal_verification.py looks for in the statechart external: change both together.
    member = "top/" + include[2:-2] + "/SKILL.md"
    data = b"stand-in for the pinned archive; see tests/support/source_tree.py\n"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(member)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def source():
    """The path of the copy, made once per process and removed when the process ends."""
    global _source
    if _source is None:
        root = Path(tempfile.mkdtemp(prefix="dotfiles-source-"))
        atexit.register(shutil.rmtree, root, ignore_errors=True)
        copy = root / "source"
        shutil.copytree(REPO, copy, symlinks=True, ignore=shutil.ignore_patterns(".git"), copy_function=_link_or_copy)
        text = (REPO / EXTERNALS).read_text()
        for n, (url, include) in enumerate(ARCHIVE.findall(text)):
            stand_in = root / ("archive-%d.tar.gz" % n)
            stand_in.write_bytes(_stand_in_archive(include))
            text = text.replace(url, stand_in.as_uri())
        if re.search(r'url\s*=\s*"https?://', text):
            raise AssertionError("%s still has an https URL after the stand-ins: a test would download it" % EXTERNALS)
        (copy / EXTERNALS).unlink()  # a hard link to the repo's file, so write a new one
        (copy / EXTERNALS).write_text(text)
        _source = copy
    return _source


def chezmoi_env(home, **extra):
    """The environment for a chezmoi subprocess: HOME set, no proxy exemptions, and a proxy that refuses every connection."""
    env = {k: v for k, v in os.environ.items() if k.upper() not in ("NO_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY")}
    env.update(HOME=str(home), HTTPS_PROXY="http://127.0.0.1:1", HTTP_PROXY="http://127.0.0.1:1", **extra)
    return env
