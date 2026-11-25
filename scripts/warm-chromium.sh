#!/bin/sh
# Reads Chromium's binary and the data files beside it once, front to back, before any test starts it.
#
# On a fresh GitHub runner the disk is cold: the first read of a file comes from slow storage. Chromium maps its
# 530 MB binary and pages it in a few KB at a time, so its first start took 13 to 31 s on an idle runner and 57 s
# under scripts/ci-par.py's load, while the 60 s render limit of shx-note-image ran (dotfiles#702). A front-to-back
# read takes 8 to 11 s and leaves the later start at 1 to 3 s.
#
# Chromium is $SHX_CHROMIUM, else `chromium` on PATH, the same one the shx tests start. With none, this does nothing.
# Besides the binary it reads the files beside it named *.pak, *.dat, *.bin or *.so*. That covers an install that has its own
# directory, such as the runner's /usr/local/share/chromium/chrome-linux; where `chromium` is a small wrapper script, it reads
# only the script, which does no harm.
set -eu
bin=${SHX_CHROMIUM:-$(command -v chromium || true)}
[ -n "$bin" ] || exit 0
bin=$(readlink -f "$bin")
cat "$bin" >/dev/null
find "$(dirname "$bin")" -maxdepth 1 -type f \( -name '*.pak' -o -name '*.dat' -o -name '*.bin' -o -name '*.so*' \) -exec cat {} + >/dev/null
