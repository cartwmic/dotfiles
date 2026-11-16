# windows/

The G14 (Michael's Windows 11 laptop) files for `agent-desktop`. chezmoi never deploys this folder on any computer or profile (`.chezmoiignore` lists `windows/`); dotfiles has no Windows apply. The install script puts the files in place instead.

| File | What it is |
|---|---|
| `install.ps1` | Run once on the G14. Copies the two scripts below into `%USERPROFILE%\.local\bin`, builds `agent-desktop-client.cs` into `agent-desktop.exe` there, downloads Vercel's agent-desktop v1.3.1 (checked against the release's checksum), registers the scheduled task, and adds `.local\bin` to the user PATH. A second run changes nothing. |
| `agent-desktop-client.cs` | The command agents run, as a small compiled program (`agent-desktop.exe`, built by `install.ps1`; it starts in 30 ms where powershell.exe takes 270). Takes the call, writes it as a request for the worker, waits for the answer and prints it. |
| `agent-desktop.ps1` | The worker: the scheduled task runs it (`--worker`) inside the logged-in desktop session, and it does the action. Also works as the command by itself, the slower fallback. |
| `agent-desktop.cmd` | A two-line wrapper that runs the PowerShell command; the fallback when no `.exe` is built. |

These run on Windows PowerShell 5.1, the version the G14 ships with. The G14 has no PowerShell 7.

How the pieces fit, the unlock step, and how to reproduce the setup are in [docs/agent-desktop.md](../docs/agent-desktop.md), section "G14".
