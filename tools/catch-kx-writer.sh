#!/usr/bin/env bash
# Catch whatever opens ~/kinox/kx for WRITING — the cause of the ETXTBSY
# ("Text file busy") errors. Must run as root:
#
#     sudo /home/enigma/kinox/tools/catch-kx-writer.sh           # until Ctrl-C
#     sudo /home/enigma/kinox/tools/catch-kx-writer.sh 120       # 120 seconds
#
# Writes findings to tools/kx-writer.log. Two independent detectors run at once:
#   1) bpftrace on openat/open syscalls  -> catches even momentary write-opens,
#                                            reports comm + pid + uid
#   2) a 50ms fuser poll                 -> backup, matches the file by any name
# At start it also invokes `kx doctor` a few times as the real user, in case the
# writer fires on kx startup (e.g. an rtk --auto-patch hook).
set -u
TARGET=/home/enigma/kinox/kx
LOG=/home/enigma/kinox/tools/kx-writer.log
DUR="${1:-0}"   # 0 = run until Ctrl-C

if [ "$(id -u)" -ne 0 ]; then
  echo "Must run as root:  sudo $0 [seconds]" >&2
  exit 1
fi

echo "==== catcher START $(date '+%F %T.%N') watching $TARGET ====" | tee -a "$LOG"

# 1) bpftrace: any write-mode open (O_WRONLY/O_RDWR) of a path that names kx
bpftrace -e '
tracepoint:syscalls:sys_enter_openat,
tracepoint:syscalls:sys_enter_open
{
  $fn = str(args.filename);
  if ((args.flags & 3) != 0 &&
      ($fn == "/home/enigma/kinox/kx" || $fn == "kx" || $fn == "./kx" ||
       $fn == "/home/enigma/.local/bin/kx")) {
    time("%H:%M:%S ");
    printf("WRITE-OPEN comm=%s pid=%d uid=%d flags=0x%x path=%s\n",
           comm, pid, uid, args.flags, $fn);
  }
}' >> "$LOG" 2>&1 &
BPF=$!

# 2) fuser poll backup
( while :; do
    h=$(fuser "$TARGET" 2>/dev/null)
    if [ -n "$h" ]; then
      printf -- '--- %s fuser holders:%s ---\n' "$(date '+%T.%N')" "$h" >> "$LOG"
      fuser -v "$TARGET" >> "$LOG" 2>&1
      for tok in $h; do
        pid=$(printf '%s' "$tok" | tr -cd '0-9'); [ -z "$pid" ] && continue
        printf '    pid=%s exe=%s\n      cmd: %s\n' \
          "$pid" "$(readlink -f /proc/$pid/exe 2>/dev/null)" \
          "$(tr '\0' ' ' < /proc/$pid/cmdline 2>/dev/null)" >> "$LOG"
      done
    fi
    sleep 0.05
  done ) &
POLL=$!

cleanup() { kill "$BPF" "$POLL" 2>/dev/null; echo "==== catcher STOP $(date '+%F %T') -> $LOG ====" | tee -a "$LOG"; }
trap cleanup EXIT INT TERM

# 3) provoke: run kx as the real user, in case the writer fires on kx startup
echo "-- provoking with 5x 'kx doctor' as enigma --" >> "$LOG"
for i in 1 2 3 4 5; do
  sudo -u enigma -H /home/enigma/.local/bin/kx doctor >/dev/null 2>&1
  sleep 1
done

if [ "$DUR" -gt 0 ] 2>/dev/null; then sleep "$DUR"; else
  echo "-- running until Ctrl-C; trigger the auto-patch / rtk init now --" | tee -a "$LOG"
  while :; do sleep 3600; done
fi
