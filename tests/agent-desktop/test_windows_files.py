"""c9: the G14 files exist, read as Windows PowerShell 5.1, and windows/install.ps1 installs Vercel's tool once.

The G14 has PowerShell 5.1 only. These tests run under PowerShell 7 on Linux, so they cannot run 5.1. What they do:
  * parse every file and walk its syntax tree and tokens for forms only PowerShell 7 knows (the scanner is proven on planted
    fixtures first, so a scanner that finds nothing cannot pass);
  * keep the files ASCII (5.1 reads a file with no byte-order mark as ANSI);
  * compile the compiled client (agent-desktop-client.cs) as C# 5, the compiler that ships with Windows, and keep its list of key
    and modifier names the same as the worker's;
  * run install.ps1 against a stub release (stub curl.exe and tar.exe on PATH, a stub ScheduledTasks module): a fresh install,
    a wrong checksum, a second run that downloads and changes nothing, and the task it registers (one long-lived worker: one
    instance at a time, no time limit, started at logon, and a task of the old shape is registered again).
The G14 itself is not touched here.
Run: mise exec aqua:PowerShell/PowerShell@7.7.0 -- python3 -m unittest discover -s tests/agent-desktop -p test_windows_files.py
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import windows_testlib as wt
from windows_testlib import ASSET, RELEASE, VERSION, WINDOWS, Sandbox, WindowsTestCase, pwsh

PS1 = ("install.ps1", "agent-desktop.ps1")
FILES = PS1 + ("agent-desktop.cmd", "agent-desktop-client.cs")

# Walks a script's syntax tree and prints one JSON list of findings: PowerShell-7-only syntax and members.
SCANNER = r'''
param([string]$Path)
$errors = $null; $tokens = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Path, [ref]$tokens, [ref]$errors)
$found = New-Object System.Collections.ArrayList
foreach ($e in $errors) { [void]$found.Add("parse error: " + $e.Message + " line " + $e.Extent.StartLineNumber) }
$badTokens = 'QuestionQuestion', 'QuestionDot', 'QuestionQuestionEquals', 'QuestionLBracket', 'QuestionMark', 'AndAnd', 'OrOr'
foreach ($t in $tokens) { if ($badTokens -contains $t.Kind.ToString()) { [void]$found.Add("token " + $t.Kind + " line " + $t.Extent.StartLineNumber) } }
$badAst = 'TernaryExpressionAst', 'PipelineChainAst', 'ChainableAst'
$all = $ast.FindAll({ param($n) $true }, $true)
foreach ($n in $all) {
    $type = $n.GetType().Name
    if ($badAst -contains $type) { [void]$found.Add("syntax " + $type + " line " + $n.Extent.StartLineNumber) }
    if ($type -eq 'MemberExpressionAst' -or $type -eq 'InvokeMemberExpressionAst') {
        $m = $n.Member.Extent.Text
        if ($m -in 'ArgumentList', 'ProcessPath', 'GetRelativePath') { [void]$found.Add("member ." + $m + " line " + $n.Extent.StartLineNumber) }
    }
    if ($type -eq 'VariableExpressionAst' -and $n.VariablePath.UserPath -in 'IsWindows', 'IsLinux', 'IsMacOS', 'PSStyle') {
        [void]$found.Add("variable " + $n.VariablePath.UserPath + " line " + $n.Extent.StartLineNumber)
    }
    if ($type -eq 'FileRedirectionAst' -or $type -eq 'MergingRedirectionAst') {
        if ($n.FromStream.ToString() -in 'Error', 'All') { [void]$found.Add("error-stream redirection line " + $n.Extent.StartLineNumber) }
    }
    if ($type -eq 'CommandParameterAst' -and $n.ParameterName -in 'Parallel', 'AsHashtable', 'AsByteStream', 'AdditionalChildPath', 'SkipHttpErrorCheck') {
        [void]$found.Add("parameter -" + $n.ParameterName + " line " + $n.Extent.StartLineNumber)
    }
    if ($type -eq 'CommandAst') {
        $name = $n.GetCommandName()
        if ($name -eq 'Join-Path') {
            $positional = @($n.CommandElements | Select-Object -Skip 1 | Where-Object { $_.GetType().Name -ne 'CommandParameterAst' })
            $named = @($n.CommandElements | Where-Object { $_.GetType().Name -eq 'CommandParameterAst' })
            if ($positional.Count + $named.Count -gt 2) { [void]$found.Add("Join-Path with more than Path and ChildPath, line " + $n.Extent.StartLineNumber) }
        }
        if ($name -in 'ConvertFrom-Json') {
            if (@($n.CommandElements | Where-Object { $_.GetType().Name -eq 'CommandParameterAst' -and $_.ParameterName -eq 'Depth' }).Count) {
                [void]$found.Add("ConvertFrom-Json -Depth (7 only), line " + $n.Extent.StartLineNumber)
            }
        }
        if ($name -in 'Test-Json', 'Get-Error') { [void]$found.Add("command " + $name + " line " + $n.Extent.StartLineNumber) }
    }
    if ($type -eq 'StringConstantExpressionAst' -and $n.Value -in 'utf8NoBOM') { [void]$found.Add("encoding utf8NoBOM line " + $n.Extent.StartLineNumber) }
}
ConvertTo-Json -InputObject @($found) -Compress
'''

# One planted use of every form the scanner must flag. Each is valid PowerShell 7.
PLANTED = {
    "ternary": "$x = $true ? 1 : 2",
    "null-coalescing": "$x = $a ?? $b",
    "null-conditional member": "$x = ${a}?.Length",
    "null-conditional index": "$x = ${a}?[0]",
    "null-coalescing assignment": "$a ??= 1",
    "and-and chain": "Get-Item . && Get-Item .",
    "or-or chain": "Get-Item nope || Get-Item .",
    "ForEach-Object -Parallel": "1..3 | ForEach-Object -Parallel { $_ }",
    "ProcessStartInfo.ArgumentList": "$p = New-Object System.Diagnostics.ProcessStartInfo; $p.ArgumentList.Add('x')",
    "$IsWindows": "if ($IsWindows) { 1 }",
    "-AsHashtable": "'{}' | ConvertFrom-Json -AsHashtable",
    "three-argument Join-Path": "Join-Path 'a' 'b' 'c'",
    "Join-Path -AdditionalChildPath": "Join-Path 'a' 'b' -AdditionalChildPath 'c'",
    "-AsByteStream": "Get-Content x -AsByteStream",
    "utf8NoBOM": "'x' | Set-Content f -Encoding utf8NoBOM",
    "2>$null (stops the script on 5.1)": "& reg.exe query HKCU\\Environment 2>$null",
    "2>&1": "& tar.exe -xzf x 2>&1",
}


class Scanner:
    def __init__(self, tmp):
        self.script = Path(tmp) / "scan.ps1"
        self.script.write_text(SCANNER)

    def scan(self, path):
        r = subprocess.run([pwsh(), "-NoProfile", "-File", str(self.script), str(path)], capture_output=True, text=True, timeout=120)
        if r.returncode:
            raise AssertionError("scanner failed on %s: %s" % (path, r.stderr))
        return json.loads(r.stdout or "[]")


class FilesTest(WindowsTestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="rad-scan-")
        cls.scanner = Scanner(cls.tmpdir)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, True)

    def test_the_files_exist(self):
        for name in FILES:
            self.assertTrue((WINDOWS / name).is_file(), "windows/%s must exist" % name)

    def test_the_scanner_flags_every_planted_powershell_7_form(self):
        for label, code in PLANTED.items():
            f = Path(self.tmpdir) / "planted.ps1"
            f.write_text(code + "\n")
            self.assertTrue(self.scanner.scan(f), "the scanner missed: %s" % label)

    def test_the_scanner_passes_plain_5_1_code(self):
        f = Path(self.tmpdir) / "plain.ps1"
        f.write_text("$p = Join-Path 'a' 'b'\nif ($p -and (Test-Path $p)) { 'x' } else { 'y' }\n$s = [IO.Path]::Combine('a', 'b')\n")
        self.assertEqual(self.scanner.scan(f), [])

    def test_the_scripts_parse_and_use_no_powershell_7_form(self):
        for name in PS1:
            path = WINDOWS / name
            self.assertTrue(path.is_file(), "windows/%s must exist" % name)
            self.assertEqual(self.scanner.scan(path), [], name)

    def test_the_files_are_ascii_so_5_1_reads_them_as_written(self):
        for name in FILES:
            data = (WINDOWS / name).read_bytes()
            bad = [i for i, b in enumerate(data) if b > 127]
            self.assertEqual(bad, [], "windows/%s has non-ASCII bytes at %s" % (name, bad[:5]))

    def test_the_cmd_wrapper_calls_the_script_and_returns_its_exit_code(self):
        raw = (WINDOWS / "agent-desktop.cmd").read_bytes()
        text = raw.decode("ascii")
        self.assertIn("powershell.exe -NoProfile -ExecutionPolicy Bypass -File", text)
        self.assertIn("agent-desktop.ps1", text)
        self.assertIn("%*", text)
        self.assertRegex(text, r"exit /b %ERRORLEVEL%")
        self.assertEqual(raw.count(b"\n"), raw.count(b"\r\n"), "cmd.exe wants CRLF line ends")

    def test_the_compiled_client_knows_the_same_key_and_modifier_names_as_the_worker(self):
        ps = (WINDOWS / "agent-desktop.ps1").read_text()
        cs = (WINDOWS / "agent-desktop-client.cs").read_text()
        def ps_names(table):
            body = re.search(r"\$script:%s = @\{(.*?)\n\}" % table, ps, re.S).group(1)
            return set(re.findall(r"'([a-z0-9]+)'\s*=", body))
        def cs_names(array):
            body = re.search(r"%s = \{(.*?)\};" % array, cs, re.S).group(1)
            return set(re.findall(r'"([a-z0-9]+)"', body))
        self.assertEqual(cs_names("KeyNames"), ps_names("KeyCodes"), "key names: client (C#) and worker (PowerShell) differ")
        self.assertEqual(cs_names("ModNames"), ps_names("ModCodes"), "modifier names: client (C#) and worker (PowerShell) differ")

    def test_the_scripts_change_no_login_pin_sleep_power_or_remote_desktop_setting(self):
        banned = ("powercfg", "rustdesk", "bcdedit", "setx", "Set-ItemProperty", "New-ItemProperty",
                  "HKLM:", "Winlogon", "InactivityTimeout", "ScreenSaver", "Set-LocalUser", "net user")
        for name in PS1:
            text = (WINDOWS / name).read_text().lower()
            for word in banned:
                self.assertNotIn(word.lower(), text, "windows/%s mentions %s" % (name, word))
            keys = re.findall(r"hk[a-z_]+[:\\]+[^\s\"']*", text)
            self.assertTrue(all(k.startswith("hkcu\\environment") for k in keys), "only HKCU\\Environment (the user PATH) may be touched: %s" % keys)


class NativeCodeTest(WindowsTestCase):
    """The C# block in agent-desktop.ps1 is only compiled on Windows, so compile it here: syntax, C# 5 (the 5.1 compiler), struct size."""

    def test_the_native_block_compiles_as_csharp_5_and_the_input_struct_has_the_size_user32_wants(self):
        src = (WINDOWS / "agent-desktop.ps1").read_text()
        m = re.search(r"\$script:NativeSource = @'\n(.*?)\n'@", src, re.S)
        self.assertIsNotNone(m, "agent-desktop.ps1 must hold the native block as a here-string")
        with tempfile.TemporaryDirectory() as tmp:
            code = Path(tmp) / "native.cs"
            code.write_text(m.group(1))
            probe = Path(tmp) / "probe.ps1"
            probe.write_text("""param([string]$Code)
Add-Type -TypeDefinition ([IO.File]::ReadAllText($Code)) -CompilerOptions '-langversion:5'
[Runtime.InteropServices.Marshal]::SizeOf((New-Object 'AdNative+INPUT'))
""")
            r = subprocess.run([pwsh(), "-NoProfile", "-File", str(probe), str(code)], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.strip(), "40", "INPUT must be 40 bytes on 64-bit Windows, or SendInput rejects every event")


    def test_the_compiled_client_compiles_as_csharp_5(self):
        """csc.exe on the G14 is C# 5. Roslyn here is told to accept C# 5 only, so a newer form in the client fails this test."""
        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / "probe.ps1"
            probe.write_text("""param([string]$Code)
Add-Type -TypeDefinition ([IO.File]::ReadAllText($Code)) -CompilerOptions '-langversion:5'
[AgentDesktopClient].GetMethod('Run').Name
""")
            r = subprocess.run([pwsh(), "-NoProfile", "-File", str(probe), str(WINDOWS / "agent-desktop-client.cs")], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(r.stdout.strip(), "Run")


class InstallTest(WindowsTestCase):
    def setUp(self):
        super().setUp()
        self.box = Sandbox(self)
        wt.release_files(self.box.release)

    def fresh(self):
        r = self.box.install()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def test_a_fresh_install_puts_both_scripts_and_the_pinned_tool_in_place(self):
        r = self.fresh()
        box = self.box
        for name in ("agent-desktop.ps1", "agent-desktop.cmd"):
            self.assertEqual((box.bin / name).read_bytes(), (WINDOWS / name).read_bytes(), name)
        self.assertFalse((box.bin / "install.ps1").exists(), "install.ps1 stays in the repo")
        self.assertTrue((box.vercel / "agent-desktop.exe").is_file(), r.stdout)
        self.assertIn("curl %s/%s" % (RELEASE, ASSET), box.calls())
        self.assertIn("curl %s/checksums.txt" % RELEASE, box.calls())
        self.assertIn(VERSION, r.stdout)

    def test_a_wrong_checksum_stops_the_install_and_leaves_no_tool(self):
        wt.release_files(self.box.release, checksum_ok=False)
        r = self.box.install()
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertRegex(r.stdout + r.stderr, r"(?i)checksum")
        found = list(self.box.vercel.rglob("*")) if self.box.vercel.exists() else []
        self.assertEqual([p.name for p in found if p.is_file()], [], "nothing may be left in the tool folder")

    def test_a_missing_download_tool_exits_69_and_says_so(self):
        env = self.box.env(PATH=os.pathsep.join([str(self.box.tmp / "empty"), "/usr/bin", "/bin"]))
        # /usr/bin has curl and tar but not curl.exe or tar.exe, which is what makes this a Windows-only lookup
        r = self.box.run(WINDOWS / "install.ps1", env=env)
        self.assertEqual(r.returncode, 69, r.stdout + r.stderr)
        self.assertRegex(r.stdout + r.stderr, r"curl\.exe|tar\.exe")

    def test_the_second_run_downloads_nothing_and_changes_nothing(self):
        self.fresh()
        box = self.box
        first_calls = len(box.calls())
        watched = [box.bin / "agent-desktop.ps1", box.bin / "agent-desktop.cmd", box.bin / "agent-desktop.exe", box.vercel / "agent-desktop.exe"]
        before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in watched}
        r = box.install()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        new_calls = box.calls()[first_calls:]
        quiet = [c for c in new_calls if not c.startswith(("reg query", "module Get-ScheduledTask"))]
        self.assertEqual(quiet, [], "a second run must not download, unpack, register, end, start or write anything")
        for p in watched:
            self.assertEqual((p.read_bytes(), p.stat().st_mtime_ns), before[p], p.name)
        self.assertIn("Nothing changed", r.stdout)

    def test_a_changed_script_is_replaced_without_a_download(self):
        self.fresh()
        box = self.box
        source = box.tmp / "windows-copy"
        shutil.copytree(WINDOWS, source)
        with open(source / "agent-desktop.ps1", "a") as f:
            f.write("\n# a later version\n")
        first_calls = len(box.calls())
        r = box.install(source=source)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("# a later version", (box.bin / "agent-desktop.ps1").read_text())
        self.assertEqual([c for c in box.calls()[first_calls:] if c.startswith(("curl", "tar"))], [])

    def test_the_task_runs_the_installed_script_as_the_worker_for_the_logged_on_user_only(self):
        self.fresh()
        task = self.box.task()
        self.assertEqual(task["TaskName"], wt.TASK_NAME)
        action = task["Actions"][0]
        self.assertEqual(action["Execute"], "powershell.exe")
        self.assertIn('-File "%s"' % (self.box.bin / "agent-desktop.ps1"), action["Arguments"])
        self.assertTrue(action["Arguments"].endswith(" --worker"), action["Arguments"])
        self.assertIn("-NoProfile", action["Arguments"])
        self.assertEqual(str(task["Principal"]["LogonType"]), "Interactive", "run only when the user is logged on")
        self.assertEqual(task["Principal"]["UserId"], "G14\\michael")
        self.assertTrue(task["HasTrigger"], "the worker starts at logon, so the first call finds it running")
        self.assertEqual([t["Type"] for t in task["Triggers"]], ["LogOn"])
        self.assertEqual(task["Triggers"][0]["UserId"], "G14\\michael")
        self.assertTrue(task["Settings"]["AllowStartIfOnBatteries"], "the laptop must run it on battery")
        self.assertEqual(str(task["Settings"]["MultipleInstances"]), "IgnoreNew", "one worker at a time")
        self.assertEqual(str(task["Settings"]["ExecutionTimeLimit"]), "PT0S", "a worker that lives for the session has no time limit")

    def test_a_fresh_install_starts_the_worker_so_the_first_call_is_fast(self):
        self.fresh()
        calls = [c for c in self.box.calls() if c.startswith("schtasks")]
        self.assertEqual(calls, ["schtasks /End agent-desktop", "schtasks /Run agent-desktop"], "end any old worker, then start the new one")

    def test_a_changed_script_restarts_the_worker(self):
        self.fresh()
        box = self.box
        source = box.tmp / "windows-copy"
        shutil.copytree(WINDOWS, source)
        with open(source / "agent-desktop.ps1", "a") as f:
            f.write("\n# a later version\n")
        before = len([c for c in box.calls() if c.startswith("schtasks")])
        box.install(source=source)
        self.assertEqual([c for c in box.calls() if c.startswith("schtasks")][before:], ["schtasks /End agent-desktop", "schtasks /Run agent-desktop"])

    def test_a_task_of_the_old_shape_is_registered_again(self):
        # the first live run ran the task per call: parallel instances, a ten minute limit, no trigger. Same command line.
        self.fresh()
        task = self.box.task()
        task["Settings"]["MultipleInstances"] = "Parallel"
        task["Settings"]["ExecutionTimeLimit"] = "PT10M"
        task["Triggers"] = []
        task["HasTrigger"] = False
        (self.box.state / "task.json").write_text(json.dumps(task))
        registers = lambda: [c for c in self.box.calls() if c.startswith("Register-ScheduledTask")]
        before = len(registers())
        self.box.install()
        self.assertEqual(len(registers()), before + 1, "the settings differ, so the task is registered again")
        again = self.box.task()
        self.assertEqual((str(again["Settings"]["MultipleInstances"]), str(again["Settings"]["ExecutionTimeLimit"]), len(again["Triggers"])), ("IgnoreNew", "PT0S", 1))
        self.box.install()
        self.assertEqual(len(registers()), before + 1, "and then left alone")

    def csc_calls(self):
        return [c for c in self.box.calls() if c.startswith("csc ")]

    def test_a_fresh_install_builds_the_client_exe_from_the_source_with_the_windows_compiler(self):
        self.fresh()
        exe = self.box.bin / "agent-desktop.exe"
        self.assertTrue(exe.is_file(), "agent-desktop.exe must be in the bin folder")
        self.assertIn((WINDOWS / "agent-desktop-client.cs").read_text(), exe.read_text(), "built from the repo's source")
        calls = self.csc_calls()
        self.assertEqual(len(calls), 1, calls)
        self.assertIn("/target:exe", calls[0])
        self.assertEqual([p.name for p in self.box.bin.iterdir() if p.name.endswith(".new")], [], "no half-built file may stay")

    def test_the_client_is_built_again_only_when_its_source_changed(self):
        self.fresh()
        box = self.box
        box.install()
        self.assertEqual(len(self.csc_calls()), 1, "an unchanged source is not compiled again")
        source = box.tmp / "windows-copy"
        shutil.copytree(WINDOWS, source)
        with open(source / "agent-desktop-client.cs", "a") as f:
            f.write("\n// a later version\n")
        r = box.install(source=source)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(self.csc_calls()), 2)
        self.assertIn("// a later version", (box.bin / "agent-desktop.exe").read_text())
        self.assertIn("agent-desktop.exe built", r.stdout)

    def test_a_compiler_error_fails_the_install_with_its_message_and_leaves_no_exe(self):
        r = self.box.install(AD_STUB_CSC_FAIL="1")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("C# compiler failed", r.stderr)
        self.assertIn("CS1002", r.stderr, "the compiler's own message is shown")
        self.assertFalse((self.box.bin / "agent-desktop.exe").exists())
        self.assertFalse((self.box.bin / "agent-desktop.exe.new").exists())

    def test_a_missing_compiler_exits_69_and_says_where_it_looked(self):
        missing = self.box.tmp / "no-such-csc.exe"
        r = self.box.install(AGENT_DESKTOP_CSC=str(missing))
        self.assertEqual(r.returncode, 69, r.stdout + r.stderr)
        self.assertIn(str(missing), r.stderr)

    def test_the_user_path_gets_the_bin_folder_once_and_keeps_existing_entries_and_their_kind(self):
        (self.box.state / "user-path.txt").write_text("%USERPROFILE%\\tools;C:\\Other")
        (self.box.state / "user-path.kind").write_text("REG_EXPAND_SZ")
        self.fresh()
        self.assertEqual(self.box.user_path(), "%USERPROFILE%\\tools;C:\\Other;" + str(self.box.bin))
        self.assertEqual((self.box.state / "user-path.kind").read_text(), "REG_EXPAND_SZ")
        adds = lambda: [c for c in self.box.calls() if c.startswith("reg add")]
        self.assertEqual(len(adds()), 1)
        self.box.install()
        self.assertEqual(len(adds()), 1, "a PATH that already has the folder is left alone")

    def test_a_user_with_no_path_value_yet_still_installs(self):
        # the stub reg.exe exits 1 with a message on stderr when there is no value, as the real one does
        r = self.fresh()
        self.assertEqual(self.box.user_path(), str(self.box.bin))
        self.assertIn("added", r.stdout)

    def test_a_task_that_differs_is_registered_again_and_a_matching_one_is_left_alone(self):
        self.fresh()
        registers = lambda: [c for c in self.box.calls() if c.startswith("Register-ScheduledTask")]
        self.assertEqual(len(registers()), 1)
        self.box.install()
        self.assertEqual(len(registers()), 1, "a matching task is left alone")
        task = self.box.task()
        task["Actions"][0]["Arguments"] = "-File old.ps1"
        (self.box.state / "task.json").write_text(json.dumps(task))
        self.box.install()
        self.assertEqual(len(registers()), 2, "a task with another command is registered again")


if __name__ == "__main__":
    unittest.main()
