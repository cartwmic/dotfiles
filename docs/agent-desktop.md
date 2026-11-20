# agent-desktop

One command, `agent-desktop`, lets an agent see and drive the screen. It runs on four computers and does the same eight things on each: take a screenshot, list the windows, bring a window to the front, move the pointer, click, type, press keys, and report where the pointer is. On the Macs and the G14 it can also list an app's buttons and fields by name and click them by name, with `agent-desktop ui`.

Each computer has its own script. The scripts never call each other and there is no front-door script that picks one: dotfiles decides which one a computer gets. What they share is the contract below.

## The contract

```
agent-desktop shot FILE [REGION]             screenshot to FILE (REGION is "X,Y WxH"); prints FILE
agent-desktop windows                        one line per window
agent-desktop focus NAME                     bring the window named NAME to the front (what NAME matches differs by computer, below)
agent-desktop move X Y                       move the pointer to X,Y
agent-desktop click X Y [left|right|middle]  move, then click (left by default)
agent-desktop type TEXT                      type TEXT
agent-desktop key KEY [MOD...]               press KEY with the modifiers held, for example: key comma ctrl
agent-desktop cursor                         print the pointer position as "X Y"
agent-desktop ui ARGS...                     Macs and G14 only: hand ARGS to Vercel's agent-desktop (list and click controls by name)
```

Output: `shot` prints the file name. `windows` prints a tab-separated header line, then one line per window. `cursor` prints `X Y`. `ui` prints what Vercel's program prints and exits with its exit code.

Exit codes:

| Code | Meaning |
|---|---|
| 0 | ok |
| 1 | a tool failed, or printed something unexpected |
| 2 | a bad call. A wrong-shape call (no action, an unknown action, a missing or extra argument) prints the usage naming all eight actions. A bad value (a non-integer coordinate, an unknown button or key word) prints one error line starting with the action name; Windows also prints the usage |
| 69 | a needed tool is missing; the message names how to install it |

Log: every step writes one line to `agent-desktop.log` with the UTC time, a run id, the elapsed time, the step and its outcome. `type` logs the length of the text, never the text. On Linux and macOS the file is `~/.local/state/agent-desktop/agent-desktop.log` (under `$XDG_STATE_HOME` instead when it is set). On Windows it is `%LOCALAPPDATA%\agent-desktop\agent-desktop.log`.

A coordinate is a whole number; anything else exits 2. On Omarchy and Windows, coordinates are screen pixels. On a Mac they are points (see below).

### What differs by computer

| | Omarchy | Mac | G14 (Windows) |
|---|---|---|---|
| `windows` columns | class, title, at, size, workspace, xwayland | app, title, at, size, pid | app, title, at, size, focused, minimized |
| `focus NAME` matches | the window class | the app name, which is the first column of `windows` | the app name (with or without `.exe`, any case), else the exact title, else a title that contains NAME. No match exits 1. If Windows refuses to bring the window forward after trying each way it has (share input with the window in front, hold Alt, the shell's switch call, minimise and restore), exit 1; the log line `worker focus detail` says what was in front and which way worked |
| An unknown key or modifier name | exit 1 (`wtype` refuses it) | exit 2, before anything is sent | exit 2, before anything is sent |
| `ui` with no arguments | not offered | passed to Vercel's program as is | exit 2 |
| `agent-desktop save` and `agent-desktop restore` | Linux only (below) | not offered | not offered |
| Coordinates | pixels | points | pixels |

Key names are the Linux ones in every case (`comma`, `Return`, `BackSpace`, `Escape`, `F5`, letters, digits). Modifiers are `ctrl`, `shift`, `alt` and `super`. The Mac script also takes `option` for `alt` and `cmd` or `command` for `super`; the Windows script also takes `win`, `logo` and `meta` for `super`.

On a Mac, a pixel in a Retina screenshot is not a point. On a 2x display the screenshot is twice as wide and tall as the pointer space, so divide screenshot pixels by the scale before you pass a position to `move` or `click`. The same goes for the `at` and `size` columns of `windows`: they are points.

## The four computers

| Computer | What the eight actions use | `ui` | What it can do | Where the script comes from |
|---|---|---|---|---|
| Omarchy (Linux desktop) | Hyprland's `hyprctl`, `wlrctl`, `wtype` and `grim` | no | The eight actions plus screenshots the agent reads: about 9 of the 14 checks | `dot_local/bin/executable_agent-desktop`, personal profile only |
| Mac mini | macOS `screencapture` and `osascript` | yes | The eight actions, plus app controls by name | `66_agent_desktop_macos.sh`, from a dotfiles apply (both profiles on a Mac) |
| G14 (Windows 11 laptop) | Windows PowerShell 5.1 with .NET and user32, run by a scheduled task inside the logged-in desktop session | yes, through the same task | The eight actions, plus app controls by name | `windows/install.ps1`, run once by hand; dotfiles never deploys `windows/` |
| work Mac | the same as the Mac mini | yes | The same as the Mac mini, once set up (below) | the same `66` step, from the work profile |

The 14 checks are the ones from the earlier trials: J0 to J8 (install, screenshot, list windows, focus, move the pointer, click, type, press keys, report the pointer) and N1 to N5 (read three apps by label, calculator by labels, three runs in a row, a stale reference is refused, speed).

Vercel's agent-desktop is the only third-party program. It is pinned at v1.3.1 and used only behind `agent-desktop ui`; the eight actions use only what the operating system ships.

## Omarchy (personal Linux)

The Omarchy script is `dot_local/bin/executable_agent-desktop`. The eight actions are unchanged, and it has two more verbs, `save` and `restore` (below). Dotfiles installs it at `~/.local/bin/agent-desktop` byte for byte, on the personal profile only (the work profile has no Linux desktop). A check (`tests/agent-desktop/check_omarchy_unchanged.py SHA256`) renders it the way chezmoi would on personal Linux and compares its hash with the SHA256 you give it; it is not a comparison with the base script, which differs from this one by `save` and `restore`.

It drives Hyprland 0.56.2, which uses a Lua config. The old `hyprctl dispatch movecursor 737 277` and `focuswindow class:X` fail with a Lua syntax error, so the script uses `hyprctl dispatch 'hl.dsp.cursor.move({x=737,y=277})'` and `hyprctl dispatch 'hl.dsp.focus({window="class:X"})'`. Hyprland has no click dispatcher, so a click is a move followed by `wlrctl pointer click left`. `wlrctl` is an AUR package (`yay -S --needed wlrctl`); a missing tool exits 69 and names its package.

What it cannot do: the bar on Omarchy is the eight actions plus screenshots the agent reads, which is about 9 of the 14 checks (J0 to J8). It cannot list buttons by name; N1 to N4 are recorded as not offered, because Omarchy's apps do not show their buttons by name, and there is no `ui` action. Reading labels there is out of scope.

### `agent-desktop save` and `agent-desktop restore` (Linux only)

These two verbs are not part of the contract above and exist only in the Omarchy script, because Hyprland is where an agent's browser or screen work moves the focus Michael is using (`follow_mouse` focuses the window under the pointer, and `agent-desktop focus` and `click` change focus on purpose). The Mac and G14 scripts have no such verbs.

```
agent-desktop save      remember the active window (by address) and the pointer position
agent-desktop restore   put back what the agent moved: focus the remembered window and move the pointer back, then forget the record
```

Call `agent-desktop save` first, before anything that touches Chrome or the screen, and `agent-desktop restore` last. The record is one file per caller, `~/.local/state/agent-desktop/saved-focus.KEY` (under `$XDG_STATE_HOME` when it is set), holding the address, the pointer and the time. KEY is the caller's `$T3CODE_THREAD_ID`, else its `$CLAUDE_CODE_SESSION_ID`, with every character outside `A-Za-z0-9._-` turned into `_`. Every call one agent makes carries the same value and two agents carry different ones, so two agents can `save` and `restore` at the same time and each `restore` reads only its own record. With neither variable set (a plain terminal) the file is `saved-focus` with no key, shared by whoever calls without one; one agent or Michael alone gets the old behaviour. A record left by an agent that never restored is only ever seen by that same caller, and its next `save` keeps it (first record wins). 

`restore` puts back only what the agent moved, and leaves the rest. While a record exists, `focus` notes the window it focused (`agent_window=`) and `move` and `click` note the point (`agent_pointer=`, the last one counts); with no record they write nothing. `restore` refocuses the saved window only when the active window is the agent's: one it focused, or one of the agent Chrome profile's processes. If Michael switched to another window, that window keeps focus and `restore` says so. It moves the pointer back only when it refocused or the pointer is still where the agent's last `move` or `click` put it. It focuses first and moves the pointer second, because changing workspace warps the pointer; it then checks focus once more after every pointer move, because `follow_mouse` may hand focus to whatever is under the pointer: the window that had focus before the move gets it back (the saved window when `restore` refocused it or it was already active, otherwise the window that kept focus).

Cases:

| Case | Result |
|---|---|
| `restore` with nothing saved | exit 1, says to run `agent-desktop save` first, makes no Hyprland call |
| the saved window no longer exists, and the active window is the agent's | exit 1 and names the address, even though `hyprctl` itself exits 0 with a warning; the pointer still moves and the record is deleted |
| the saved window no longer exists, and Michael's own window is active | `restore` keeps that window and exits 0; it never asks for the saved window, so it cannot find it gone |
| no window is active when `restore` runs (for example an empty workspace) | `restore` says there is no active window, does not refocus the saved window (an empty workspace Michael chose looks the same), moves the pointer back only if the agent moved it, exit 0 |
| no window was active at `save` | `save` succeeds; `restore` moves the pointer only (when the agent moved it), says there is no window to refocus, exit 0 |
| `save` twice by one caller | the second keeps the first record, prints `already saved <N>s ago; first record kept`, exit 0 |
| two callers `save` and `restore` at once | each has its own record: each `restore` puts back the window its own `save` found, and a caller with no record of its own gets `nothing saved` (exit 1) even when another caller's record exists |
| the saved window is already active | `restore` makes no focus dispatch; the pointer goes back only if the agent moved it |
| the active window is neither the saved one nor the agent's | `restore` leaves focus there, says it kept focus on that window, exit 0 |

Each of the two writes one line to `agent-desktop.log` with the run id and the outcome. Tests: `tests/agent-desktop/test_agent_desktop.py` (`test_save_*`, `test_restore_*`, and the per-caller ones: `test_two_callers_*`, `test_a_caller_*`, `test_a_second_save_*`, `test_the_claude_code_session_*`, `test_a_key_with_*`).

Reproduce: `chezmoi apply ~/.local/bin/agent-desktop` (after the preflight in `AGENTS.md`), then `agent-desktop cursor`. Tests: `python3 -m unittest discover -s tests/agent-desktop -v`.

## Mac mini and any Mac

A Mac gets the macOS script from the install step `run_onchange_after_66_agent_desktop_macos.sh.tmpl` (its deploy name is `66_agent_desktop_macos.sh`). It copies the macOS script, from `.chezmoitemplates/agent-desktop-macos.sh`, to `~/.local/bin/agent-desktop`, and downloads Vercel's agent-desktop v1.3.1 for the Mac's architecture into `~/.local/share/agent-desktop/vercel/`. It downloads the release archive and the release's `checksums.txt`, checks the archive against it, and installs everything the archive holds at the top level: `agent-desktop` and `agent-desktop-macos-helper`. Applying again downloads nothing and changes nothing (the folder's `.installed` file records the version and the processor). Both profiles, personal and work, run this step on a Mac; Linux and Windows skip it. It is a run step and not a managed file because chezmoi refuses two source files for one destination, and `~/.local/bin/agent-desktop` is already the Linux script's destination.

The eight actions use `screencapture` for `shot` and `osascript` (JavaScript for Automation: the window list, pointer, key and typing events from Core Graphics, and AppKit's NSRunningApplication for focus; nothing talks to System Events, so no Automation permission is needed). `ui ARGS...` runs the Vercel binary, and `AGENT_DESKTOP_UI_BIN` overrides its path. If the binary is missing, `ui` exits 69 and says how to install it.

The script is copied before the download, so if the download fails, the eight actions still work. A failed download, a checksum that does not match, an archive that will not unpack, or a processor Vercel has no build for makes the step exit 1. chezmoi then stops the apply at that step, so steps 70 and later do not run until the next apply that gets past it. The step is retried at every apply until it succeeds.

Permissions. macOS gives Screen Recording (macOS 27 calls it Screen & System Audio Recording) and Accessibility to the app that started a process, and a plain ssh shell has neither. On the Mac mini, the personal profile installs a small helper that runs inside kitty, which already has both, so nothing is granted to ssh. Over ssh, `agent-desktop` hands the whole call to the helper before it touches the screen and returns the helper's stdout, stderr and exit code unchanged. What the helper is, how it starts and how to restart or check it are in "Mac mini permissions (host change)" below.

The work profile leaves the helper and its login item out: the work Mac's permission route is settled after merge by a read-only check of its limits, and each action there is its own ask (see "Work Mac"). Without the helper an ssh call runs in place. A call that runs in place and finds a permission missing exits 1 with a message that names Screen Recording or Accessibility and this page. It names the fix for where the call ran: kitty when it ran in the helper, your terminal app when you ran it at the Mac, and for an ssh call with no helper (the work Mac) it says that allowing kitty does not help and points to "Work Mac". Without the Screen Recording permission, window titles come back blank, so the script says so rather than printing blanks.

Reproduce: on a Mac, run a dotfiles apply (`chezmoi apply`). To redo one Mac by hand, delete `~/.local/bin/agent-desktop` and `~/.local/share/agent-desktop/`, then render and run the `66` step: `chezmoi execute-template < run_onchange_after_66_agent_desktop_macos.sh.tmpl | sh`. That works as written when you run it in the Mac's chezmoi source. From any other copy of this repo (a worktree, a scratch copy), name the copy: `chezmoi --source <copy> execute-template < <copy>/run_onchange_after_66_agent_desktop_macos.sh.tmpl | sh`. Then check with `agent-desktop cursor`.

### Mac mini permissions (host change)

What it is. `agent-desktop-relay` (source: `.chezmoitemplates/agent-desktop-relay.sh`) is a loop that runs in a small kitty window. The helper asks kitty for a minimized window, but kitty 0.37 on macOS ignores that, so `agent-desktop-relay start` hides that kitty once the helper is up (NSRunningApplication `hide`, which needs no permission; a failure is only logged). The window shows for about a second while kitty opens and may take the keyboard focus then. The helper keeps working hidden; to see it, click kitty's Dock icon or use Cmd+Tab. It takes one call at a time, runs `~/.local/bin/agent-desktop` with the caller's arguments in the caller's folder, and hands back stdout, stderr and the exit code byte for byte. Arguments with spaces, quotes, newlines or nothing in them arrive as given. Calls from several ssh sessions at once are run one after the other, each with its own answer. Standard input is not passed on, and neither is the caller's environment (an `AGENT_DESKTOP_UI_BIN` set in the ssh shell does not reach the helper; the helper's own environment applies). A call and its answer travel as files in `~/.local/state/agent-desktop/relay/`, and the helper's pid file is there too.

When a call goes to it. `agent-desktop` sends the call to the helper when it runs in an ssh session (`SSH_CONNECTION` is set), is not already inside the helper, and the helper is installed. Anywhere else, such as a shell in kitty or a Mac with no helper, it runs the call itself. Measured on the Mac mini, forwarding adds about 0.1 s (`cursor`: 167 ms forwarded, 67 ms run in place).

Which permissions it uses. kitty's own: Screen & System Audio Recording and Accessibility. Nothing is added for ssh.

Start at login. A per-user login item, `~/Library/LaunchAgents/com.cartwmic.agent-desktop-relay.plist`, runs `agent-desktop-relay start` when the user logs in. `start` opens kitty with `open` (so kitty, not launchd, is the app macOS checks) and waits until the helper is up. The `66` step on the personal profile installs the helper and the login item, loads the login item and starts the helper, so an apply over ssh leaves it working without a login. Applying again changes nothing. A new copy of the helper restarts it. If the login item will not load or the helper will not start (nobody is logged in at the Mac, for example), the step prints a WARN and still succeeds, and the login item starts the helper at the next login.

By hand, from any shell on the Mac (over ssh too):

- `agent-desktop-relay status` prints `running (pid N)` and exits 0, or prints `not running` and exits 1.
- `agent-desktop-relay start` starts it if it is not running.
- `agent-desktop-relay stop`, then `agent-desktop-relay start`, restarts it. Closing its kitty window stops it too.

Helper not running. A call over ssh exits 1 with one line that names the helper, says `agent-desktop-relay start`, and points at this page. If the helper stops during a call, the call exits 1 and says so.

No Automation permission. `focus`, `type` and `key` used to talk to System Events, which makes macOS ask on the Mac's screen "kitty wants access to control System Events". They now post key events and activate apps directly, so they need only Accessibility, and nobody has to allow anything beyond the two permissions above. If that System Events question is on the Mac's screen from an earlier build, it can stay unanswered. What `focus`, `type` and `key` do now:

- `focus NAME` activates the running app whose name is exactly NAME (the first column of `windows`). The app comes to the front; which of its windows takes the keys is the app's choice, so click into the field you want before typing if the app has several windows.
- `key KEY [MOD...]` presses each modifier key, then KEY with the modifier flags set, then lets go, the way a keyboard does.
- `type TEXT` presses the key that makes each character on a US keyboard, with Shift held for capitals and symbols like `!` and `"`, a short pause between characters; newline is Return and tab is Tab. Characters with no key on a US keyboard (an accented letter, an emoji) are refused with exit 1 before anything is typed: setting a Unicode string on the key event did nothing on macOS 27. Apps may still change what arrives (TextEdit capitalizes the first letter of a sentence).

When kitty loses its permissions. macOS asks again about Screen Recording about once a month, and it asks on the Mac's screen. Michael re-allows kitty there, or under System Settings > Privacy & Security > Screen & System Audio Recording (and Accessibility), by switching kitty on.

Log. A forwarded call writes one `relay call` line in `agent-desktop.log` (its run id and exit code). The helper passes that run id to the script, so the script's own step lines for the call carry the same id. The helper also logs when it starts and stops. `type` logs only the length of the text.

Reproduce: on the Mac mini, run a dotfiles apply (`chezmoi apply`), or the `66` step by hand as above; then `agent-desktop-relay status`, and from another machine `ssh mac-mini agent-desktop cursor`. To start clean, run `agent-desktop-relay stop`, delete `~/.local/bin/agent-desktop-relay` and `~/Library/LaunchAgents/com.cartwmic.agent-desktop-relay.plist` (after `launchctl bootout gui/$(id -u)/com.cartwmic.agent-desktop-relay`), and run the `66` step again.

## G14 (Windows 11 laptop)

The G14 is not a dotfiles machine: chezmoi deploys nothing there, and the `windows/` folder is never copied into a home folder. Its files come from `windows/install.ps1` in this repo. See [windows/README.md](../windows/README.md) for what each file does. The scripts run on Windows PowerShell 5.1, which ships with Windows 11. The G14 has no PowerShell 7.

Why a scheduled task: an ssh session on the G14 lands in a session with no desktop, and screen actions only work inside the logged-in desktop session. So a scheduled task named `agent-desktop` runs one long-lived worker inside the desktop session (started at logon, and by any call that finds none running). `agent-desktop` writes each call as a request file, the worker does the action and writes an answer file, and the command prints it and exits with its exit code. The command is a small compiled program, `agent-desktop.exe` (built from `windows/agent-desktop-client.cs` by `install.ps1`, with the C# compiler that ships with Windows), because starting `powershell.exe` alone takes 270 ms on the G14 and the program takes 30 ms. A call that finds the worker running starts nothing: measured over ssh on the locked G14 it cost 0.1 to 0.16 s more than an ssh round trip with no command, the worker picks a request up in about 15 ms, and a `ui click` adds about 0.3 s for the Vercel tool. `agent-desktop.cmd`, which runs `agent-desktop.ps1` and takes 0.55 to 0.7 s a call, stays as the fallback. The first live run started a new PowerShell and loaded the ScheduledTasks module on every call and took 3.6 s per action, the second (worker, PowerShell command) 1.29 s per click. If nobody takes a request within 0.3 s the command runs `schtasks /Run` (one instance runs at a time, so a running worker ignores it), again each second until the request is taken. The worker checks for a locked screen on every request, and exits when `agent-desktop.ps1` changes, so old code never answers a call. The wait is on the file and has a time limit: if no answer arrives, the command exits 1 with a message and does not hang. A bad call is refused with exit 2 before any request is written, and so is `agent-desktop ui` with no arguments.

The time limit is 60 seconds. Set `AGENT_DESKTOP_TIMEOUT` (seconds) to change it; a value that is not a number, or is 0 or less, exits 2. When the limit passes, the command withdraws its request and ends the task (a stuck worker; the next call starts a new one), and the worker drops a request that is past its deadline and writes no late answer.

Files, all in `%LOCALAPPDATA%\agent-desktop\`: `request-<runid>.json` (the call: its id, action, arguments, the caller's folder, the path of Vercel's program, and the deadline), `answer-<runid>.json` (the exit code, stdout and stderr) `agent-desktop.log` (the worker also logs, per request, how long it waited and how long the action took, and at start the priority it runs at) and `worker.lock` (held by the running worker). A finished call removes both JSON files. A relative `FILE` for `shot` is resolved against the folder the caller ran in, because the task runs elsewhere. `agent-desktop ui` goes through the same scheduled task, because Vercel's program also only sees the screen from the desktop session.

A locked screen: the G14's screen can only be driven while it is unlocked. If the desktop session is locked, the command exits 1 with a message that says the screen is locked. It never returns a blank screenshot or an empty window list with exit 0.

Logging: each step is logged on both sides of the task (the command that takes the call, and the task that does the action) in `%LOCALAPPDATA%\agent-desktop\agent-desktop.log`, one line per step in the same format as the other computers, with the run id carried in the request. `type` logs only the length of the text.

Unlock: the G14 locks itself and its lock timeout does not change. To use it, Michael unlocks it at the keyboard, or from his Omarchy machine through RustDesk. An agent unlocks it only after an ask to Michael, each time. Nothing changes the G14's login, PIN, sleep, power, lock timeout or RustDesk settings, and it is locked again afterwards.

Install, from a machine with ssh access (here, through the Mac mini): copy the `windows/` folder to the G14, then run `powershell -NoProfile -ExecutionPolicy Bypass -File windows\install.ps1`. It:

- copies `agent-desktop.ps1` and `agent-desktop.cmd` into `%USERPROFILE%\.local\bin`, and builds `agent-desktop-client.cs` into `agent-desktop.exe` there (again only when the source changed; a failed compile exits 1 with the compiler's message, a missing compiler exits 69);
- downloads Vercel's agent-desktop v1.3.1 (`agent-desktop-v1.3.1-x86_64-pc-windows-msvc.tar.gz`), checks it against the release's `checksums.txt`, and unpacks `agent-desktop.exe` under `%USERPROFILE%\.local\share\agent-desktop\vercel\`;
- registers the scheduled task `agent-desktop`, set to run only when the user is logged on, so it runs in the desktop session. It starts at logon, runs one instance at a time with no time limit, and runs on battery. If a task of that name exists with a different command or different settings, it is registered again. When a script or the task changed, the install ends the old worker and starts a new one, so the first call after an install is already fast;
- adds `%USERPROFILE%\.local\bin` to the user PATH if it is missing. It reads and writes the user PATH with `reg.exe` under `HKCU\Environment` and keeps the value's type, so entries such as `%USERPROFILE%\bin` keep working. A new ssh session or sign-in sees the change.

The download uses `curl.exe` and `tar.exe`, which ship with Windows 11; if either is missing, the install exits 69. A failed download or a checksum that does not match exits 1 and installs nothing from the archive. The installed Vercel version is recorded in `version.txt` next to `agent-desktop.exe`. The two scripts are compared by SHA-256 and replaced only when they differ.

It changes no login, PIN, sleep, power or RustDesk setting. A second run changes nothing and downloads nothing; it says so.

Reproduce: the install steps above, then `agent-desktop cursor` while the G14 is unlocked. To start clean, remove the files in `.local\bin` (`agent-desktop.ps1`, `.cmd`, `.exe` and `.exe.source-sha256`), the Vercel folder, the scheduled task, the `%USERPROFILE%\.local\bin` entry in the user PATH and the folder `%LOCALAPPDATA%\agent-desktop\`, and run the install again. The install puts the PATH entry back only if it is missing.

## Work Mac

The work profile gives a work Mac the same setup as any Mac: the `66` step runs on a dotfiles apply and installs the same script and the same pinned Vercel program, but not the kitty helper or its login item (`66` installs those on the personal profile only). Why: the kitty helper is for a computer an agent reaches over ssh, and the work Mac has ssh off (see below). The Omarchy script and the Windows files are personal only; the work profile has no Linux or Windows machine (see [profiles.md](profiles.md)).

On the work profile, a blocked GitHub download makes the `66` step exit 1 and stops the apply there; steps 70 and later wait for the next apply.

No agent installs, applies, grants a permission or runs a check on the work Mac without Michael. Each such action is its own ask to him, and a yes covers only the action it names. No keyboard or mouse input goes through the KVM without his OK for each test. Michael takes the merged dotfiles there with his own `chezmoi update`. The permissions in the Mac section are his to set. After that, each step (the read-only check of the Mac's limits, the permissions, the run of the eight actions and `ui` with saved output and screenshots) is its own ask. That run is `live_run.py work-mac` (see "Repeating a live run").

### What the read-only check found (2026-11-15)

Michael approved a read-only check of the work Mac (ask #1152). An agent there ran `sw_vers`, `uname -m`, `system_profiler SPConfigurationProfileDataType`, `nc -z 127.0.0.1 22` and `launchctl print system/com.openssh.sshd`, and changed nothing. It found:

- macOS 26.7.3 on Apple silicon.
- The installed management profiles neither block nor pre-allow Screen Recording, Accessibility, PostEvent or ListenEvent for `agent-desktop`'s terminal. The user may switch each one on in System Settings.
- A profile turns off the recurring macOS 26 "allow screen recording?" prompt, so a granted Screen Recording permission should stay granted. This is read from the profile, not seen.
- Screenshots are allowed by profile.
- Remote Login (ssh) is off, and no profile sets it. So on this Mac `agent-desktop` runs from a local terminal, the same as on the Mac mini without the helper.

The next step is Michael's: granting Screen Recording and Accessibility to the terminal that runs `agent-desktop`, then a run of the eight actions and `ui` with saved output. Each is its own ask.

## Repeating a live run

The live proof runs the 14 checks through the real path on one computer and saves a record. Run it from the repo root:

```
python3 tests/agent-desktop/live_run.py DEVICE [--out DIR] [--dry-run] [--only J2,J8] [--phase all|prepare|rows] [--unlock-timeout SECS]
```

`DEVICE` is `omarchy` (this machine), `mac-mini` (over ssh), `work-mac` (the Mac you start it on: no ssh, no copy) or `g14` (over ssh through the Mac mini). `--dry-run` prints the plan and the preconditions and changes nothing. `--only` runs just the named rows and writes `record.partial.json`. `--phase` applies to the G14: `prepare` installs, installs again, reads settings and checks the locked screen (the G14 must be locked); `rows` waits for the unlock, runs the rows and writes the record (the G14 must be unlocked). Output goes under `--out`: each command's output as a text file, each screenshot as a PNG, and `record.json`. At the end the driver runs `tests/agent-desktop/check_record.py` on the record and exits with its status.

For `mac-mini`, the driver copies the working tree to the Mac mini and runs the install there from the copy, which is the `--source <copy>` form of the reproduce command above. The Mac needs the permissions from "Mac mini permissions (host change)" first.

For `work-mac`, the driver runs on the Mac it is started on. It copies nothing and uses no ssh: it removes the installed script and the Vercel folder, renders the `66` step from the working tree and runs it (the work profile leaves out the kitty helper), then runs the same 14 checks in place. `check_record.py --device work-mac` judges the record like a Mac: the same rows must pass as for the Mac mini, against the same source files. Start it from a terminal that holds Screen Recording and Accessibility (see "Work Mac"). Because it installs on that Mac, it is Michael's run, or one he has agreed to (see "Work Mac"). On a machine that is not a Mac, `--dry-run` prints the plan and shows the Mac precondition as `MISSING`, and a real run stops with exit 3 before it does anything.

How the checks read the Mac: the Calculator display is read from a `ui snapshot` taken without `-i` (with `-i` the display text is left out) and only from its static text, so a button named `7` is never the display; the app in front is read from the system (`NSWorkspace`, the frontmost application), not from `ui list-windows` `is_focused`; and a click or key is sent only after the system reports the target app in front, because `focus` asks the app to come forward and returns at once.

## Where the checks live

`tests/agent-desktop/` holds the tests; `tests/profiles/` holds the profile table checks. See [the Linux script](../dot_local/bin/executable_agent-desktop) for the contract on Omarchy.
