#!/bin/sh
set -eu
task_rules=$(mktemp /run/pxe-firewall.XXXXXX)
trap 'rm -f "$task_rules"' EXIT HUP INT TERM
for task_table in 'inet pxe_filter' 'ip pxe_nat'; do
    if nft list table $task_table >/dev/null 2>&1; then
        printf 'delete table %s\n' "$task_table" >> "$task_rules"
    fi
done
cat /etc/pxe/firewall.nft >> "$task_rules"
nft --check --file "$task_rules"
nft --file "$task_rules"
logger -t pxe-firewall 'Applied PXE-owned filter/NAT tables; other tables preserved'
