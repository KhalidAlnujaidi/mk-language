#!/usr/bin/env bash
# One-shot monitor: log the FIRST process that opens ~enigma/kinox/kx for
# writing, capture its context, then disable itself. Runs as a root systemd
# service (bpftrace needs root). Not a forever task — stops after one catch.
set -u
LOG=/home/enigma/kinox/tools/kx-writer.log
echo "==== one-shot daemon START $(date "+%F %T") — stops after first catch ====" >> "$LOG"
bpftrace -e '
tracepoint:syscalls:sys_enter_openat,
tracepoint:syscalls:sys_enter_open
{
  $fn = str(args.filename);
  if ((args.flags & 3) != 0 &&
      ($fn == "/home/enigma/kinox/kx" || $fn == "kx" || $fn == "./kx" ||
       $fn == "/home/enigma/.local/bin/kx")) {
    time("%Y-%m-%d %H:%M:%S ");
    printf("WRITE-OPEN comm=%s pid=%d uid=%d flags=0x%x path=%s\n",
           comm, pid, uid, args.flags, $fn);
  }
}' 2>>"$LOG" | while IFS= read -r line; do
  printf "%s\n" "$line" >> "$LOG"
  case "$line" in
    *WRITE-OPEN*)
      echo "==== CAUGHT $(date "+%F %T") — capturing context, self-disabling ====" >> "$LOG"
      pid=$(printf "%s" "$line" | sed -n "s/.*pid=\([0-9]*\).*/\1/p")
      if [ -n "$pid" ]; then
        echo "  exe : $(readlink -f /proc/$pid/exe 2>/dev/null)" >> "$LOG"
        echo "  cmd : $(tr "\0" " " < /proc/$pid/cmdline 2>/dev/null)" >> "$LOG"
        ppid=$(awk "/^PPid:/{print \$2}" /proc/$pid/status 2>/dev/null)
        echo "  ppid: ${ppid} ($(tr "\0" " " < /proc/${ppid}/cmdline 2>/dev/null))" >> "$LOG"
      fi
      systemctl disable kx-writer-catch.service >/dev/null 2>&1 || true
      echo "==== disabled; will not restart at boot. Findings above. ====" >> "$LOG"
      exit 0
      ;;
  esac
done
