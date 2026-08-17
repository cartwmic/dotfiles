# subagent depth cap

Chezmoi **source** for a one-key Pi extension config. It caps nested
subagent depth at `1`. This directory is not the pi-subagents runtime
and does not define agents.

The runtime that reads this file is the separately installed
[pi-subagents](https://github.com/nicobailon/pi-subagents) package
(`pi install npm:pi-subagents`). Agent definitions, slash commands,
and workflows live in that package. This folder ships only
[config.json](./config.json).

## Overview

`pi-subagents` loads optional JSON from
`~/.pi/agent/extensions/subagent/config.json`. This source currently
contains one key:

```json
{
  "maxSubagentDepth": 1
}
```

`maxSubagentDepth` is the nested-delegation cap when no inherited
`PI_SUBAGENT_MAX_DEPTH` is already in effect. With `1`, a parent session
can spawn children; those children cannot spawn further nested
subagents. There is no `index.ts` here; Pi does not load TypeScript
from this directory.

## Setup

Work in the chezmoi source. Confirm this overlay is present:

```sh
cd ~/.local/share/chezmoi/dot_pi/agent/extensions/subagent && ls -1
```

You should see [config.json](./config.json) and this README. Chezmoi
maps this directory to `~/.pi/agent/extensions/subagent`. The `termux`
profile skips `.pi`, so this overlay does not deploy there.

The runtime is not installed by this folder. Install it with Pi
(`pi install npm:pi-subagents`) if it is not already present. After an
apply that includes this dest, start a new Pi process so the installed
extension re-reads config.

## Usage

The live dest is generated. Edit **this** [config.json](./config.json),
not `~/.pi/agent/extensions/subagent/config.json` by hand.

To change the cap, set `maxSubagentDepth` in the source file, then
apply only this destination:

```sh
chezmoi apply ~/.pi/agent/extensions/subagent
```

Then start a new Pi process. This README does not apply for you.

Do not add agent markdown, workflows, or an `index.ts` here unless you
intend to replace the npm runtime. Custom agents belong in the
pi-subagents layout, not this overlay.

## Validation

There is no test file. Assert the source cap is `1`:

```sh
cd ~/.local/share/chezmoi/dot_pi/agent/extensions/subagent
cat config.json
test "$(jq -r '.maxSubagentDepth' config.json)" = 1
```

Exit 0 means the source JSON parses and `maxSubagentDepth` is `1`.
That does not prove pi-subagents is installed or that a live Pi
session honors the cap.
