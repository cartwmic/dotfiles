"""Continuous frontmost-app sampling for the agent Chrome focus journeys.

Reading 'lsappinfo front' once before and once after a step misses a steal that comes and goes: the
launcher's own hand-back gives the front back within seconds, so an after-check sees the original app
again and calls the launch clean. FrontSampler samples on a thread (default every 50 ms) from before the
launch until the journey is over, records every period in which the front differs from the baseline, and
can assert that there were none - reporting when each happened and how long it lasted.
"""
import subprocess
import threading
import time


def front_asn():
    """The frontmost app's ASN. lsappinfo, not osascript/System Events: osascript needs Automation (TCC)
    consent from the calling app, and the consent dialog itself takes focus."""
    r = subprocess.run(["lsappinfo", "front"], capture_output=True, text=True, timeout=15)
    if r.returncode != 0 or not r.stdout.strip():
        raise RuntimeError("could not read the frontmost app (lsappinfo front): " + r.stderr.strip())
    return r.stdout.strip()


def front_name(asn):
    """A display name for an ASN, for reports; falls back to the ASN itself."""
    r = subprocess.run(["lsappinfo", "info", "-only", "name", asn], capture_output=True, text=True, timeout=15)
    if r.returncode != 0 or "=" not in r.stdout:
        return asn
    _, _, value = r.stdout.strip().partition("=")  # output looks like '"LSDisplayName"="App Name"'
    return value.strip().strip('"') or asn


class FrontSampler:
    """Samples the frontmost app on a daemon thread. start() reads the baseline; every period after that
    in which the front is not the baseline is one excursion (with its start, end and the app it went to)."""

    def __init__(self, interval=0.05):
        self.interval = interval
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = None
        self._baseline = None
        self._baseline_name = None
        self._started_at = None
        self._open = None           # the excursion in progress, while the front is away from the baseline
        self._excursions = []
        self._error = None

    def start(self):
        self._baseline = front_asn()
        self._baseline_name = front_name(self._baseline)
        self._started_at = time.monotonic()
        self._thread = threading.Thread(target=self._run, daemon=True, name="front-sampler")
        self._thread.start()

    def _run(self):
        while not self._stop.wait(self.interval):
            try:
                asn = front_asn()
            except Exception as err:   # a failed sample must not kill the sampler
                with self._lock:
                    self._error = str(err)
                continue
            with self._lock:
                self._record(asn)

    def _record(self, asn):
        now = time.monotonic()
        away = asn != self._baseline
        if away and self._open is None:
            self._open = {"start": now, "to": asn, "to_name": front_name(asn), "end": None}
        elif not away and self._open is not None:
            self._open["end"] = now
            self._excursions.append(self._open)
            self._open = None

    def stop(self):
        """Stop sampling; an excursion still in progress is closed with no end (the front never came back)."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
        with self._lock:
            if self._open is not None:
                self._excursions.append(self._open)
                self._open = None

    def excursions(self):
        with self._lock:
            found = [dict(e) for e in self._excursions]
            if self._open is not None:
                found.append(dict(self._open))   # a change still in progress counts too
            return found

    def describe(self):
        lines = []
        for e in self.excursions():
            at = e["start"] - self._started_at
            if e["end"] is None:
                lines.append("front went from %s to %s %.2fs into the run and is still away"
                             % (self._baseline_name, e["to_name"], at))
            else:
                lines.append("front went from %s to %s %.2fs into the run, for %.2fs"
                             % (self._baseline_name, e["to_name"], at, e["end"] - e["start"]))
        return "; ".join(lines)

    def assert_unchanged(self, step):
        if self._error is not None:
            raise AssertionError("%s: sampling the frontmost app failed: %s" % (step, self._error))
        if self.excursions():
            raise AssertionError("%s changed the frontmost app (baseline %s): %s"
                                 % (step, self._baseline_name, self.describe()))
