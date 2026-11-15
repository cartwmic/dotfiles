# agent-desktop for the G14 (Windows 11, Windows PowerShell 5.1): screenshot, list windows, focus, move and click the
# pointer, type and press keys, and report where the pointer is. Agents call it over ssh; Michael can run it too.
# Source: windows/agent-desktop.ps1 in the dotfiles repo; windows/install.ps1 copies it to %USERPROFILE%\.local\bin.
# Contract and G14 notes: docs/agent-desktop.md.
#
#   agent-desktop shot FILE [REGION]                screenshot to FILE; REGION is one argument, "X,Y WxH"; prints FILE
#   agent-desktop windows                           one line per window: app, title, at, size, focused, minimized
#   agent-desktop focus NAME                        focus the window whose app (notepad.exe) or title is NAME
#   agent-desktop move X Y                          move the pointer to X,Y (screen pixels)
#   agent-desktop click X Y [left|right|middle]     move, then click (default left)
#   agent-desktop type TEXT                         type TEXT, one key at a time
#   agent-desktop key KEY [MOD...]                  press KEY with modifiers held: key comma ctrl
#   agent-desktop cursor                            print the pointer position as "X Y"
#   agent-desktop ui ARGS...                        hand ARGS to Vercel's agent-desktop; its output and exit code come back
#
# Why a scheduled task: an ssh session on the G14 has no desktop, and the screen and input calls only work inside the
# logged-in desktop session. So this script, run by the caller, checks the call, writes it as a request file under
# %LOCALAPPDATA%\agent-desktop\, starts the scheduled task "agent-desktop", waits for the answer file, prints it and exits with
# its exit code. The task runs this same script as `agent-desktop.ps1 --worker` inside the desktop session; the worker takes
# the request, does the action and writes the answer.
#
# Exit: 0 ok; 1 a tool failed, the screen is locked or no answer came in time; 2 usage; 69 a needed tool is missing.
# Setting: AGENT_DESKTOP_TIMEOUT, seconds to wait for the answer (default 60).
# Log: %LOCALAPPDATA%\agent-desktop\agent-desktop.log, one line per step on both sides of the task: UTC time, run id,
# elapsed, step. `type` logs its length, not its text. `ui` logs its first argument and how many there are, because its
# arguments can carry typed text.
$ErrorActionPreference = 'Stop'

$script:Name = 'agent-desktop'
$script:Actions = 'shot', 'windows', 'focus', 'move', 'click', 'type', 'key', 'cursor', 'ui'
$script:DefaultTimeoutSeconds = 60
$script:TaskName = 'agent-desktop'
$script:KeyIntervalMs = 40   # a burst of keys mistyped on a fresh Notepad tab (poc/g14.md J6); paced keys did not

function Get-StateDir {
    $local = $env:LOCALAPPDATA
    if (-not $local) { $local = [Environment]::GetFolderPath('LocalApplicationData') }
    Join-Path $local 'agent-desktop'
}

function Get-RunId { (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ', [Globalization.CultureInfo]::InvariantCulture) + '-' + $PID }

# ---- log ----------------------------------------------------------------------------------------------------------------
$script:RunId = Get-RunId
$script:Clock = [Diagnostics.Stopwatch]::StartNew()

function Write-Log([string]$Text) {
    # One line: UTC time, run id, elapsed seconds, step. Opened shared so the two sides of the task can both append.
    $dir = Get-StateDir
    [void](New-Item -ItemType Directory -Force -Path $dir)
    $stamp = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ', [Globalization.CultureInfo]::InvariantCulture)
    $line = '{0} run={1} elapsed={2}s {3}' -f $stamp, $script:RunId, [int]$script:Clock.Elapsed.TotalSeconds, $Text
    $bytes = (New-Object Text.UTF8Encoding $false).GetBytes($line + "`n")
    $stream = New-Object IO.FileStream (Join-Path $dir 'agent-desktop.log'), ([IO.FileMode]::Append), ([IO.FileAccess]::Write), ([IO.FileShare]::ReadWrite)
    try { $stream.Write($bytes, 0, $bytes.Length) } finally { $stream.Dispose() }
}

function Get-StepText([string]$Action, [string[]]$Argv) {
    # What a step is called in the log. Never the typed text; never the arguments of ui.
    switch ($Action) {
        'shot'   { $region = 'full'; if ($Argv.Count -gt 1) { $region = $Argv[1] }; "shot $($Argv[0]) region=$region" }
        'focus'  { "focus $($Argv[0])" }
        'move'   { "move $($Argv[0]) $($Argv[1])" }
        'click'  { $b = 'left'; if ($Argv.Count -gt 2) { $b = $Argv[2] }; "click $($Argv[0]) $($Argv[1]) $b" }
        'type'   { "type length=$($Argv[0].Length)" }
        'key'    { $mods = 'none'; if ($Argv.Count -gt 1) { $mods = ($Argv[1..($Argv.Count - 1)] -join ',') }; "key $($Argv[0]) mods=$mods" }
        'ui'     { "ui sub=$($Argv[0]) argc=$($Argv.Count)" }
        default  { $Action }
    }
}

# ---- usage and checks -----------------------------------------------------------------------------------------------------
function Out-Err([string]$Text) { [Console]::Error.WriteLine($Text) }

function Show-Usage {
    Out-Err "usage: $script:Name shot FILE [REGION] | windows | focus NAME | move X Y |"
    Out-Err "       $script:Name click X Y [left|right|middle] | type TEXT | key KEY [MOD...] | cursor | ui ARGS..."
}

function Exit-Usage([string]$Message) {
    if ($Message) { Out-Err "[$script:Name] ERROR: $Message" }
    Show-Usage
    exit 2
}

function Exit-Fail([int]$Code, [string]$Message) {
    Out-Err "[$script:Name] ERROR: $Message"
    exit $Code
}

function Test-Int([string]$Value) { $n = 0; ($Value -match '^-?[0-9]+$') -and [int]::TryParse($Value, [ref]$n) }

function Test-Word([string]$Value) { $Value -match '^[A-Za-z0-9_]+$' }

# Key names a caller may use, in the names the Linux script takes (xkb-style), lower case, underscores dropped.
# value = virtual-key code; "e" after the colon marks an extended key.
$script:KeyCodes = @{
    'return' = '13'; 'enter' = '13'; 'escape' = '1B'; 'esc' = '1B'; 'tab' = '09'; 'space' = '20'; 'backspace' = '08'
    'delete' = '2E:e'; 'del' = '2E:e'; 'insert' = '2D:e'; 'home' = '24:e'; 'end' = '23:e'
    'pageup' = '21:e'; 'prior' = '21:e'; 'pagedown' = '22:e'; 'next' = '22:e'
    'up' = '26:e'; 'down' = '28:e'; 'left' = '25:e'; 'right' = '27:e'
    'comma' = 'BC'; 'period' = 'BE'; 'minus' = 'BD'; 'equal' = 'BB'; 'slash' = 'BF'; 'backslash' = 'DC'; 'semicolon' = 'BA'
    'apostrophe' = 'DE'; 'grave' = 'C0'; 'bracketleft' = 'DB'; 'bracketright' = 'DD'
    'capslock' = '14'; 'menu' = '5D:e'; 'printscreen' = '2C:e'; 'print' = '2C:e'
}
$script:ModCodes = @{
    'ctrl' = '11'; 'control' = '11'; 'alt' = '12'; 'shift' = '10'
    'super' = '5B:e'; 'win' = '5B:e'; 'logo' = '5B:e'; 'meta' = '5B:e'
}

function Resolve-Key([string]$Name, [hashtable]$Table) {
    # Returns a [code, extended] pair, or $null when the name is not one this script knows.
    $k = $Name.ToLowerInvariant().Replace('_', '')
    $v = $null
    if ($Table.ContainsKey($k)) { $v = $Table[$k] }
    elseif ($Table -eq $script:KeyCodes) {
        if ($k -match '^[a-z]$') { $v = ('{0:X2}' -f ([int][char]$k - 32)) }
        elseif ($k -match '^[0-9]$') { $v = ('{0:X2}' -f [int][char]$k) }
        elseif ($k -match '^f([1-9]|1[0-9]|2[0-4])$') { $v = ('{0:X2}' -f (111 + [int]$Matches[1])) }
    }
    if ($null -eq $v) { return $null }
    $parts = $v.Split(':')
    return , @([int]('0x' + $parts[0]), ($parts.Count -gt 1))
}

function Test-Call([string[]]$Argv) {
    # Checks the whole call before anything is written or started. Exits 2 with the usage on any bad call.
    if ($Argv.Count -lt 1) { Exit-Usage '' }
    $rest = @()
    if ($Argv.Count -gt 1) { $rest = $Argv[1..($Argv.Count - 1)] }
    switch ($Argv[0]) {
        'shot' {
            if ($rest.Count -lt 1 -or $rest.Count -gt 2) { Exit-Usage '' }
            if ($rest[0] -eq '') { Exit-Usage 'shot: FILE must not be empty' }
            if ($rest.Count -eq 2 -and $rest[1] -notmatch '^-?[0-9]+,-?[0-9]+ [0-9]+x[0-9]+$') { Exit-Usage 'shot: REGION must be "X,Y WxH", for example "0,0 800x600"' }
        }
        'windows' { if ($rest.Count -ne 0) { Exit-Usage '' } }
        'focus' {
            if ($rest.Count -ne 1) { Exit-Usage '' }
            if ($rest[0] -eq '') { Exit-Usage 'focus: NAME must not be empty' }
        }
        'move' {
            if ($rest.Count -ne 2) { Exit-Usage '' }
            if (-not (Test-Int $rest[0]) -or -not (Test-Int $rest[1])) { Exit-Usage 'move: X and Y must be integers' }
        }
        'click' {
            if ($rest.Count -lt 2 -or $rest.Count -gt 3) { Exit-Usage '' }
            if (-not (Test-Int $rest[0]) -or -not (Test-Int $rest[1])) { Exit-Usage 'click: X and Y must be integers' }
            if ($rest.Count -eq 3 -and @('left', 'right', 'middle') -notcontains $rest[2]) { Exit-Usage 'click: button must be left, right or middle' }
        }
        'type' { if ($rest.Count -ne 1) { Exit-Usage '' } }
        'key' {
            if ($rest.Count -lt 1) { Exit-Usage '' }
            foreach ($w in $rest) { if (-not (Test-Word $w)) { Exit-Usage 'key: KEY and MOD must be names such as comma or ctrl' } }
            if ($null -eq (Resolve-Key $rest[0] $script:KeyCodes)) { Exit-Usage "key: unknown key name $($rest[0])" }
            for ($i = 1; $i -lt $rest.Count; $i++) {
                if ($null -eq (Resolve-Key $rest[$i] $script:ModCodes)) { Exit-Usage "key: unknown modifier $($rest[$i]) (ctrl, alt, shift or super)" }
            }
        }
        'cursor' { if ($rest.Count -ne 0) { Exit-Usage '' } }
        'ui' { if ($rest.Count -lt 1) { Exit-Usage '' } }
        default { Exit-Usage '' }
    }
}

# ---- the call from the caller's session: request, task, answer ------------------------------------------------------------
function Get-UiBin {
    if ($env:AGENT_DESKTOP_UI_BIN) { return $env:AGENT_DESKTOP_UI_BIN }
    $home1 = $env:USERPROFILE
    if (-not $home1) { $home1 = $HOME }
    $p = $home1
    foreach ($part in '.local', 'share', 'agent-desktop', 'vercel', 'agent-desktop.exe') { $p = Join-Path $p $part }
    $p
}

function Get-Timeout {
    $t = $script:DefaultTimeoutSeconds
    if ($env:AGENT_DESKTOP_TIMEOUT) {
        $d = 0.0
        if (-not [double]::TryParse($env:AGENT_DESKTOP_TIMEOUT, [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$d) -or $d -le 0) {
            Exit-Usage 'AGENT_DESKTOP_TIMEOUT must be a number of seconds, greater than 0'
        }
        $t = $d
    }
    $t
}

function Write-TextAtomic([string]$Path, [string]$Text) {
    $tmp = [IO.Path]::ChangeExtension($Path, '.tmp')
    [IO.File]::WriteAllText($tmp, $Text, (New-Object Text.UTF8Encoding $false))
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

function Invoke-Call([string[]]$Argv) {
    Test-Call $Argv
    $action = $Argv[0]
    $rest = @()
    if ($Argv.Count -gt 1) { $rest = [string[]]$Argv[1..($Argv.Count - 1)] }
    $timeout = Get-Timeout
    $uiBin = ''
    if ($action -eq 'ui') {
        $uiBin = Get-UiBin
        if (-not (Test-Path -LiteralPath $uiBin -PathType Leaf)) {
            Exit-Fail 69 "Vercel's agent-desktop is not installed at $uiBin. Run windows\install.ps1 from the dotfiles repo, or set AGENT_DESKTOP_UI_BIN."
        }
    }
    $dir = Get-StateDir
    [void](New-Item -ItemType Directory -Force -Path $dir)
    $request = Join-Path $dir "request-$script:RunId.json"
    $answer = Join-Path $dir "answer-$script:RunId.json"
    $expires = [DateTime]::UtcNow.AddSeconds($timeout).Ticks
    $body = [ordered]@{ id = $script:RunId; action = $action; argv = [string[]]$rest; cwd = $PWD.ProviderPath; ui_bin = $uiBin; expires = $expires }
    Write-TextAtomic $request (ConvertTo-Json -InputObject $body)
    Write-Log ("request " + (Get-StepText $action $rest))
    try {
        Start-ScheduledTask -TaskName $script:TaskName
    } catch {
        Remove-Item -LiteralPath $request -ErrorAction SilentlyContinue
        $registered = Get-ScheduledTask -TaskName $script:TaskName -ErrorAction SilentlyContinue
        if (-not $registered) {
            Write-Log 'FAIL task is not registered'
            Exit-Fail 69 "the scheduled task '$script:TaskName' is not registered. Run windows\install.ps1 from the dotfiles repo."
        }
        Write-Log 'FAIL task did not start'
        Exit-Fail 1 "could not start the scheduled task '$script:TaskName': $($_.Exception.Message)"
    }
    Write-Log 'task started'
    $wait = [Diagnostics.Stopwatch]::StartNew()
    while (-not (Test-Path -LiteralPath $answer)) {
        if ($wait.Elapsed.TotalSeconds -ge $timeout) {
            Remove-Item -LiteralPath $request -ErrorAction SilentlyContinue   # a late task run must not act on an old call
            Write-Log "FAIL timeout after ${timeout}s waiting for the answer"
            Exit-Fail 1 "no answer from the scheduled task '$script:TaskName' within ${timeout}s. The screen may be locked, nobody may be signed in on the G14, or the task is stuck. Log: $(Join-Path $dir 'agent-desktop.log')"
        }
        [Threading.Thread]::Sleep(25)
    }
    $reply = ConvertFrom-Json ([IO.File]::ReadAllText($answer))
    Remove-Item -LiteralPath $answer, $request -ErrorAction SilentlyContinue
    if ($reply.stdout) { [Console]::Out.Write([string]$reply.stdout) }
    if ($reply.stderr) { [Console]::Error.Write([string]$reply.stderr) }
    Write-Log "answer exit=$($reply.exit)"
    exit ([int]$reply.exit)
}

# ---- the worker: runs inside the desktop session --------------------------------------------------------------------------
$script:NativeLoaded = $false

function Initialize-Native {
    if ($script:NativeLoaded) { return }
    Add-Type -AssemblyName System.Drawing
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -TypeDefinition $script:NativeSource
    [void][AdNative]::SetProcessDPIAware()   # the task is not DPI aware by default; without this the coordinates are scaled
    $script:NativeLoaded = $true
}

$script:NativeSource = @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;

public class AdWindow {
    public IntPtr Handle; public string Title; public uint ProcessId; public int X, Y, W, H; public bool Minimized;
}

public static class AdNative {
    [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] public struct MOUSEINPUT { public int dx; public int dy; public uint mouseData; public uint dwFlags; public uint time; public IntPtr dwExtraInfo; }
    [StructLayout(LayoutKind.Sequential)] public struct KEYBDINPUT { public ushort wVk; public ushort wScan; public uint dwFlags; public uint time; public IntPtr dwExtraInfo; }
    [StructLayout(LayoutKind.Explicit)] public struct INPUTUNION { [FieldOffset(0)] public MOUSEINPUT mi; [FieldOffset(0)] public KEYBDINPUT ki; }
    [StructLayout(LayoutKind.Sequential)] public struct INPUT { public uint type; public INPUTUNION u; }
    delegate bool EnumProc(IntPtr h, IntPtr l);

    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    [DllImport("user32.dll")] public static extern bool GetCursorPos(out POINT p);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll", SetLastError = true)] static extern uint SendInput(uint n, INPUT[] inputs, int size);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumProc cb, IntPtr l);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetWindowTextLengthW(IntPtr h);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] static extern bool BringWindowToTop(IntPtr h);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] static extern bool AttachThreadInput(uint from, uint to, bool attach);
    [DllImport("user32.dll")] static extern uint MapVirtualKeyW(uint code, uint type);
    [DllImport("kernel32.dll")] static extern uint GetCurrentThreadId();
    [DllImport("dwmapi.dll")] static extern int DwmGetWindowAttribute(IntPtr h, int attr, out int value, int size);

    const uint INPUT_MOUSE = 0, INPUT_KEYBOARD = 1;
    const uint KEYEVENTF_EXTENDEDKEY = 1, KEYEVENTF_KEYUP = 2, KEYEVENTF_UNICODE = 4;

    public static string Cursor() {
        POINT p; if (!GetCursorPos(out p)) throw new Exception("GetCursorPos failed");
        return p.X + " " + p.Y;
    }

    public static void Move(int x, int y) {
        if (!SetCursorPos(x, y)) throw new Exception("SetCursorPos failed for " + x + "," + y);
    }

    public static void Click(string button) {
        uint down = 0x0002, up = 0x0004;
        if (button == "right") { down = 0x0008; up = 0x0010; }
        else if (button == "middle") { down = 0x0020; up = 0x0040; }
        INPUT[] inputs = new INPUT[2];
        inputs[0].type = INPUT_MOUSE; inputs[0].u.mi.dwFlags = down;
        inputs[1].type = INPUT_MOUSE; inputs[1].u.mi.dwFlags = up;
        Send(inputs);
    }

    static void Send(INPUT[] inputs) {
        uint sent = SendInput((uint)inputs.Length, inputs, Marshal.SizeOf(typeof(INPUT)));
        if (sent != inputs.Length) throw new Exception("SendInput accepted " + sent + " of " + inputs.Length + " events (error " + Marshal.GetLastWin32Error() + ")");
    }

    static INPUT Key(ushort vk, uint flags) {
        INPUT i = new INPUT(); i.type = INPUT_KEYBOARD;
        i.u.ki.wVk = vk; i.u.ki.wScan = (ushort)MapVirtualKeyW(vk, 0); i.u.ki.dwFlags = flags;
        return i;
    }

    // Press KEY with the modifiers held, as one batch so nothing slips in between.
    public static void Chord(int[] mods, bool[] modExtended, int key, bool keyExtended) {
        List<INPUT> list = new List<INPUT>();
        for (int i = 0; i < mods.Length; i++) list.Add(Key((ushort)mods[i], modExtended[i] ? KEYEVENTF_EXTENDEDKEY : 0));
        list.Add(Key((ushort)key, keyExtended ? KEYEVENTF_EXTENDEDKEY : 0));
        list.Add(Key((ushort)key, (keyExtended ? KEYEVENTF_EXTENDEDKEY : 0) | KEYEVENTF_KEYUP));
        for (int i = mods.Length - 1; i >= 0; i--) list.Add(Key((ushort)mods[i], (modExtended[i] ? KEYEVENTF_EXTENDEDKEY : 0) | KEYEVENTF_KEYUP));
        Send(list.ToArray());
    }

    // Type TEXT one character at a time, intervalMs apart. Enter and Tab are real keys; everything else is a Unicode key event.
    public static void TypeText(string text, int intervalMs) {
        for (int n = 0; n < text.Length; n++) {
            char c = text[n];
            INPUT[] pair = new INPUT[2];
            if (c == '\r' || c == '\n') {
                if (c == '\r' && n + 1 < text.Length && text[n + 1] == '\n') n++;
                pair[0] = Key(0x0D, 0); pair[1] = Key(0x0D, KEYEVENTF_KEYUP);
            } else if (c == '\t') {
                pair[0] = Key(0x09, 0); pair[1] = Key(0x09, KEYEVENTF_KEYUP);
            } else {
                pair[0] = new INPUT(); pair[0].type = INPUT_KEYBOARD; pair[0].u.ki.wScan = c; pair[0].u.ki.dwFlags = KEYEVENTF_UNICODE;
                pair[1] = new INPUT(); pair[1].type = INPUT_KEYBOARD; pair[1].u.ki.wScan = c; pair[1].u.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP;
            }
            Send(pair);
            if (n + 1 < text.Length) Thread.Sleep(intervalMs);
        }
    }

    public static List<AdWindow> Windows() {
        List<AdWindow> list = new List<AdWindow>();
        EnumWindows(delegate(IntPtr h, IntPtr l) {
            if (!IsWindowVisible(h)) return true;
            int cloaked = 0; DwmGetWindowAttribute(h, 14, out cloaked, 4);
            if (cloaked != 0) return true;   // hidden UWP shells
            int len = GetWindowTextLengthW(h);
            if (len == 0) return true;
            StringBuilder sb = new StringBuilder(len + 1); GetWindowTextW(h, sb, sb.Capacity);
            RECT r; GetWindowRect(h, out r);
            uint pid; GetWindowThreadProcessId(h, out pid);
            AdWindow w = new AdWindow();
            w.Handle = h; w.Title = sb.ToString(); w.ProcessId = pid; w.X = r.Left; w.Y = r.Top; w.W = r.Right - r.Left; w.H = r.Bottom - r.Top; w.Minimized = IsIconic(h);
            list.Add(w);
            return true;
        }, IntPtr.Zero);
        return list;
    }

    public static IntPtr Foreground() { return GetForegroundWindow(); }

    // Bring the window to the front and say whether it is there now.
    public static bool Focus(IntPtr h) {
        if (IsIconic(h)) ShowWindow(h, 9);
        uint ignore; uint fgThread = GetWindowThreadProcessId(GetForegroundWindow(), out ignore);
        uint me = GetCurrentThreadId();
        bool attached = fgThread != 0 && fgThread != me && AttachThreadInput(me, fgThread, true);
        BringWindowToTop(h); SetForegroundWindow(h);
        if (attached) AttachThreadInput(me, fgThread, false);
        return GetForegroundWindow() == h;
    }
}
'@

function Test-ScreenLocked {
    # Windows runs LogonUI.exe while the lock screen is up. This is the check the G14 trial used (poc/g14.md).
    [bool](Get-Process -Name LogonUI -ErrorAction SilentlyContinue)
}

function ConvertTo-ArgString([string[]]$Items) {
    # One command-line string that the receiving program splits back into exactly these arguments (CommandLineToArgvW rules).
    $parts = New-Object Collections.Generic.List[string]
    foreach ($a in $Items) {
        if ($a.Length -gt 0 -and $a -notmatch '[\s"]') { $parts.Add($a); continue }
        $sb = New-Object Text.StringBuilder
        [void]$sb.Append('"')
        $slashes = 0
        foreach ($c in $a.ToCharArray()) {
            if ($c -eq [char]'\') { $slashes++ }
            elseif ($c -eq [char]'"') { [void]$sb.Append([string]::new([char]'\', $slashes * 2 + 1)); [void]$sb.Append('"'); $slashes = 0 }
            else { if ($slashes -gt 0) { [void]$sb.Append([string]::new([char]'\', $slashes)); $slashes = 0 }; [void]$sb.Append($c) }
        }
        [void]$sb.Append([string]::new([char]'\', $slashes * 2))
        [void]$sb.Append('"')
        $parts.Add($sb.ToString())
    }
    $parts -join ' '
}

function Invoke-Ui([string]$Bin, [string[]]$Argv) {
    if (-not (Test-Path -LiteralPath $Bin -PathType Leaf)) { return @{ exit = 69; stdout = ''; stderr = "Vercel's agent-desktop is not installed at $Bin. Run windows\install.ps1.`n" } }
    $psi = New-Object Diagnostics.ProcessStartInfo $Bin
    $psi.Arguments = ConvertTo-ArgString $Argv
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.RedirectStandardInput = $true
    $p = [Diagnostics.Process]::Start($psi)
    $p.StandardInput.Close()
    $out = $p.StandardOutput.ReadToEndAsync()
    $err = $p.StandardError.ReadToEndAsync()
    $p.WaitForExit()
    @{ exit = $p.ExitCode; stdout = $out.Result; stderr = $err.Result }
}

function Invoke-Action([string]$Action, [string[]]$Argv, [string]$Cwd, [string]$UiBin) {
    # Returns @{ exit; stdout; stderr }. Anything it throws becomes exit 1 with the message.
    if ($Action -eq 'ui') { return (Invoke-Ui $UiBin $Argv) }
    Initialize-Native
    switch ($Action) {
        'shot' {
            $file = [IO.Path]::GetFullPath([IO.Path]::Combine($Cwd, $Argv[0]))
            $b = [System.Windows.Forms.SystemInformation]::VirtualScreen
            $x = $b.Left; $y = $b.Top; $w = $b.Width; $h = $b.Height
            if ($Argv.Count -gt 1) {
                $m = [regex]::Match($Argv[1], '^(-?[0-9]+),(-?[0-9]+) ([0-9]+)x([0-9]+)$')
                $x = [int]$m.Groups[1].Value; $y = [int]$m.Groups[2].Value; $w = [int]$m.Groups[3].Value; $h = [int]$m.Groups[4].Value
            }
            $bmp = New-Object Drawing.Bitmap $w, $h
            try {
                $g = [Drawing.Graphics]::FromImage($bmp)
                try { $g.CopyFromScreen($x, $y, 0, 0, $bmp.Size) } finally { $g.Dispose() }
                $format = [Drawing.Imaging.ImageFormat]::Png
                if ($file -match '\.jpe?g$') { $format = [Drawing.Imaging.ImageFormat]::Jpeg }
                $bmp.Save($file, $format)
            } finally { $bmp.Dispose() }
            return @{ exit = 0; stdout = "$($Argv[0])`n"; stderr = '' }
        }
        'windows' {
            $fg = [AdNative]::Foreground()
            $lines = New-Object Collections.Generic.List[string]
            $lines.Add("app`ttitle`tat`tsize`tfocused`tminimized")
            foreach ($w in [AdNative]::Windows()) {
                $app = ''
                try { $app = (Get-Process -Id $w.ProcessId -ErrorAction Stop).ProcessName + '.exe' } catch { $app = '' }
                $title = ([string]$w.Title).Replace("`t", ' ').Replace("`n", ' ').Replace("`r", ' ')
                $lines.Add(("{0}`t{1}`t{2},{3}`t{4}x{5}`t{6}`t{7}" -f $app, $title, $w.X, $w.Y, $w.W, $w.H, ([bool]($w.Handle -eq $fg)).ToString().ToLowerInvariant(), ([bool]$w.Minimized).ToString().ToLowerInvariant()))
            }
            return @{ exit = 0; stdout = (($lines -join "`n") + "`n"); stderr = '' }
        }
        'focus' {
            $name = $Argv[0]
            $all = @()
            foreach ($w in [AdNative]::Windows()) {
                $app = ''
                try { $app = (Get-Process -Id $w.ProcessId -ErrorAction Stop).ProcessName } catch { $app = '' }
                $all += , @($w, $app)
            }
            $stem = [IO.Path]::GetFileNameWithoutExtension($name)
            $hit = $null
            foreach ($pair in $all) { if ($pair[1] -ieq $stem) { $hit = $pair[0]; break } }
            if ($null -eq $hit) { foreach ($pair in $all) { if ($pair[0].Title -ieq $name) { $hit = $pair[0]; break } } }
            if ($null -eq $hit) { foreach ($pair in $all) { if ($pair[0].Title.IndexOf($name, [StringComparison]::OrdinalIgnoreCase) -ge 0) { $hit = $pair[0]; break } } }
            if ($null -eq $hit) { return @{ exit = 1; stdout = ''; stderr = "[$script:Name] ERROR: no window has the app name or a title matching $name`n" } }
            if (-not [AdNative]::Focus($hit.Handle)) { return @{ exit = 1; stdout = ''; stderr = "[$script:Name] ERROR: Windows did not bring '$($hit.Title)' to the front`n" } }
            return @{ exit = 0; stdout = ''; stderr = '' }
        }
        'move' { [AdNative]::Move([int]$Argv[0], [int]$Argv[1]); return @{ exit = 0; stdout = ''; stderr = '' } }
        'click' {
            $button = 'left'
            if ($Argv.Count -gt 2) { $button = $Argv[2] }
            [AdNative]::Move([int]$Argv[0], [int]$Argv[1])
            [AdNative]::Click($button)
            return @{ exit = 0; stdout = ''; stderr = '' }
        }
        'type' { [AdNative]::TypeText($Argv[0], $script:KeyIntervalMs); return @{ exit = 0; stdout = ''; stderr = '' } }
        'key' {
            $key = Resolve-Key $Argv[0] $script:KeyCodes
            $codes = New-Object Collections.Generic.List[int]
            $ext = New-Object Collections.Generic.List[bool]
            for ($i = 1; $i -lt $Argv.Count; $i++) { $m = Resolve-Key $Argv[$i] $script:ModCodes; $codes.Add($m[0]); $ext.Add($m[1]) }
            [AdNative]::Chord($codes.ToArray(), $ext.ToArray(), $key[0], $key[1])
            return @{ exit = 0; stdout = ''; stderr = '' }
        }
        'cursor' { return @{ exit = 0; stdout = ([AdNative]::Cursor() + "`n"); stderr = '' } }
    }
    @{ exit = 2; stdout = ''; stderr = "[$script:Name] ERROR: unknown action $Action`n" }
}

function Invoke-Worker {
    $dir = Get-StateDir
    if (-not (Test-Path -LiteralPath $dir)) { return }
    foreach ($file in (Get-ChildItem -LiteralPath $dir -Filter 'request-*.json' | Sort-Object Name)) {
        $claimed = Join-Path $dir ('claimed-' + $file.Name.Substring('request-'.Length))
        try { [IO.File]::Move($file.FullName, $claimed) } catch { continue }   # another worker took it
        $req = $null
        try { $req = ConvertFrom-Json ([IO.File]::ReadAllText($claimed)) } catch { }
        Remove-Item -LiteralPath $claimed -ErrorAction SilentlyContinue
        if ($null -eq $req) { $script:RunId = Get-RunId; Write-Log 'worker FAIL unreadable request'; continue }
        $script:RunId = [string]$req.id
        $script:Clock = [Diagnostics.Stopwatch]::StartNew()
        if ([DateTime]::UtcNow.Ticks -gt [int64]$req.expires) { Write-Log 'worker dropped an expired request'; continue }
        $argv = [string[]]@($req.argv)
        $step = Get-StepText ([string]$req.action) $argv
        $result = $null
        if (Test-ScreenLocked) {
            Write-Log "worker FAIL ${step}: the screen is locked"
            $result = @{ exit = 1; stdout = ''; stderr = "[$script:Name] ERROR: the screen is locked. Unlock the G14, then run the command again. See docs/agent-desktop.md.`n" }
        } else {
            try {
                $result = Invoke-Action ([string]$req.action) $argv ([string]$req.cwd) ([string]$req.ui_bin)
                if ($result.exit -eq 0) { Write-Log "worker $step ok" } else { Write-Log "worker FAIL $step exit=$($result.exit)" }
            } catch {
                Write-Log "worker FAIL $step"
                $result = @{ exit = 1; stdout = ''; stderr = "[$script:Name] ERROR: $($_.Exception.Message)`n" }
            }
        }
        if ([DateTime]::UtcNow.Ticks -gt [int64]$req.expires) { Write-Log 'worker answer dropped: the caller gave up'; continue }
        $answer = Join-Path $dir ('answer-' + $script:RunId + '.json')
        Write-TextAtomic $answer (ConvertTo-Json -InputObject ([ordered]@{ exit = [int]$result.exit; stdout = [string]$result.stdout; stderr = [string]$result.stderr }))
        return   # one request per worker run: the caller starts the task once per call
    }
}

# ---- main -----------------------------------------------------------------------------------------------------------------
if ($args.Count -ge 1 -and $args[0] -eq '--worker') {
    Invoke-Worker
    exit 0
}
Invoke-Call ([string[]]$args)
