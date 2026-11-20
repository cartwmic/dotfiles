---
name: using-browse
description: Use for any task in a web page, as Michael: open or read a site, sign in, fill a form, click, scrape, download a file, pass a 1Password or passkey prompt, or check how a page looks. Browse (the browse MCP server) is the default browser tool; agent-desktop handles what is outside the page. Use it without being told to; do not start another browser or browser tool.
---

# Using Browse

Browse (`browse` MCP server) drives the agent Chrome (the one at 127.0.0.1:9333, profile ~/.local/share/agent-chrome-profile). Use it by default. Do not
start another browser or tool. Personal accounts only; never the work Mac.

## Start
1. Call the `status` tool. It lists connected browsers, pairing, tabs, and `nextStep` if something is missing. The relay starts on the first Browse call, and the extension reconnects about 1-2 seconds later. So if `status` says the browser is not connected or `paired-offline` right after that first call, wait about 5 seconds and call `status` again, up to 3 times. If no browser is connected after that: check `systemctl --user status agent-chrome`
   (or run `agent-chrome`). If `status` still shows no connected browser or no pairing (a new machine or a new agent-chrome profile), run `agent-browse-setup` in the background (it waits up to 3 minutes for the steps below, and a shell shows no output until a command ends; read its output when it ends): it starts the agent Chrome, opens the Web Store page if the extension is missing (neither its service worker nor its folder in the agent Chrome profile), opens the extension settings, runs `browse pair` with the code in a 0600 file (never printed) and ends with `browse status`. It prints the click or typing it cannot do (click Add to Chrome; click Pair with a code, type the code with `agent-desktop type "$(cat <the code file it names>)"`, which keeps the code out of the output, and click Connect); do those with the screen tool below, and it exits non-zero until `browse status` shows connected (agent-harness README, "Agent browser" > "Pair Browse"). Do not ask Michael until you have tried that.
2. Open a page: `execute` with `await page.goto("https://...")`. The result starts with `tab: <id>`.

## The tab is the handle
- Pass that id as `tab` to every later `execute` (and `tabs`). Without `tab`, `page.goto` opens a new tab.
- You only see tabs you opened (and tabs Michael lent). Idle agent tabs close after 10 minutes, so a saved id can go stale: call `tabs` (list) before reusing one; reopen if it is gone.
- Close tabs you opened when you are done (`page.close()` or `tabs` close). Never close a tab you did not open. A tab Michael lent is given back, not closed.

## Read and act
- `snapshot()` returns a compact outline with refs (`e12`). Act on a ref: `await ref("e12").click()`, `.fill("text")`. Prefer snapshot plus ref to guessing selectors; take a new snapshot after the page changes (`snapshot({ diff: true })`).
- `return await page.screenshot()` to look at the page when text is not enough.
- Browse does not clear cookies or storage and refuses other extensions' pages and `file:` URLs. A bot check or captcha is reported to you: do not retry-loop it.
- Menu popups (a right-click or dropdown menu) are missing from `snapshot()`. A Playwright text selector still finds them: `browse click --tab 12 --selector 'text=Rename'` (the same `--selector` works in `execute` and the other tools).
- `handoff()` and `demonstrate()` ask Michael to act. Do not use them until you have tried the 1Password extension, his Beeper and Gmail for login codes, and screen control (below).

## The `browse` command line
`browse status` shows the pairing in a shell. Its `Setup: not installed. Run browse install` and `Updates: not installed in a way that updates` lines can appear, and they are expected: this machine never runs `browse install` (it would write a self-updating copy over the pinned one) and Browse's own updates are off on purpose. Do not act on them. `Extension: connected` is the line that matters.
A command takes the tab first, so a value after a ref is read as the tab: `browse fill e52 Hello` fails with "--tab takes integer". Pass each argument as a flag, or the whole call as JSON:
```
browse fill --tab 12 --ref e52 --value "Hello"
browse fill --json '{"tab":12,"ref":"e52","value":"Hello"}'
```

## Downloads
Browse has no download tool. Use `agent-download`:
1. `mark=$(agent-download mark)` before the click.
2. Click the download in the page with Browse. The click can take up to about 15 seconds to return; that is normal.
3. `path=$(agent-download wait --mark "$mark")` prints the file's path (exit 1 if nothing arrives in 60 s: `--timeout N` changes it). Use that path; do not guess a file name, and `rm` the file when you are done with it.

## Sign in: `agent-login`
Sign in without the 1Password extension. For each field: click it with Browse (so it has focus), then run `agent-login username <part of the page URL>`, and the same with `password` and `otp`. Then submit with Browse.
It types the value from the `developer` vault login whose URL has exactly that page's host, and prints only what it typed. If it refuses, it says why (no login for that host, several logins: it lists each title with its id; pick one with `--item <id>`, no field has focus: click the field again).
Use the 1Password popup (next section) only for passkeys, or when `agent-login` says there is no login for that host.

## Outside the page: `agent-desktop`
Browse cannot see the 1Password popup, passkey prompts or browser dialogs. Use the screen tool (docs/agent-desktop.md):
1. Make the page's tab the active one and the Chrome window the keyboard-active one: `agent-chrome focus <part of the page URL>`, then `agent-desktop focus google-chrome`
   (a floating 1Password desktop window can sit on top; the second command fixes that).
2. Open the 1Password popup: `agent-desktop key x ctrl shift`. Wait about 2 seconds, then `agent-desktop shot /tmp/x.png` and read the image. Escape closes the popup: `agent-desktop key Escape`.
3. Pick the entry for that exact host; confirm with `agent-desktop key Return`. Then return to Browse and `snapshot` to confirm you are signed in.
Keep screen input short: every agent on the desktop shares it. Do not leave a popup open. If a code is needed (email, text), read it from Gmail or Beeper; do not ask Michael first.

## 1Password rules
- 1Password personal account only. Never print or log a password, code or token.
- Every login you add or edit in 1Password fills only on its exact host (the full subdomain it was made for: "only fill on this exact domain"), not the parent domain. Fix an existing agent-made login the same way when you touch it.
