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


if __name__ == "__main__":
    unittest.main()
