#!/usr/bin/env python3
"""Exhaustively minimize a reviewed prompt-edit palette against a JSON oracle."""
import argparse
import hashlib
import itertools
import json
import pathlib
import subprocess
import sys


def digest(data):
    return hashlib.sha256(data).hexdigest()


def private_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")
    path.chmod(0o600)


def load_palette(source, manifest):
    if digest(source) != manifest["sourceSha256"]:
        raise ValueError("Source digest changed")
    start, end = manifest["editableRange"]
    if not 0 <= start <= end <= len(source):
        raise ValueError("Invalid editable range")
    edits = sorted(manifest["edits"], key=lambda e: e["start"])
    ids = set()
    previous_end = start
    for edit in edits:
        old, new = edit["old"].encode(), edit["new"].encode()
        left, right = edit["start"], edit["start"] + len(old)
        if edit["id"] in ids or not old or old == new:
            raise ValueError("Edit ids must be unique; edits must change nonempty original text")
        if left < previous_end or not start <= left <= right <= end:
            raise ValueError("Overlapping edit or edit outside approved range")
        if source[left:right] != old:
            raise ValueError("Original edit text does not match immutable source")
        for pleft, pright in manifest.get("protectedRanges", []):
            if not 0 <= pleft <= pright <= len(source):
                raise ValueError("Invalid protected range")
            if left < pright and right > pleft:
                raise ValueError("Edit touches a protected range")
        source[:left].decode("utf-8")
        source[:right].decode("utf-8")
        ids.add(edit["id"])
        previous_end = right
    if not edits or not manifest.get("context"):
        raise ValueError("Need a reviewed nonempty palette and frozen context")
    return edits


def patch(source, edits):
    result = source
    for edit in reversed(edits):
        left = edit["start"]
        result = result[:left] + edit["new"].encode() + result[left + len(edit["old"].encode()):]
    return result


class Search:
    def __init__(self, source, manifest, output, command, budget, controls_every):
        self.source = source
        self.manifest = manifest
        self.edits = load_palette(source, manifest)
        ceiling = manifest["context"]["budgetCeiling"]
        if type(ceiling) is not int or not 4 <= budget <= ceiling:
            raise ValueError("Requested budget exceeds the approved manifest ceiling")
        self.output = output
        self.command = command
        self.budget = budget
        self.controls_every = controls_every
        self.used = 0
        self.trials = 0
        self.cache = {}
        self.context_files = {
            str(pathlib.Path(p).resolve()): digest(pathlib.Path(p).read_bytes())
            for p in manifest["contextFiles"]
        }
        self.context_digest = digest(json.dumps({
            "context": manifest["context"], "files": self.context_files,
            "source": digest(source), "edits": self.edits, "oracle": command,
        }, sort_keys=True).encode())

    def check_context(self):
        for path, expected in self.context_files.items():
            if digest(pathlib.Path(path).read_bytes()) != expected:
                raise RuntimeError("Frozen context file changed")

    def probe(self, chosen, label, fresh=False):
        key = tuple(e["id"] for e in chosen)
        if not fresh and key in self.cache:
            return self.cache[key]
        if self.used >= self.budget:
            raise RuntimeError("Inference budget exhausted; minimum not established")
        self.check_context()
        self.trials += 1
        trial = self.output / f"trial-{self.trials:03d}"
        trial.mkdir(mode=0o700)
        prompt = trial / "prompt.txt"
        prompt.write_bytes(patch(self.source, chosen))
        prompt.chmod(0o600)
        request = {
            "prompt": str(prompt), "promptSha256": digest(prompt.read_bytes()),
            "outputDir": str(trial), "contextDigest": self.context_digest,
            "maxMessages": 1, "label": label,
        }
        # Reserve one inference before invoking the oracle. Timeouts/invalid output
        # still consume the reservation, so failure cannot erase budget usage.
        self.used += 1
        private_json(trial / "request.json", request)
        try:
            run = subprocess.run(self.command, input=json.dumps(request), text=True,
                                 capture_output=True, timeout=120)
            if run.returncode:
                raise RuntimeError("Oracle process failed (diagnostics withheld)")
            result = json.loads(run.stdout)
            if result.get("verdict") not in ("accept", "reject", "inconclusive"):
                raise RuntimeError("Invalid oracle verdict")
            if result.get("messages") != 1 or result.get("promptSha256") != request["promptSha256"]:
                raise RuntimeError("Oracle did not prove one inference and exact prompt identity")
            if result.get("contextDigest") != self.context_digest:
                raise RuntimeError("Oracle context identity mismatch")
            self.check_context()
        except (ValueError, subprocess.TimeoutExpired):
            raise RuntimeError("Oracle output invalid or timed out") from None
        private_json(trial / "result.json", result)
        row = {
            "trial": self.trials, "label": label, "editIds": list(key),
            "verdict": result["verdict"], "promptSha256": request["promptSha256"],
            "requestsUsed": self.used,
        }
        with (self.output / "trials.jsonl").open("a") as f:
            f.write(json.dumps(row) + "\n")
        (self.output / "trials.jsonl").chmod(0o600)
        print(json.dumps(row), flush=True)
        if result["verdict"] == "inconclusive":
            raise RuntimeError("Inconclusive probe; stop without a minimum claim")
        if key in self.cache and self.cache[key] != result["verdict"]:
            raise RuntimeError("Oracle changed its answer; stop without a minimum claim")
        self.cache[key] = result["verdict"]
        return result["verdict"]

    def expect(self, edits, verdict, label):
        if self.probe(edits, label, fresh=True) != verdict:
            raise RuntimeError("Control or confirmation failed")

    def controls(self):
        self.expect([], "reject", "negative-control")
        self.expect(self.edits, "accept", "positive-control")

    def run(self):
        self.controls()
        winner = None
        fresh_candidates = 0
        # Enumerate by edit count, then removed bytes, added bytes, and source order.
        # No monotonicity assumption: a failed group does not prune its subsets.
        for count in range(len(self.edits) + 1):
            combinations = sorted(itertools.combinations(self.edits, count), key=lambda c: (
                sum(len(e["old"].encode()) for e in c),
                sum(len(e["new"].encode()) for e in c), tuple(e["start"] for e in c)))
            for chosen in combinations:
                cached = tuple(e["id"] for e in chosen) in self.cache
                if self.probe(chosen, "search") == "accept":
                    winner = list(chosen)
                    break
                if not cached:
                    fresh_candidates += 1
                    if fresh_candidates % self.controls_every == 0:
                        self.controls()
            if winner is not None:
                break
        if winner is None:
            raise RuntimeError("No accepted subset")
        self.expect(winner, "accept", "winner-confirmation")
        self.expect(winner, "accept", "winner-confirmation")
        for edit in winner:
            reduced = [e for e in winner if e["id"] != edit["id"]]
            self.expect(reduced, "reject", "remove-" + edit["id"])
            self.expect(reduced, "reject", "remove-" + edit["id"])
        self.expect([], "reject", "final-negative-control")
        self.expect(winner, "accept", "final-winner-control")
        final = self.output / "minimal-prompt.txt"
        final.write_bytes(patch(self.source, winner))
        final.chmod(0o600)
        return {
            "status": "palette-minimum-observed", "contextDigest": self.context_digest,
            "sourceSha256": digest(self.source), "resultSha256": digest(final.read_bytes()),
            "edits": winner, "editCount": len(winner),
            "removedBytes": sum(len(e["old"].encode()) for e in winner),
            "addedBytes": sum(len(e["new"].encode()) for e in winner),
            "requestsUsed": self.used, "budget": self.budget,
            "claim": "Minimum under this fixed palette and observed stable oracle; not a global rewrite minimum",
            "functionalValidation": "pending",
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=pathlib.Path)
    parser.add_argument("manifest", type=pathlib.Path)
    parser.add_argument("output", type=pathlib.Path)
    parser.add_argument("--budget", type=int, default=92)
    parser.add_argument("--controls-every", type=int, default=16)
    parser.add_argument("--oracle", nargs="+", required=True)
    args = parser.parse_args()
    if args.budget < 4 or args.controls_every < 1:
        parser.error("Budget >=4 and control interval >=1 required")
    output = args.output.resolve()
    output.mkdir(mode=0o700)  # Refuse reuse: no evidence/cache carried across runs.
    source = args.source.read_bytes()
    manifest = json.loads(args.manifest.read_text())
    search = None
    try:
        search = Search(source, manifest, output, args.oracle, args.budget, args.controls_every)
        private_json(output / "frozen.json", {
            "manifest": manifest, "contextDigest": search.context_digest,
            "contextFiles": search.context_files, "oracle": args.oracle,
        })
        result = search.run()
        private_json(output / "result.json", result)
        print(json.dumps({"status": result["status"], "result": str(output / "result.json")}))
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        private_json(output / "result.json", {
            "status": "blocked", "reason": str(error),
            "requestsUsed": search.used if search else 0,
            "functionalValidation": "not-run",
        })
        print(json.dumps({"status": "blocked", "reason": str(error)}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
