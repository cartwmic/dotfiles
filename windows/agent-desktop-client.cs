// agent-desktop for the G14, the command an agent types: a small compiled program that hands the call to the worker.
// Source: windows/agent-desktop-client.cs in the dotfiles repo. windows/install.ps1 builds it with the C# compiler that ships with
// Windows (csc.exe, C# 5) into %USERPROFILE%\.local\bin\agent-desktop.exe, which wins over agent-desktop.cmd on the PATH.
// Contract and G14 notes: docs/agent-desktop.md.
//
// Why it exists: powershell.exe alone takes 270 ms to start in an ssh session on the G14 (this program: 30 ms), and the PowerShell
// client spent 540 to 620 ms per call, which put a `ui click` at 1.3 s against a limit of 1 s. This program does exactly what the
// PowerShell client in agent-desktop.ps1 does, and agent-desktop.ps1 stays as the fallback (agent-desktop.cmd runs it) and as the
// worker. Both are tested with the same calls.
//
// Same contract as agent-desktop.ps1: check the call (exit 2 with the usage on a bad call, before anything is written), write
// request-<run>.json under %LOCALAPPDATA%\agent-desktop\, wait for answer-<run>.json, print it, exit with its exit code. If nobody
// takes the request within 0.3 s the scheduled task is started (again each second); on timeout the request is withdrawn, the task
// is ended and the exit code is 1. Exit: 0 ok; 1 a tool failed, the screen is locked or no answer came in time; 2 usage; 69 a
// needed tool or the task is missing. Setting: AGENT_DESKTOP_TIMEOUT, seconds (default 60). Log: agent-desktop.log in the same
// folder, one line per step on both sides: UTC time, run id, elapsed seconds, step.

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;

public static class AgentDesktopClient
{
    const string Name = "agent-desktop";
    const string TaskName = "agent-desktop";
    const double DefaultTimeoutSeconds = 60;
    const int StartAfterMs = 300;      // a request nobody has taken after this long gets the task started, and again every second
    const int RestartEveryMs = 1000;

    sealed class ExitException : Exception
    {
        public readonly int Code;
        public ExitException(int code) { Code = code; }
    }

    static readonly RegexOptions Loose = RegexOptions.IgnoreCase | RegexOptions.CultureInvariant;

    // The names a caller may use for `key`; the same tables as the worker in agent-desktop.ps1 (a test keeps them in step).
    static readonly string[] KeyNames = {
        "return", "enter", "escape", "esc", "tab", "space", "backspace", "delete", "del", "insert", "home", "end",
        "pageup", "prior", "pagedown", "next", "up", "down", "left", "right",
        "comma", "period", "minus", "equal", "slash", "backslash", "semicolon", "apostrophe", "grave", "bracketleft", "bracketright",
        "capslock", "menu", "printscreen", "print"
    };
    static readonly string[] ModNames = { "ctrl", "control", "alt", "shift", "super", "win", "logo", "meta" };

    static TextWriter Out, Err;
    static string RunId;
    static Stopwatch Clock;

    public static int Main(string[] args)
    {
        return Run(args, Console.Out, Console.Error);
    }

    // The whole program, with its output streams passed in so that a test can call it.
    public static int Run(string[] args, TextWriter output, TextWriter error)
    {
        Out = output; Err = error;
        RunId = DateTime.UtcNow.ToString("yyyyMMdd'T'HHmmss'Z'", CultureInfo.InvariantCulture) + "-" + Process.GetCurrentProcess().Id;
        Clock = Stopwatch.StartNew();
        try { return Call(args); }
        catch (ExitException e) { return e.Code; }
        catch (Exception e) { Err.WriteLine("[" + Name + "] ERROR: " + e.Message); return 1; }
    }

    // ---- exits and the log -----------------------------------------------------------------------------------------------
    static void ShowUsage()
    {
        Err.WriteLine("usage: " + Name + " shot FILE [REGION] | windows | focus NAME | move X Y |");
        Err.WriteLine("       " + Name + " click X Y [left|right|middle] | type TEXT | key KEY [MOD...] | cursor | ui ARGS...");
    }

    static ExitException Usage(string message)
    {
        if (message.Length > 0) Err.WriteLine("[" + Name + "] ERROR: " + message);
        ShowUsage();
        return new ExitException(2);
    }

    static ExitException Fail(int code, string message)
    {
        Err.WriteLine("[" + Name + "] ERROR: " + message);
        return new ExitException(code);
    }

    static string StateDir()
    {
        string local = Environment.GetEnvironmentVariable("LOCALAPPDATA");
        if (string.IsNullOrEmpty(local)) local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        return Path.Combine(local, "agent-desktop");
    }

    static void Log(string text)
    {
        string dir = StateDir();
        Directory.CreateDirectory(dir);
        string stamp = DateTime.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'Z'", CultureInfo.InvariantCulture);
        string line = stamp + " run=" + RunId + " elapsed=" + (int)Clock.Elapsed.TotalSeconds + "s " + text + "\n";
        byte[] bytes = new UTF8Encoding(false).GetBytes(line);
        using (FileStream f = new FileStream(Path.Combine(dir, "agent-desktop.log"), FileMode.Append, FileAccess.Write, FileShare.ReadWrite))
            f.Write(bytes, 0, bytes.Length);
    }

    // What a step is called in the log. Never the typed text; never the arguments of ui.
    static string StepText(string action, string[] a)
    {
        switch (action)
        {
            case "shot": return "shot " + a[0] + " region=" + (a.Length > 1 ? a[1] : "full");
            case "focus": return "focus " + a[0];
            case "move": return "move " + a[0] + " " + a[1];
            case "click": return "click " + a[0] + " " + a[1] + " " + (a.Length > 2 ? a[2] : "left");
            case "type": return "type length=" + a[0].Length;
            case "key": return "key " + a[0] + " mods=" + (a.Length > 1 ? string.Join(",", a, 1, a.Length - 1) : "none");
            case "ui": return "ui sub=" + a[0] + " argc=" + a.Length;
            default: return action;
        }
    }

    // ---- the checks ------------------------------------------------------------------------------------------------------
    static bool IsInt(string v)
    {
        int n;
        return Regex.IsMatch(v, "^-?[0-9]+$", Loose) && int.TryParse(v, NumberStyles.Integer, CultureInfo.InvariantCulture, out n);
    }

    static bool IsWord(string v) { return Regex.IsMatch(v, "^[A-Za-z0-9_]+$", Loose); }

    static bool KnownKey(string name)
    {
        string k = name.ToLowerInvariant().Replace("_", "");
        if (Array.IndexOf(KeyNames, k) >= 0) return true;
        return Regex.IsMatch(k, "^[a-z]$", Loose) || Regex.IsMatch(k, "^[0-9]$", Loose) || Regex.IsMatch(k, "^f([1-9]|1[0-9]|2[0-4])$", Loose);
    }

    static bool KnownModifier(string name)
    {
        return Array.IndexOf(ModNames, name.ToLowerInvariant().Replace("_", "")) >= 0;
    }

    // Checks the whole call before anything is written or started. Exits 2 with the usage on any bad call.
    static void CheckCall(string[] argv)
    {
        if (argv.Length < 1) throw Usage("");
        string[] rest = new string[argv.Length - 1];
        Array.Copy(argv, 1, rest, 0, rest.Length);
        switch (argv[0])
        {
            case "shot":
                if (rest.Length < 1 || rest.Length > 2) throw Usage("");
                if (rest[0].Length == 0) throw Usage("shot: FILE must not be empty");
                if (rest.Length == 2 && !Regex.IsMatch(rest[1], "^-?[0-9]+,-?[0-9]+ [0-9]+x[0-9]+$", Loose))
                    throw Usage("shot: REGION must be \"X,Y WxH\", for example \"0,0 800x600\"");
                break;
            case "windows":
                if (rest.Length != 0) throw Usage("");
                break;
            case "focus":
                if (rest.Length != 1) throw Usage("");
                if (rest[0].Length == 0) throw Usage("focus: NAME must not be empty");
                break;
            case "move":
                if (rest.Length != 2) throw Usage("");
                if (!IsInt(rest[0]) || !IsInt(rest[1])) throw Usage("move: X and Y must be integers");
                break;
            case "click":
                if (rest.Length < 2 || rest.Length > 3) throw Usage("");
                if (!IsInt(rest[0]) || !IsInt(rest[1])) throw Usage("click: X and Y must be integers");
                if (rest.Length == 3 && Array.FindIndex(rest, 2, 1, delegate(string b) { return b == "left" || b == "right" || b == "middle"; }) < 0)
                    throw Usage("click: button must be left, right or middle");
                break;
            case "type":
                if (rest.Length != 1) throw Usage("");
                break;
            case "key":
                if (rest.Length < 1) throw Usage("");
                foreach (string w in rest) if (!IsWord(w)) throw Usage("key: KEY and MOD must be names such as comma or ctrl");
                if (!KnownKey(rest[0])) throw Usage("key: unknown key name " + rest[0]);
                for (int i = 1; i < rest.Length; i++)
                    if (!KnownModifier(rest[i])) throw Usage("key: unknown modifier " + rest[i] + " (ctrl, alt, shift or super)");
                break;
            case "cursor":
                if (rest.Length != 0) throw Usage("");
                break;
            case "ui":
                if (rest.Length < 1) throw Usage("");
                break;
            default:
                throw Usage("");
        }
    }

    static string UiBin()
    {
        string v = Environment.GetEnvironmentVariable("AGENT_DESKTOP_UI_BIN");
        if (!string.IsNullOrEmpty(v)) return v;
        string home = Environment.GetEnvironmentVariable("USERPROFILE");
        if (string.IsNullOrEmpty(home)) home = Environment.GetEnvironmentVariable("HOME");
        return Path.Combine(Path.Combine(Path.Combine(Path.Combine(Path.Combine(home ?? "", ".local"), "share"), "agent-desktop"), "vercel"), "agent-desktop.exe");
    }

    static double Timeout()
    {
        string v = Environment.GetEnvironmentVariable("AGENT_DESKTOP_TIMEOUT");
        if (string.IsNullOrEmpty(v)) return DefaultTimeoutSeconds;
        double d;
        if (!double.TryParse(v, NumberStyles.Float, CultureInfo.InvariantCulture, out d) || d <= 0)
            throw Usage("AGENT_DESKTOP_TIMEOUT must be a number of seconds, greater than 0");
        return d;
    }

    // ---- the files -------------------------------------------------------------------------------------------------------
    static string JsonString(string text)
    {
        StringBuilder sb = new StringBuilder(text.Length + 2);
        sb.Append('"');
        foreach (char c in text)
        {
            switch (c)
            {
                case '\\': sb.Append("\\\\"); break;
                case '"': sb.Append("\\\""); break;
                case '\n': sb.Append("\\n"); break;
                case '\r': sb.Append("\\r"); break;
                case '\t': sb.Append("\\t"); break;
                default:
                    if (c < ' ') sb.Append("\\u").Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                    else sb.Append(c);
                    break;
            }
        }
        return sb.Append('"').ToString();
    }

    static void WriteAtomic(string path, string text)
    {
        string tmp = Path.ChangeExtension(path, ".tmp");
        File.WriteAllText(tmp, text, new UTF8Encoding(false));
        if (File.Exists(path)) File.Delete(path);
        File.Move(tmp, path);
    }

    static void RemoveQuietly(string path)
    {
        try { File.Delete(path); } catch (Exception) { }
    }

    // The answer is {"exit":N,"stdout":"..","stderr":".."} written by the worker (PowerShell's ConvertTo-Json: any spacing, escapes
    // for quotes, backslashes, control characters, and \uXXXX for a few others).
    static bool ReadAnswer(string text, out int exit, out string stdout, out string stderr)
    {
        exit = 1; stdout = ""; stderr = "";
        int i = 0;
        SkipSpace(text, ref i);
        if (i >= text.Length || text[i] != '{') return false;
        i++;
        bool gotExit = false;
        while (true)
        {
            SkipSpace(text, ref i);
            if (i < text.Length && text[i] == '}') return gotExit;
            string key;
            if (!ReadString(text, ref i, out key)) return false;
            SkipSpace(text, ref i);
            if (i >= text.Length || text[i] != ':') return false;
            i++;
            SkipSpace(text, ref i);
            if (key == "exit")
            {
                int start = i;
                while (i < text.Length && (text[i] == '-' || (text[i] >= '0' && text[i] <= '9'))) i++;
                if (!int.TryParse(text.Substring(start, i - start), NumberStyles.Integer, CultureInfo.InvariantCulture, out exit)) return false;
                gotExit = true;
            }
            else
            {
                string v;
                if (!ReadString(text, ref i, out v)) return false;
                if (key == "stdout") stdout = v; else if (key == "stderr") stderr = v;
            }
            SkipSpace(text, ref i);
            if (i < text.Length && text[i] == ',') i++;
        }
    }

    static void SkipSpace(string t, ref int i) { while (i < t.Length && char.IsWhiteSpace(t[i])) i++; }

    static bool ReadString(string t, ref int i, out string value)
    {
        value = null;
        if (i >= t.Length || t[i] != '"') return false;
        i++;
        StringBuilder sb = new StringBuilder();
        while (i < t.Length)
        {
            char c = t[i++];
            if (c == '"') { value = sb.ToString(); return true; }
            if (c != '\\') { sb.Append(c); continue; }
            if (i >= t.Length) return false;
            char e = t[i++];
            switch (e)
            {
                case 'n': sb.Append('\n'); break;
                case 'r': sb.Append('\r'); break;
                case 't': sb.Append('\t'); break;
                case 'b': sb.Append('\b'); break;
                case 'f': sb.Append('\f'); break;
                case 'u':
                    int code;
                    if (i + 4 > t.Length || !int.TryParse(t.Substring(i, 4), NumberStyles.HexNumber, CultureInfo.InvariantCulture, out code)) return false;
                    sb.Append((char)code); i += 4;
                    break;
                default: sb.Append(e); break;   // \" \\ \/
            }
        }
        return false;
    }

    // schtasks.exe takes 40 ms. Its output is read and dropped so that nothing of it reaches this program's output.
    static int Schtasks(string arguments)
    {
        try
        {
            ProcessStartInfo psi = new ProcessStartInfo("schtasks.exe", arguments);
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;
            using (Process p = Process.Start(psi))
            {
                p.StandardOutput.ReadToEnd();
                p.StandardError.ReadToEnd();
                p.WaitForExit();
                return p.ExitCode;
            }
        }
        catch (Exception) { return -1; }
    }

    // ---- the call --------------------------------------------------------------------------------------------------------
    static int Call(string[] argv)
    {
        CheckCall(argv);
        string action = argv[0];
        string[] rest = new string[argv.Length - 1];
        Array.Copy(argv, 1, rest, 0, rest.Length);
        double timeout = Timeout();
        string uiBin = "";
        if (action == "ui")
        {
            uiBin = UiBin();
            if (!File.Exists(uiBin))
                throw Fail(69, "Vercel's agent-desktop is not installed at " + uiBin + ". Run windows\\install.ps1 from the dotfiles repo, or set AGENT_DESKTOP_UI_BIN.");
        }
        string dir = StateDir();
        Directory.CreateDirectory(dir);
        string request = Path.Combine(dir, "request-" + RunId + ".json");
        string answer = Path.Combine(dir, "answer-" + RunId + ".json");
        long expires = DateTime.UtcNow.AddSeconds(timeout).Ticks;
        StringBuilder args = new StringBuilder("[");
        for (int i = 0; i < rest.Length; i++) { if (i > 0) args.Append(','); args.Append(JsonString(rest[i])); }
        args.Append(']');
        string body = "{\"id\":" + JsonString(RunId) + ",\"action\":" + JsonString(action) + ",\"argv\":" + args + ",\"cwd\":" + JsonString(Directory.GetCurrentDirectory()) + ",\"ui_bin\":" + JsonString(uiBin) + ",\"expires\":" + expires.ToString(CultureInfo.InvariantCulture) + "}";
        WriteAtomic(request, body);
        Log("request " + StepText(action, rest));
        Stopwatch wait = Stopwatch.StartNew();
        double nextStart = StartAfterMs;
        bool started = false;
        while (!File.Exists(answer))
        {
            double ms = wait.Elapsed.TotalMilliseconds;
            if (ms >= timeout * 1000)
            {
                RemoveQuietly(request);   // a late worker must not act on an old call
                string t = timeout.ToString(CultureInfo.InvariantCulture);
                Log("FAIL timeout after " + t + "s waiting for the answer");
                Schtasks("/End /TN " + TaskName);   // a stuck worker is ended, so the next call starts a fresh one
                throw Fail(1, "no answer from the scheduled task '" + TaskName + "' within " + t + "s. The screen may be locked, nobody may be signed in on the G14, or the worker is stuck (it was ended; the next call starts a new one). Log: " + Path.Combine(dir, "agent-desktop.log"));
            }
            if (ms >= nextStart && File.Exists(request))
            {
                // nobody has taken the request: no worker is running, or it is busy. A running task ignores a second start.
                if (Schtasks("/Run /TN " + TaskName) != 0 && Schtasks("/Query /TN " + TaskName) != 0)
                {
                    RemoveQuietly(request);
                    Log("FAIL task is not registered");
                    throw Fail(69, "the scheduled task '" + TaskName + "' is not registered. Run windows\\install.ps1 from the dotfiles repo.");
                }
                if (!started) { Log("task start requested"); started = true; }
                nextStart = ms + RestartEveryMs;
            }
            Thread.Sleep(5);
        }
        string text = File.ReadAllText(answer, Encoding.UTF8);
        int exit; string stdout, stderr;
        bool ok = ReadAnswer(text, out exit, out stdout, out stderr);
        RemoveQuietly(answer);
        RemoveQuietly(request);
        if (!ok) throw Fail(1, "the answer from the worker could not be read: " + answer);
        if (stdout.Length > 0) Out.Write(stdout);
        if (stderr.Length > 0) Err.Write(stderr);
        Log("answer exit=" + exit);
        return exit;
    }
}
