"""Bounded-memory and compatibility checks for the store readers.

Everything runs on a small synthetic store in a temp directory. Nothing here
touches the real recap store.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import tempfile
import tracemalloc
import unittest
import unittest.mock
from pathlib import Path

IMPLEMENTATION = Path(__file__).resolve().parent / "session_recap.py"
spec = importlib.util.spec_from_file_location("session_recap_under_test", IMPLEMENTATION)
recap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recap)

PAYLOAD = "x" * 150_000  # one heavy record is about 150 KB, like real coverage units
SOURCES = ("s-a", "s-b", "s-c", "s-d")


def record(index: int, source_id: str, status: str = "published", version: int = 2) -> dict:
    day = f"2026-10-{10 + index % 5:02d}"
    value = {
        "schema_version": version,
        "record_id": f"r{index:04d}",
        "source_kind": "pi",
        "source_id": source_id,
        "kind": "single",
        "status": status,
        "summary": f"summary {index}",
        "created_at": f"{day}T00:00:{index % 60:02d}.000000+00:00",
        "published_at": f"{day}T00:00:{index % 60:02d}.000000+00:00",
        "metadata": {"pi": {"nativeSessionId": source_id, "coverage": {"units": [PAYLOAD]}}},
        "annotations": {},
    }
    return value


class ReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data_home = Path(self.temp.name) / "data"
        self.root = self.data_home / "session-recap"
        self.records = []
        for index in range(120):  # about 18 MB on disk
            self.records.append(record(index, SOURCES[index % len(SOURCES)]))
        for value in self.records:
            self.put(value)
        self.store_bytes = sum(p.stat().st_size for p in (self.root / "records").glob("*/*.json"))

    def put(self, value: dict, name: str | None = None, day: str | None = None) -> Path:
        directory = self.root / "records" / (day or value["created_at"][:10])
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{name or value['record_id']}.json"
        path.write_text(recap._json_text(value), encoding="utf-8")
        return path

    def run_cli(self, *argv: str) -> tuple[int, str]:
        code, out, _ = self.run_cli_err(*argv)
        return code, out

    def run_cli_err(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        env = {"XDG_DATA_HOME": str(self.data_home), "XDG_CONFIG_HOME": str(Path(self.temp.name) / "config")}
        with unittest.mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = recap.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_store_is_large_enough_for_the_bound_to_mean_something(self) -> None:
        self.assertGreater(self.store_bytes, 15_000_000)

    def test_scoped_list_returns_exactly_the_matching_records(self) -> None:
        code, everything = self.run_cli("list", "--json")
        self.assertEqual(code, 0)
        code, scoped = self.run_cli("list", "--json", "--source-kind", "pi", "--source-id", "s-b", "--status", "published")
        self.assertEqual(code, 0)
        full, part = json.loads(everything), json.loads(scoped)
        expected = [r for r in full["records"] if r["source_id"] == "s-b"]
        self.assertEqual(part["records"], expected)
        self.assertEqual(len(expected), 30)
        self.assertEqual(part["presentation"]["records"], {r["record_id"]: full["presentation"]["records"][r["record_id"]] for r in expected})
        self.assertEqual(part["presentation"]["time_zone"], full["presentation"]["time_zone"])

    def test_scoped_list_peak_memory_is_bounded_but_unscoped_is_not(self) -> None:
        tracemalloc.start()
        try:
            self.run_cli("list", "--json", "--source-kind", "pi", "--source-id", "s-b", "--status", "published")
            _, scoped_peak = tracemalloc.get_traced_memory()
            tracemalloc.reset_peak()
            self.run_cli("list", "--json")
            _, full_peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        # Scoped: its 30 matches (a quarter of the store) plus one file in flight.
        matched_bytes = self.store_bytes // len(SOURCES)
        self.assertLess(scoped_peak, matched_bytes * 5)
        self.assertLess(scoped_peak, self.store_bytes * 0.9)
        # Control: unscoped still needs the whole result, so the bound is not vacuous.
        self.assertGreater(full_peak, scoped_peak * 2.5)

    def test_non_matching_records_are_never_retained(self) -> None:
        tracemalloc.start()
        try:
            code, output = self.run_cli("list", "--json", "--source-id", "no-such-session")
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(json.loads(output)["records"], [])
        self.assertLess(peak, 2_000_000)  # about one file in flight, not 18 MB

    def test_unsupported_schema_still_fails_even_if_the_filter_would_skip_it(self) -> None:
        self.put(record(900, "s-z", version=7))
        code, out, err = self.run_cli_err("list", "--json", "--source-id", "s-a")
        self.assertNotEqual(code, 0)
        self.assertIn("unsupported record schema", err)
        self.assertEqual(out, "")

    def test_read_ignores_unrelated_unreadable_files(self) -> None:
        bad = self.root / "records" / "2026-10-19"
        bad.mkdir()
        (bad / "broken.json").write_text("{not json", encoding="utf-8")
        code, output = self.run_cli("read", "r0007", "--json")
        self.assertEqual(json.loads(output)["record"]["record_id"], "r0007")

    def test_read_opens_one_file_not_the_store(self) -> None:
        with unittest.mock.patch.object(recap, "_read_json", wraps=recap._read_json) as spy:
            self.run_cli("read", "r0007", "--json")
        # fast path: the named file for the lookup, then the re-read under the lock
        self.assertLessEqual(spy.call_count, 2)

    def test_over_long_id_is_just_not_found(self) -> None:
        code, out, err = self.run_cli_err("read", "r" * 400, "--json")
        self.assertNotEqual(code, 0)
        self.assertIn("not found or ambiguous", err)

    def test_read_falls_back_to_content_match_for_a_renamed_file(self) -> None:
        value = record(950, "s-a")
        self.put(value, name="not-the-id")
        code, output = self.run_cli("read", "r0950", "--json")
        self.assertEqual(json.loads(output)["record"]["record_id"], "r0950")

    def test_duplicate_ids_are_still_ambiguous(self) -> None:
        value = record(960, "s-a")
        self.put(value)
        self.put(value, day="2026-10-30")
        code, out, err = self.run_cli_err("read", "r0960", "--json")
        self.assertNotEqual(code, 0)
        self.assertIn("not found or ambiguous", err)

    def test_hostile_ids_are_just_not_found(self) -> None:
        for bad in ("../x", "*", "a/b", ".", "..", "", "r00*"):
            with self.subTest(bad=bad):
                code, out, err = self.run_cli_err("read", bad, "--json")
                self.assertNotEqual(code, 0)
                self.assertIn("not found or ambiguous", err)
                self.assertEqual(out, "")

    def test_annotate_changes_only_the_named_namespace_of_one_record(self) -> None:
        before = {p.name: p.read_bytes() for p in (self.root / "records").glob("*/*.json")}
        code, output = self.run_cli("annotate", "r0003", "--namespace", "herdr", "--metadata-json", '{"pane_id": "p1"}')
        self.assertEqual(json.loads(output)["record"]["annotations"], {"herdr": {"pane_id": "p1"}})
        after = {p.name: p.read_bytes() for p in (self.root / "records").glob("*/*.json")}
        changed = [name for name in before if before[name] != after[name]]
        self.assertEqual(changed, ["r0003.json"])
        stored = json.loads(after["r0003.json"])
        self.assertEqual(stored["summary"], "summary 3")
        self.assertEqual(stored["metadata"], self.records[3]["metadata"])


    def owned(self, index: int, source_id: str, pi: object, version: int = 2, status: str = "published") -> dict:
        value = record(index, source_id, status=status, version=version)
        value["metadata"] = {"pi": pi} if pi is not ... else {}
        if version == 1:
            value.pop("metadata"); value["generic_annotations"] = {}
        return value

    def test_pi_owner_matches_the_adapter_owner_rule_not_source_id(self) -> None:
        cases = {
            "o-session": self.owned(800, "history-1", {"sessionId": "me", "nativeSessionId": "other"}),   # sessionId wins
            "o-native": self.owned(801, "history-2", {"nativeSessionId": "me"}),                         # legacy: native only
            "o-null": self.owned(802, "history-3", {"sessionId": None, "nativeSessionId": "me"}),         # null falls back like ??
            "x-other-owner": self.owned(803, "me", {"sessionId": "someone-else", "nativeSessionId": "me"}),  # source_id==me but owner differs
            "x-no-pi": self.owned(804, "me", ...),
            "x-pi-not-object": self.owned(805, "me", "me"),
            "x-v1": self.owned(806, "me", {"sessionId": "me"}, version=1),
            "x-unpublished": self.owned(807, "me", {"sessionId": "me"}, status="failed"),
        }
        for value in cases.values():
            self.put(value)
        code, out = self.run_cli("list", "--json", "--source-kind", "pi", "--status", "published", "--pi-owner", "me")
        self.assertEqual(code, 0)
        ids = sorted(r["record_id"] for r in json.loads(out)["records"])
        self.assertEqual(ids, sorted(cases[k]["record_id"] for k in ("o-session", "o-native", "o-null")))

    def test_pi_owner_agrees_with_a_python_rewrite_of_the_adapter_predicate(self) -> None:
        # Cross-check against the adapter's expression on every fixture owner shape.
        shapes = [{"sessionId": "me"}, {"nativeSessionId": "me"}, {"sessionId": None, "nativeSessionId": "me"},
                  {"sessionId": "", "nativeSessionId": "me"}, {"sessionId": 5}, {}, {"sessionId": "me", "nativeSessionId": "x"},
                  {"sessionId": False, "nativeSessionId": "me"}, {"sessionId": 0}, {"sessionId": ["me"]}, {"nativeSessionId": ["me"]}]
        for index, pi in enumerate(shapes):
            self.put(self.owned(700 + index, f"h-{index}", pi))
        code, out = self.run_cli("list", "--json", "--pi-owner", "me")
        got = {r["record_id"] for r in json.loads(out)["records"] if r["record_id"].startswith("r07")}
        expect = {f"r{700 + i:04d}" for i, pi in enumerate(shapes)
                  if (pi.get("sessionId") if pi.get("sessionId") is not None else pi.get("nativeSessionId")) == "me"}
        self.assertEqual(got, expect)

    def test_pi_owner_scoped_memory_is_bounded(self) -> None:
        for index in range(4):
            self.put(self.owned(600 + index, "history-x", {"sessionId": "mine"}))
        tracemalloc.start()
        try:
            code, out = self.run_cli("list", "--json", "--source-kind", "pi", "--status", "published", "--pi-owner", "mine")
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(len(json.loads(out)["records"]), 4)
        self.assertLess(peak, 4 * 150_000 * 5)

    def test_unfiltered_output_is_unchanged_by_the_new_option(self) -> None:
        code, out = self.run_cli("list", "--json")
        self.assertEqual(len(json.loads(out)["records"]), len(self.records))  # no flag: every fixture record, as before
        self.assertEqual(json.loads(self.run_cli("list", "--json", "--pi-owner", "nobody")[1])["records"], [])

    def grow(self, sid: str, count: int, start: int = 2000) -> None:
        for index in range(start, start + count):
            value = record(index, sid)
            value["metadata"] = {"pi": {"nativeSessionId": sid, "historyId": "h", "scope": "current-context", "fingerprint": "f%d" % index,
                                         "coverage": {"anchor": "a%d" % index, "units": [{"id": "u%d" % n, "v": "x" * 2000} for n in range(75)]}}}
            self.put(value)

    def peak(self, *argv: str) -> tuple[int, dict]:
        tracemalloc.start()
        try:
            code, out = self.run_cli(*argv)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertEqual(code, 0)
        return peak, json.loads(out)

    def test_omit_units_projection_is_the_same_record_minus_units(self) -> None:
        self.grow("grow-a", 3)
        full = json.loads(self.run_cli("list", "--json", "--source-id", "grow-a")[1])["records"]
        lite = json.loads(self.run_cli("list", "--json", "--source-id", "grow-a", "--omit-coverage-units")[1])["records"]
        self.assertEqual(len(full), 3); self.assertEqual(len(lite), 3)
        for f, l in zip(full, lite):
            cov = f["metadata"]["pi"]["coverage"]
            expected = json.loads(json.dumps(f))
            del expected["metadata"]["pi"]["coverage"]["units"]
            expected["metadata"]["pi"]["coverage"]["unitsOmitted"] = len(cov["units"])
            self.assertEqual(l, expected)
            self.assertNotIn("units", l["metadata"]["pi"]["coverage"])
        # read still returns the units in full
        code, out = self.run_cli("read", full[0]["record_id"], "--json")
        self.assertEqual(json.loads(out)["record"]["metadata"]["pi"]["coverage"]["units"], full[0]["metadata"]["pi"]["coverage"]["units"])

    def test_records_without_units_or_pi_pass_through_unchanged(self) -> None:
        self.put(self.owned(990, "plain", {"sessionId": "x"}))      # pi object without coverage
        self.put(self.owned(991, "plain", ...))                      # no metadata.pi
        self.put(self.owned(992, "plain", {"coverage": {"anchor": None}}))  # coverage without units
        a = json.loads(self.run_cli("list", "--json", "--source-id", "plain")[1])["records"]
        b = json.loads(self.run_cli("list", "--json", "--source-id", "plain", "--omit-coverage-units")[1])["records"]
        self.assertEqual(a, b)

    def test_projection_memory_does_not_grow_with_a_sessions_record_count(self) -> None:
        self.grow("grow-b", 20)
        small, _ = self.peak("list", "--json", "--source-kind", "pi", "--source-id", "grow-b", "--omit-coverage-units")
        full_small, _ = self.peak("list", "--json", "--source-kind", "pi", "--source-id", "grow-b")
        self.grow("grow-b", 140, start=3000)   # session grows 8x
        big, data = self.peak("list", "--json", "--source-kind", "pi", "--source-id", "grow-b", "--omit-coverage-units")
        full_big, _ = self.peak("list", "--json", "--source-kind", "pi", "--source-id", "grow-b")
        self.assertEqual(len(data["records"]), 160)
        self.assertLess(big, small * 3 + 2_000_000)     # 8x the records, projection peak stays near flat; absolute slack avoids allocator flake
        self.assertLess(big, full_big / 8)              # and is far below what the unprojected list needs
        self.assertGreater(full_big, big * 8)           # control: the unprojected list grows with the session
        self.assertGreater(full_big, full_small * 4)

    # --- list reads only the records it returns (cartwmic/dotfiles#15) ---

    def full_reads(self, *argv: str) -> list[str]:
        """Names of the record files the list opened, in order."""
        with unittest.mock.patch.object(recap, "_read_json", wraps=recap._read_json) as spy:
            code, _ = self.run_cli(*argv)
        self.assertEqual(code, 0)
        return [call.args[0].name for call in spy.call_args_list if call.args[0].parent.parent.name == "records"]

    def test_first_list_builds_the_cache_and_later_scoped_lists_read_only_their_matches(self) -> None:
        first = self.full_reads("list", "--json", "--source-kind", "pi", "--source-id", "s-b")
        self.assertEqual(len(first), len(self.records))  # one pass over every file builds the cache
        self.assertTrue((self.root / recap.LIST_INDEX_NAME).is_file())
        second = self.full_reads("list", "--json", "--source-kind", "pi", "--source-id", "s-b")
        expected = {f"{r['record_id']}.json" for r in self.records if r["source_id"] == "s-b"}
        self.assertEqual(sorted(second), sorted(expected))  # exactly the 30 it returns, none of the other 90
        self.assertEqual(self.full_reads("list", "--json", "--source-id", "no-such-session"), [])

    def test_cached_list_output_is_identical_to_the_uncached_output(self) -> None:
        argv = ("list", "--json", "--source-kind", "pi", "--status", "published", "--omit-coverage-units")
        cold = self.run_cli(*argv)
        self.assertTrue((self.root / recap.LIST_INDEX_NAME).is_file())
        self.assertEqual(self.run_cli(*argv), cold)
        (self.root / recap.LIST_INDEX_NAME).unlink()
        self.assertEqual(self.run_cli(*argv), cold)

    def test_pi_owner_lists_read_only_the_owners_records_once_cached(self) -> None:
        self.put(self.owned(500, "history-q", {"sessionId": "mine"}))
        self.run_cli("list", "--json", "--pi-owner", "mine")
        self.assertEqual(self.full_reads("list", "--json", "--pi-owner", "mine"), ["r0500.json"])

    def test_new_and_hand_placed_files_are_picked_up(self) -> None:
        self.run_cli("list", "--json")
        self.put(record(910, "s-a"))
        self.put(record(911, "s-a"), name="renamed", day="2026-10-31")
        ids = {r["record_id"] for r in json.loads(self.run_cli("list", "--json", "--source-id", "s-a")[1])["records"]}
        self.assertTrue({"r0910", "r0911"} <= ids)

    def test_an_edited_file_is_read_again_and_its_new_fields_apply(self) -> None:
        self.run_cli("list", "--json")
        path = self.put(record(0, "s-a", status="published"))
        value = json.loads(path.read_text(encoding="utf-8"))
        value.update(source_id="moved", status="failed", summary="a longer summary than before")
        path.write_text(recap._json_text(value), encoding="utf-8")
        moved = json.loads(self.run_cli("list", "--json", "--source-id", "moved")[1])["records"]
        self.assertEqual([r["record_id"] for r in moved], ["r0000"])
        old = json.loads(self.run_cli("list", "--json", "--source-id", "s-a")[1])["records"]
        self.assertNotIn("r0000", [r["record_id"] for r in old])

    def test_a_deleted_file_is_dropped_from_the_cache(self) -> None:
        self.run_cli("list", "--json")
        (self.root / "records" / self.records[3]["created_at"][:10] / "r0003.json").unlink()
        self.run_cli("list", "--json")
        entries = json.loads((self.root / recap.LIST_INDEX_NAME).read_text(encoding="utf-8"))["entries"]
        self.assertEqual(len(entries), len(self.records) - 1)

    def test_a_broken_cache_is_ignored_and_rebuilt(self) -> None:
        expected = self.run_cli("list", "--json", "--source-id", "s-c")
        for junk in ("{not json", "[]", '{"version": 2, "entries": {}}', '{"version": 1, "entries": []}'):
            with self.subTest(junk=junk):
                (self.root / recap.LIST_INDEX_NAME).write_text(junk, encoding="utf-8")
                self.assertEqual(self.run_cli("list", "--json", "--source-id", "s-c"), expected)

    def test_a_cached_unsupported_schema_still_fails_the_list(self) -> None:
        self.run_cli("list", "--json", "--source-id", "s-a")
        self.put(record(900, "s-z", version=7))
        for _ in range(2):  # uncached, then cached
            code, out, err = self.run_cli_err("list", "--json", "--source-id", "s-a")
            self.assertNotEqual(code, 0)
            self.assertIn("unsupported record schema", err)
            self.assertEqual(out, "")

    def test_an_unwritable_cache_does_not_fail_the_list(self) -> None:
        expected = self.run_cli("list", "--json", "--source-id", "s-d")
        (self.root / recap.LIST_INDEX_NAME).unlink()
        with unittest.mock.patch.object(recap, "_atomic_write_json", side_effect=PermissionError("read-only")):
            self.assertEqual(self.run_cli("list", "--json", "--source-id", "s-d"), expected)
        self.assertFalse((self.root / recap.LIST_INDEX_NAME).exists())

    def test_cache_is_not_a_record_and_is_never_listed_or_read_as_one(self) -> None:
        self.run_cli("list", "--json")
        code, out, err = self.run_cli_err("read", "list-index", "--json")
        self.assertNotEqual(code, 0)
        self.assertEqual(len(json.loads(self.run_cli("list", "--json")[1])["records"]), len(self.records))


if __name__ == "__main__":
    unittest.main()
