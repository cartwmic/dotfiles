# windows/

The G14 (Michael's Windows 11 laptop) files for `agent-desktop`. chezmoi never deploys this folder on any computer or profile (`.chezmoiignore` lists `windows/`); dotfiles has no Windows apply. The install script puts the files in place instead.

| File | What it is |
|---|---|
| `install.ps1` | Run once on the G14. Copies the two scripts below into `%USERPROFILE%\.local\bin`, downloads Vercel's agent-desktop v1.3.1 (checked against the release's checksum), registers the scheduled task, and adds `.local\bin` to the user PATH. A second run changes nothing. |
| `agent-desktop.ps1` | The command. Takes the call, writes it as a request for the scheduled task, waits for the answer and prints it. The task runs the same script inside the logged-in desktop session and does the action. |
| `agent-desktop.cmd` | A two-line wrapper so `agent-desktop` works from cmd.exe and ssh. |

These run on Windows PowerShell 5.1, the version the G14 ships with. The G14 has no PowerShell 7.

How the pieces fit, the unlock step, and how to reproduce the setup are in [docs/agent-desktop.md](../docs/agent-desktop.md), section "G14".
