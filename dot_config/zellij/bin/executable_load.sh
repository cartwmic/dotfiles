#!/bin/sh
# 1-minute load average as a short string (e.g. "1.42"). Used by zjstatus.
set -eu

case "$(uname -s)" in
  Darwin) sysctl -n vm.loadavg | awk '{printf "%s", $2}' ;;
  Linux)  awk '{printf "%s", $1}' /proc/loadavg ;;
  *)      printf "0.00" ;;
esac
