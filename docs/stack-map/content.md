<!-- PLACEHOLDER: three valid citations and a four-step flow so the generator can be tested. The real content replaces this file. -->
# Agent stack map

## Start here

This is a placeholder. The coordinator is the program that watches the agents.[[coordinator:package.json:2|"name": "coordinator"]]

## The one-minute picture

Dotfiles install the tools[[dotfiles:README.md:1|# Dotfiles]] and **agent-kit** is a library `@cartwmic/agent-kit`.[[agent-kit:package.json:2|"name": "@cartwmic/agent-kit"]]

## What each repository is for

Each repository does one job.

| Repo | Job |
|---|---|
| dotfiles | machines [[dotfiles:README.md:1|# Dotfiles]] |

## How a piece of work moves

```flow
1. Michael | asks the coordinator for something | coordinator:README.md
2. Coordinator | opens a ledger ask `ledger open` | src/ledger/cli.ts
3. Lead | starts a builder | coordinator:leads
4. Builder | opens a pull request | dotfiles:README.md
```

## Where do I change X?

| Change | Where |
|---|---|
| bump agent-kit | `dot_local/share/agent-kit/package.json` [[dotfiles:dot_local/share/agent-kit/package.json:2|"name"]] |

## Glossary

- **seat**: the role an agent plays.
