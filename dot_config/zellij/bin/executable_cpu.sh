#!/bin/sh
# CPU usage as integer percent (0-100), system-wide. Used by zjstatus.
# Cross-platform (macOS / Linux). Single line, no trailing newline.
set -eu

case "$(uname -s)" in
  Darwin)
    cores=$(sysctl -n hw.ncpu)
    # ps %cpu sums to up to cores*100 across all processes; divide to get %.
    ps -A -o %cpu= | awk -v c="$cores" '{s+=$1} END {printf "%d", s/c}'
    ;;
  Linux)
    a=$(awk '/^cpu / {print $2,$3,$4,$5,$6,$7,$8,$9}' /proc/stat)
    sleep 1
    b=$(awk '/^cpu / {print $2,$3,$4,$5,$6,$7,$8,$9}' /proc/stat)
    awk -v a="$a" -v b="$b" 'BEGIN {
      n=split(a,p," "); split(b,q," ")
      t1=0; t2=0; for(i=1;i<=n;i++){t1+=p[i]; t2+=q[i]}
      d=t2-t1; di=q[4]-p[4]
      if (d>0) printf "%d", (d-di)*100/d; else printf "0"
    }'
    ;;
  *)
    printf "0"
    ;;
esac
