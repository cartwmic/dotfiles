# Neovim LazyVim overlay

Chezmoi source for `~/.config/nvim`. This is a **local overlay** on
[LazyVim](https://github.com/LazyVim/LazyVim), not the upstream starter
README. LazyVim is pulled in by [lazy.nvim](https://github.com/folke/lazy.nvim)
at runtime. Local specs live under [`lua/plugins/`](./lua/plugins/). Do not
copy the LazyVim plugin tree into git.

## Overview

[`init.lua`](./init.lua) bootstraps the Python 3 host, then loads
[`lua/config/lazy.lua`](./lua/config/lazy.lua). That file clones `lazy.nvim`
if needed and starts LazyVim plus this overlay:

- `{ "LazyVim/LazyVim", import = "lazyvim.plugins" }` — upstream LazyVim
- `{ import = "plugins" }` — this tree's specs in [`lua/plugins/`](./lua/plugins/)

[`lazyvim.json`](./lazyvim.json) enables LazyVim extras (blink.cmp is the
completion engine; extras include DAP, Prettier, mini-snippets/surround,
yanky, dial, and language packs for Docker, Go, JSON, Markdown, Rust,
Terraform, TOML, TypeScript, and YAML). [`lua/plugins/example.lua`](./lua/plugins/example.lua)
is the stock starter example and returns an empty spec.

Pinned plugin commits are in [`lazy-lock.json`](./lazy-lock.json) (committed).
Refresh the lockfile from `:Lazy` inside Neovim, then commit with the
CodeCompanion prompt
[`prompts/git-commit-chezmoi-lazylock.md`](./prompts/git-commit-chezmoi-lazylock.md).

## Setup

This directory deploys as `~/.config/nvim` via chezmoi. Neovim must be on
`PATH`. Then create the dedicated Python 3 host (needs `pynvim`) and launch
the editor:

```bash
python3 -m venv ~/.local/share/nvim-python
~/.local/share/nvim-python/bin/pip install pynvim
nvim
```

[`init.lua`](./init.lua) sets `vim.g.python3_host_prog` to
`~/.local/share/nvim-python/bin/python3` when that binary exists. If it does
not, the Python 3 provider is disabled so startup does not error. First
launch clones `lazy.nvim` into Neovim's data directory and installs plugins
from the lockfile. Some specs also expect host tools that this overlay does
not install: Ranger (`rnvimr`), ImageMagick (`image.nvim`), coursier
(Metals), `uv` (VectorCode), and `sqlparse` for the Rust SQL formatter.

## Usage

Leader is Space; localleader is `\`. Clipboard uses `unnamedplus`.

Custom commands in [`init.lua`](./init.lua):

| Command | What it does |
| --- | --- |
| `:UserPutPKMSFileDateTimestampToClipboard` | Yank `%Y-%m-%d-%H%M%S` |
| `:UserPutCurrentTimestampToClipboard` | Yank `%H:%M:%S` |
| `:UserGitChangedFilesToQuickfix` | Unstaged, staged, and untracked files into the quickfix list |

Useful maps in [`lua/config/keymaps.lua`](./lua/config/keymaps.lua): `jk`
leaves insert mode; `<C-\>` leaves terminal mode; `<leader>zt` / `<leader>zT`
paste the timestamps above; `<leader>zGq` runs the git-changed-files command;
`<leader>dT` runs LSP codelens.

[`lua/config/options.lua`](./lua/config/options.lua) turns the mouse off,
disables relative numbers, and keeps `blink.cmp`.
[`lua/config/autocmds.lua`](./lua/config/autocmds.lua) is the LazyVim autocmd
hook and currently adds none.

### Local plugin specs

Files under [`lua/plugins/`](./lua/plugins/). [`example.lua`](./lua/plugins/example.lua)
returns empty; [`diagram.lua`](./lua/plugins/diagram.lua) is loaded as a spec
but turned off by [`disabled.lua.tmpl`](./lua/plugins/disabled.lua.tmpl).

| Spec | Role |
| --- | --- |
| [`colorscheme.lua`](./lua/plugins/colorscheme.lua) | `tokyonight-night` |
| [`disabled.lua.tmpl`](./lua/plugins/disabled.lua.tmpl) | Turns off bufferline and `cartwmic/diagram.nvim` (chezmoi renders this to `disabled.lua`) |
| [`grapple.lua`](./lua/plugins/grapple.lua) | Git-scoped file tags; `<leader>1`–`5` and `<leader>zg*` |
| [`lualine.lua`](./lua/plugins/lualine.lua) | Grapple in the statusline |
| [`fzf.lua`](./lua/plugins/fzf.lua) | fzf-lua: `<C-o>` to normal mode; grep `ctrl-alt-g` |
| [`gitlinker.lua`](./lua/plugins/gitlinker.lua) | `<leader>gy` / `<leader>gY`; browse host `git.taservs.net` |
| [`vim-fugitive.lua`](./lua/plugins/vim-fugitive.lua) | Fugitive |
| [`neotree.lua`](./lua/plugins/neotree.lua) | `Y` copies a chosen path form |
| [`ranger.lua`](./lua/plugins/ranger.lua) | `<leader>r` floating Ranger (`rnvimr`) |
| [`lsp.lua`](./lua/plugins/lsp.lua) | HTML/htmldjango snippet capability |
| [`treesitter.lua`](./lua/plugins/treesitter.lua) | Extra parsers (including Scala, HCL/Terraform, KDL) |
| [`nvim-metals.lua`](./lua/plugins/nvim-metals.lua) | Metals for Scala/sbt/Java (needs coursier) |
| [`rustaceanvim.lua`](./lua/plugins/rustaceanvim.lua) | rust-analyzer overlay |
| [`markdown.lua`](./lua/plugins/markdown.lua) | `tadmccorkle/markdown.nvim` maps |
| [`lint.lua`](./lua/plugins/lint.lua) | `markdownlint-cli2` config at `~/.config/.markdownlint-cli2.jsonc` |
| [`image.lua`](./lua/plugins/image.lua) | `magick_cli` processor; no luarocks build |
| [`diagram.lua`](./lua/plugins/diagram.lua) | Spec present but **disabled** in `disabled.lua.tmpl` |
| [`oscyank.lua`](./lua/plugins/oscyank.lua) | Visual `<leader>C` OSC52 copy |
| [`text-case.lua`](./lua/plugins/text-case.lua) | Case conversion; prefix `<leader>za` |
| [`abolish.lua`](./lua/plugins/abolish.lua) | vim-abolish |
| [`colorful-winsep.lua`](./lua/plugins/colorful-winsep.lua) | Active-window separator |
| [`vectorcode.lua`](./lua/plugins/vectorcode.lua) | VectorCode (`uv tool upgrade vectorcode` on build) |
| [`vim-just.lua`](./lua/plugins/vim-just.lua) | Justfile syntax |

[`after/plugin/sql_rust_automagic.lua`](./after/plugin/sql_rust_automagic.lua)
formats `sqlx::query*` raw strings in Rust on write via
[`bin/sql-format-via-python.py`](./bin/sql-format-via-python.py) (`python3` +
`sqlparse`). Command: `:RustFormatEmbeddedSql`.

[`snippets/markdown.json`](./snippets/markdown.json) adds a PKMS frontmatter
snippet. [`prompts/`](./prompts/) holds CodeCompanion prompts (lockfile
commit, unstaged commit, fix diagnostics).

## Validation

From this directory, confirm the overlay files that Neovim and the lockfile
depend on are present:

```bash
test -f init.lua && test -f lazy-lock.json && test -d lua/plugins && test -f lua/config/lazy.lua
```

To confirm Neovim loads this config without staying open:

```bash
nvim --headless +q
```

A zero exit means startup reached quit. Headless quit can abort in-flight
[mason.nvim](https://github.com/williamboman/mason.nvim) installs; that is
expected and does not mean the overlay failed to load. Plugin UI work
(`:Lazy`) and a lockfile commit still need an interactive session plus
[`prompts/git-commit-chezmoi-lazylock.md`](./prompts/git-commit-chezmoi-lazylock.md).
