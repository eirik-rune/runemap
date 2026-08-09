#!/bin/bash
while iptables -D OUTPUT -m cgroup --path system.slice/runemap-dev.service -j DROP 2>/dev/null; do :; done
while iptables -S OUTPUT | grep -q 'runemap-dev.service'; do
  R=$(iptables -S OUTPUT | grep 'runemap-dev.service' | head -1 | sed 's/^-A /-D /')
  iptables $R 2>/dev/null || break
done
while iptables -S OUTPUT | grep -q 'runemap-ctrl.service'; do
  R=$(iptables -S OUTPUT | grep 'runemap-ctrl.service' | head -1 | sed 's/^-A /-D /')
  iptables $R 2>/dev/null || break
done
echo "$(date -u +%H:%M:%S) unblocked; remaining=$(iptables -S OUTPUT | grep -c runemap)"
