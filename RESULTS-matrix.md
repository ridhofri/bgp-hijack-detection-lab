# RQ1 — Attack vs Defense Matrix

Legend: BLOCKED = attack neutralized | HIT = attack succeeds | (n/a) = not yet tested

| Attack \ Defense        | No defense | Prefix-list (in) | RPKI/ROV | Roles/OTC |
|-------------------------|------------|------------------|----------|-----------|
| Sub-prefix hijack (/25) | HIT (E2)   | BLOCKED (E3)     | BLOCKED (E4) | (n/a)     |
| Exact-prefix hijack     | (n/a)      | (n/a)            | (n/a)    | (n/a)     |
| Forged-origin hijack    | HIT        | HIT (origin only) | HIT (bypass) | (n/a)     |
| Route leak              | (n/a)      | (n/a)            | (n/a)    | (n/a)     |

## Evidence
- E2 (no defense): attacker AS65666 announced 203.0.113.0/25; transit FIB for 203.0.113.1
  flipped to attacker (10.0.3.2/eth3); user best-path became "65001 65666". Ping 0% loss
  (attacker answered) — availability intact, integrity broken.
- E3 (prefix-list in): identical attack; /25 rejected at transit ("% Network not in table");
  transit FIB stayed on victim (10.0.1.1/eth1); user best-path stayed "65001 65010".
  Legit prefix 192.0.2.0/24 still passed; BGP session stayed Established (rejecting a route
  does not drop the peering). Filter = whitelist 192.0.2.0/24 with implicit deny.

- E4 (RPKI/ROV): StayRTR serves a self-made ROA (203.0.113.0/24, maxLength 24, AS65010).
  Transit connects via RTR (rpki cache tcp) and applies route-map "deny match rpki invalid".
  Sub-prefix /25 from AS65666 is marked Invalid (exceeds maxLength) and rejected inbound;
  transit FIB stays on victim. Valid (/24) and NotFound routes still pass.
  KEY: RPKI without policy only *labels* Invalid — the /25 stayed best & installed and the
  hijack still succeeded. The route-map is what turns the label into enforcement.

- E5 (forged-origin vs RPKI/ROV): attacker announces the victim's exact /24 with a forged
  AS_PATH "65666 65010" (via route-map set as-path prepend 65010 outbound). Transit's RPKI
  reads the origin (65010), matches the ROA, and marks the route VALID. The ROV route-map
  (deny match rpki invalid) therefore does NOT reject it. With the forged route made more
  attractive (local-preference 200 — standing in for topological closeness), it wins
  best-path and the transit FIB moves to the attacker (10.0.3.2). Hijack succeeds with ROV
  fully active. KEY: RPKI validates the ORIGIN, not the PATH — forged-origin bypasses it.
  This is the gap that BGPsec (path signing) and ASPA (AS-relationship validation) address.
