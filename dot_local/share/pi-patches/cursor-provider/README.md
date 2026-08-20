# pi-patch: cursor-provider

Adds this operator's own Cursor current-cycle spend versus a configured
included cap to the pi-sub usage widget, **on the chezmoi
`axon-work-computer` profile only**, without admin credentials and without
forking the widget.

## Why

On the work profile, a pi operator who spends Cursor enterprise credits
cannot see their own current billing-cycle usage against their included cap
while staying in pi. The usage widget already shows Anthropic extra credits
for the same operator. Cursor spend is otherwise visible only by leaving pi
for Cursor's dashboard.

The installed `@marckrenn/pi-sub-*` packages render every registered
provider as RateWindow rows, but Cursor is absent: their provider unions
are closed and there is no plugin hook. Widget package upgrades also wipe
any local customization of that widget. This patch is the supported way to
keep Cursor spend visible across upgrades: a work-profile-only runtime
customization of the tree pi actually loads, re-applied by the same
chezmoi pi-runtime-patch path used for the sibling patches. A forked
widget repository is not the delivery vehicle.

## What it changes

**Target:** the pi-loaded agent-npm tree

`~/.pi/agent/npm/node_modules/@marckrenn/pi-sub-{shared,core,bar}`

Not `@earendil-works/pi-coding-agent/dist/`, and not a disconnected global
npm copy of the widget.

Revision 1:

1. Drops `payload/cursor.ts` onto
   `pi-sub-core/src/providers/impl/cursor.ts` (`CursorProvider`, name
   `cursor`).
2. Splices closed collections so the widget can type, default, detect, and
   render that provider: shared `PROVIDERS`, `CoreProviderSettingsMap`,
   `PROVIDER_METADATA`; core `PROVIDER_FACTORIES`; bar
   `ProviderSettingsMap`, default settings, metadata, and settings UI.
3. Adds a monthly-cap control on the cursor provider settings screen. The
   fetcher reads `getSettings().providers.cursor.monthlyCapDollars` at
   fetch time (default **750**). That value is an operator-configurable
   included cap for this account, not a value discovered from Cursor. A
   missing member-scoped cap from Cursor does not prevent showing used
   amount against the configured cap.

`hasCredentials` is true only when `~/.pi/agent/auth.json` (the same token
pi already uses) yields `cursor.access`. No new secret store.

`fetchUsage` calls only these two **member-scoped** Cursor dashboard
endpoints with that session token:

| Method | URL | Used for |
|---|---|---|
| `POST` | `https://api2.cursor.sh/aiserver.v1.DashboardService/GetAggregatedUsageEvents` | operator current-cycle `totalCostCents` |
| `POST` | `https://cursor.com/api/dashboard/get-plan-info` | `billingCycleEnd` |

Results map to a single RateWindow: label is used amount / configured cap,
`usedPercent` is used/cap, and `resetAt` / `resetDescription` come from
`billingCycleEnd`. Fetch failures become the existing empty-snapshot error
path so other providers, including Anthropic extra credits, still render.

## Profile gate

This patch applies **only** when `PI_CHEZMOI_PROFILE=axon-work-computer`.
That variable is exported by the templated wrapper
`run_onchange_after_30_apply_pi_patches.sh.tmpl`
(`export PI_CHEZMOI_PROFILE="{{ .profile }}"`) before it runs the apply
loop.

- `PI_CHEZMOI_PROFILE=axon-work-computer` → apply (desired state is patched).
- Any other value, or unset (e.g. a manual `apply_pi_patches.sh` run) → do
  not apply; restore spliced files from `<file>.orig.chezmoi-pi-patch` and
  remove the dropped `cursor.ts`. Fail-safe default is "do not apply".
  State status is `unpatched`, which makes pi-patch-guard treat the patch
  as not intended-on.

Non-work profiles therefore do not gain a Cursor usage row from this
change. Ungated sibling patches ignore `PI_CHEZMOI_PROFILE` and continue
to run on all profiles.

## Safety properties

Mirrors the sibling patches' conventions:

- Marker comment `chezmoi-pi-patch:cursor-provider vN` in the dropped file
  and in each splice (`PATCH_REVISION` is 1).
- Single-occurrence anchor pre-check (aborts on drift without touching
  files).
- Backup before first edit of each spliced file as
  `<file>.orig.chezmoi-pi-patch` next to the target.
- TypeScript splices are written to a temp file and checked with Node's
  type-stripping checker before replace. A failed check leaves the
  original file in place.
- Idempotent re-runs, stale-revision restore, and a `--check` mode.

`--check` verifies without writes and exits 0 when the install already
matches the desired state for the active profile (patched on
`axon-work-computer`; unpatched otherwise). On a work-profile check, a
missing or stale install exits non-zero. On any other profile, `--check`
fails if splices are still present or if dropped `cursor.ts` still exists.

State is written to `~/.local/state/chezmoi-pi-patches/cursor-provider.json`
using the same `status` / `target` / `marker` fields so pi-patch-guard
auto-discovers it. `target` is the dropped `cursor.ts`, so a widget
upgrade that removes that file trips the existing guard when status is
intended-on.

## After a widget upgrade

A widget package upgrade rewrites
`~/.pi/agent/npm/node_modules/@marckrenn/pi-sub-*` and drops `cursor.ts`
plus the closed-union splices.

**Restore path: `chezmoi apply`** (or the same
`~/.local/user_scripts/apply_pi_patches.sh` loop it already invokes). That
re-drops the provider and re-splices the pi-loaded tree. Do not maintain a
forked widget repository, and do not hand-edit the installed sources.

## Scope / limitations

- One current-cycle spend window. No per-model Cursor breakdown.
- Does not call Cursor org Admin APIs or the team-spend roster, and does
  not store or require an org admin key.
- Does not auto-discover the included cap from a member-scoped Cursor API.
- Does not change Anthropic extra-usage fetching.
- Does not patch pi-coding-agent itself.
- Does not open an upstream Cursor-provider PR.

## Verify

```sh
PI_CHEZMOI_PROFILE=axon-work-computer node patch.mjs           # apply
PI_CHEZMOI_PROFILE=axon-work-computer node patch.mjs --check    # exit 0 when patched
# Off-profile --check expects unpatched and does not write:
PI_CHEZMOI_PROFILE=personal node patch.mjs --check
```

```sh
# Dropped provider and state (work profile, after apply)
grep -c 'chezmoi-pi-patch:cursor-provider' \
  ~/.pi/agent/npm/node_modules/@marckrenn/pi-sub-core/src/providers/impl/cursor.ts
cat ~/.local/state/chezmoi-pi-patches/cursor-provider.json
```

## Removal

Delete this directory and re-run `apply_pi_patches.sh` with a
non-`axon-work-computer` `PI_CHEZMOI_PROFILE` (restores splices and
removes dropped `cursor.ts`), or reinstall the pi-sub packages under
`~/.pi/agent/npm` and run `chezmoi apply`.
