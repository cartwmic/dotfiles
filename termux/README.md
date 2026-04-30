# Termux

Canonical source for Termux configuration on the Android phone.

Chezmoi cannot deploy these files directly (the destination lives on the phone,
not this machine), so the workflow is **edit-here, push-via-adb**.

## Files

- `termux.properties` — extra-keys home row (long-press popups bound to zellij
  shortcuts: `CTRL T` → room, `CTRL Y` → harpoon, etc.).
- `font.ttf` — terminal font. Currently **FiraCode Nerd Font Regular v3.4.0**
  (provides Nerd Font glyphs for the extra-keys row and the prompt). Replace
  this file with another `.ttf` to switch fonts, then re-run `sync.sh`.

## Sync to device

Phone must be reachable over ADB (`adb devices` shows it).

```bash
./termux/sync.sh
```

Or manually:

```bash
adb push termux/termux.properties /data/local/tmp/termux.properties.new
adb shell 'run-as com.termux cp /data/local/tmp/termux.properties.new \
    files/home/.termux/termux.properties && \
    rm /data/local/tmp/termux.properties.new'
adb shell 'am broadcast --user 0 -a com.termux.app.reload_style com.termux'
```

## Pull from device (when editing on phone)

```bash
adb shell 'run-as com.termux cat files/home/.termux/termux.properties' \
    > termux/termux.properties
adb shell 'run-as com.termux cat files/home/.termux/font.ttf' \
    > termux/font.ttf
```
