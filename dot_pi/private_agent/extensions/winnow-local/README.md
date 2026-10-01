# Local Winnow in Pi

## Purpose

This extension makes a local [Winnow-12B](https://huggingface.co/EldanRing/Winnow-12B)
server available to Pi as the classifier model `winnow/winnow-12b`. Winnow is a
Jev-class decision model: it answers Choice, yes/no, and Score questions about
supplied state, with probabilities. It speaks TypeSafe's native System One
protocol at `POST /v1/systemone`, so the same server also backs the
[System One](../system-one/README.md) `system_one` tool and `/so` commands.

Winnow-12B Q8 ranked #2 on [JevBench v1.5.4](https://benchmarkheaven.com/jev-models)
(73.2, a statistical tie with #1 and ahead of hosted Jev 1.13 at 72.1). It runs
on Apple Silicon through Metal; the upstream install guide checked a 24 GB M4 Pro.

The extension does not start, install, or download anything. Without a running
server, Pi still lists the model, and calls fail with a hint pointing here.

## Setup

One-time, per machine. Needs the Xcode command-line tools, Homebrew, about
13 GB for weights, and 20 GB free disk during setup:

```sh
xcode-select --install          # skip if already installed
brew install python cmake openssl@3
git clone https://github.com/EldanRing/winnow-inference.git ~/git/winnow-inference
cd ~/git/winnow-inference
python3 scripts/setup.py --profile apple-silicon --text-only
```

`setup.py` checks prerequisites, builds the Metal server, downloads and verifies
the Q8 weights into `models/`, and runs a unit test. `--text-only` skips the
vision projector, which typed decisions do not use.

For the `system_one` tool, add a catalog connection. This refuses to replace
an existing catalog; if you have one, add the `winnow` entry by hand or with
`/so settings`:

```sh
mkdir -p "${XDG_CONFIG_HOME:-$HOME/.config}/system-one"
( set -C; cat > "${XDG_CONFIG_HOME:-$HOME/.config}/system-one/connections.json" <<'JSON'
{"version":1,"default":"winnow","connections":{"winnow":{"baseURL":"http://127.0.0.1:8091/v1","model":"winnow-12b"}}}
JSON
)
```

No credential is needed.

## Usage

### Launch local Winnow

Start the server in a terminal you keep open. It is not a background service;
nothing starts it at login.

```sh
cd ~/git/winnow-inference
python3 scripts/serve.py --profile apple-silicon --text-only --alias winnow-12b
```

Loading takes a minute or two. It is ready when the log says
`listening on http://127.0.0.1:8091`. Keep `--alias winnow-12b`: the server
rejects other model names, and both Pi and the catalog use this one. The loaded
model holds about 13 GB of unified memory. Stop it with Ctrl+C to free that.

In Pi, run `/winnow` to check whether the server is reachable.

### Call it from Pi

Codemode scripts:

```js
const m = await models.getModelOfType("classifier", "winnow", "winnow-12b");
const r = await models.classify(m, {
  state: { message: "The deploy failed: 3 integration tests are red." },
  questions: {
    ship: { type: "bool", instructions: "Is it safe to ship?", criteria: { true: "Safe", false: "Not safe" } },
  },
});
return r.answers;
```

Extensions use `ctx.modelRegistry.classify()` with the same model. Calls cost $0.

System One tool: run `/so on` (or set the default in `/so settings`), and
select the `winnow` connection. `/so ask` works for manual requests.

## Validation

With the server running:

```sh
curl -s http://127.0.0.1:8091/health   # {"status":"ok"}
curl -s http://127.0.0.1:8091/v1/systemone -H 'Content-Type: application/json' \
  -d '{"model":"winnow-12b","state":"Checkout returns 500 errors.","questions":{"q":{"type":"noul","instructions":"Is this urgent?"}}}'
```

In Pi, the codemode script above should return `stopReason: "stop"`.

## Troubleshooting

- Calls fail with "Is local Winnow running?": start the server (Launch above) and wait for `listening`.
- `Unknown model; use Winnow-12B or the configured alias`: the server was started without `--alias winnow-12b`.
- `winnow/winnow-12b` missing from `models.getAvailableOfType("classifier")`: the extension did not load, or Pi's
  built-in `typesafe` provider changed shape. Run `pi list` and check startup errors.
- Pi's `models.json` cannot declare classifier models (as of Pi 0.99.2), so this extension is required for the native path.
- Port 8091 in use: `serve.py --port` changes it, but this extension and the catalog expect 8091.
