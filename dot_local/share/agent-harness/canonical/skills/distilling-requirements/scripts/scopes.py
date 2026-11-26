"""Shared by history_signals.py and surface_coverage.py: turn `--scope` values into repo-relative paths."""
import os


def repo_relative(repo, value):
    """A --scope value as a repo-relative path: "" for the whole repo (`.`), an absolute path inside the repo made relative; None when it is empty or lies outside the repo."""
    value = (value or "").strip()
    if not value:
        return None
    if os.path.isabs(value):
        value = os.path.relpath(os.path.realpath(value), os.path.realpath(repo))
        if value == ".." or value.startswith(".." + os.sep):
            return None
    path = os.path.normpath(value)
    return "" if path == "." else path.strip("/")


def parse_scopes(repo, values):
    """Repo-relative scope paths from the raw --scope values (each may hold several, comma-separated): [] when one of them is `.` (the whole repo), None when one is bad."""
    out = [repo_relative(repo, v) for raw in values for v in (raw.split(",") if raw.strip() else [raw])]
    if None in out:
        return None
    return [] if "" in out else out
