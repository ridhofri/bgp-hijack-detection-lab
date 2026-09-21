# RQ1 — Attack vs Defense Matrix

Legend: BLOCKED = attack neutralized | HIT = attack succeeds | (n/a) = not yet tested

| Attack \ Defense        | No defense | Prefix-list (in) | RPKI/ROV | Roles/OTC |
|-------------------------|------------|------------------|----------|-----------|
| Sub-prefix hijack (/25) | HIT (E2)   | BLOCKED (E3)     | (n/a)    | (n/a)     |
| Exact-prefix hijack     | (n/a)      | (n/a)            | (n/a)    | (n/a)     |
| Forged-origin hijack    | (n/a)      | (n/a)            | (n/a)    | (n/a)     |
| Route leak              | (n/a)      | (n/a)            | (n/a)    | (n/a)     |

## Evidence
- E2 (no defense): attacker AS65666 announced 203.0.113.0/25; transit FIB for 203.0.113.1
  flipped to attacker (10.0.3.2/eth3); user best-path became "65001 65666". Ping 0% loss
  (attacker answered) — availability intact, integrity broken.
- E3 (prefix-list in): identical attack; /25 rejected at transit ("% Network not in table");
  transit FIB stayed on victim (10.0.1.1/eth1); user best-path stayed "65001 65010".
  Legit prefix 192.0.2.0/24 still passed; BGP session stayed Established (rejecting a route
  does not drop the peering). Filter = whitelist 192.0.2.0/24 with implicit deny.
