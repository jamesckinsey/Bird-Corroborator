#!/bin/sh
set -u
echo "=== OS and hardware ==="
uname -m
cat /etc/os-release
tr -d '\000' </proc/device-tree/model 2>/dev/null || true
echo
echo "=== Load, memory, disk, failures ==="
uptime
free -h
df -h
systemctl --failed --no-pager
echo "=== Raspberry Pi thermal state (when available) ==="
vcgencmd measure_temp 2>/dev/null || true
vcgencmd get_throttled 2>/dev/null || true
