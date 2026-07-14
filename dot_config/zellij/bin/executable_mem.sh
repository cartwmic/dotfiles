#!/bin/sh
# Memory usage as integer percent (0-100). Used by zjstatus.
# Cross-platform (macOS / Linux). Single line, no trailing newline.
set -eu

case "$(uname -s)" in
  Darwin)
    /usr/bin/vm_stat | awk '
      /page size of/      { ps    = $8  + 0 }
      /Pages free:/       { free  = $3 + 0 }
      /Pages active:/     { act   = $3 + 0 }
      /Pages inactive:/   { inact = $3 + 0 }
      /Pages speculative:/{ spec  = $3 + 0 }
      /Pages wired down:/ { wired = $4 + 0 }
      /Pages occupied by compressor:/ { comp = $5 + 0 }
      END {
        used  = (act + wired + comp) * ps
        total = (free + act + inact + spec + wired + comp) * ps
        if (total > 0) printf "%d", used * 100 / total
        else printf "0"
      }'
    ;;
  Linux)
    awk '/^MemTotal:/{t=$2} /^MemAvailable:/{a=$2} END {
      if (t>0) printf "%d", (t-a)*100/t; else printf "0"
    }' /proc/meminfo
    ;;
  *)
    printf "0"
    ;;
esac
