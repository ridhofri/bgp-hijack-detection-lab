#!/usr/bin/env bash
# Withdraw the forged-origin hijack and clean up attacker config.
set -eu
docker exec clab-bgp-lab-attacker vtysh -c "conf t" \
  -c "router bgp 65666" -c "address-family ipv4 unicast" \
  -c "no network 203.0.113.0/24" \
  -c "no neighbor 10.0.3.1 route-map RM-FORGE-OUT out" -c "exit" -c "exit" \
  -c "no route-map RM-FORGE-OUT" \
  -c "no ip prefix-list PL-FORGE" \
  -c "interface lo" -c "no ip address 203.0.113.254/24" -c "end"
sleep 2
echo "### restored — transit FIB for 203.0.113.1 (should be victim 10.0.1.1)"
docker exec clab-bgp-lab-transit vtysh -c "show ip route 203.0.113.1" | grep -E "via|entry"
