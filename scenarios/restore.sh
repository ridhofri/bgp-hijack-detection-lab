#!/usr/bin/env bash
# Withdraw any injected hijack; return to clean baseline.
set -eu
docker exec clab-bgp-lab-attacker vtysh -c "conf t" -c "router bgp 65666" \
  -c "address-family ipv4 unicast" -c "no network 203.0.113.0/25" -c "end"
sleep 2
echo "### restored — transit FIB for 203.0.113.1 (should be victim 10.0.1.1)"
docker exec clab-bgp-lab-transit vtysh -c "show ip route 203.0.113.1" | grep -E "via|entry"
