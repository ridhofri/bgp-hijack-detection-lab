# RQ1 — Attack vs Defense vs Detection Matrix

Legend: **HIT** = attack succeeds (route accepted / traffic redirected) · **BLOCKED** = a defense neutralized it · detector columns show what the detector reports · **(n/a)** = not yet tested.

| Attack | No defense | Prefix-list (in) | RPKI / ROV | Roles/OTC | Detector v1 (Loc-RIB poll) | Detector v2 (BMP) |
|---|---|---|---|---|---|---|
| Sub-prefix hijack (/25) | HIT (E2) | BLOCKED (E3) | BLOCKED (E4) | (n/a) | not visible once blocked (E6) | BLOCKED: R1+R2 (E7) |
| Forged-origin hijack (/24) | HIT (E5) | BLOCKED, first hop only (E8) | HIT: bypass (E5) | (n/a) | CAUGHT: R3 (E6) | ACTIVE: R3 (E7) |
| Exact-prefix hijack | (n/a) | (n/a) | (n/a) | (n/a) | (n/a) | (n/a) |
| Route leak | (n/a) | (n/a) | (n/a) | (n/a) | (n/a) | (n/a) |

> **Correction (E8).** An earlier revision of this matrix listed prefix-list vs forged-origin as HIT. That cell was never tested. E8 tested it: the prefix-list rejects the forged /24 at the first hop. The cell has been corrected.

## Evidence

- **E2 (no defense).** Attacker AS65666 announced 203.0.113.0/25. The transit FIB for 203.0.113.1 flipped to the attacker (10.0.3.2/eth3) and the user's best path became "65001 65666". Ping stayed at 0% loss because the attacker answered: availability intact, integrity broken.

- **E3 (prefix-list in).** Identical attack. The /25 was rejected at the transit ("% Network not in table"), the FIB stayed on the victim (10.0.1.1/eth1), and the user's best path stayed "65001 65010". The attacker's legitimate 192.0.2.0/24 still passed and the BGP session stayed Established: rejecting a route does not drop the peering. Filter = whitelist of 192.0.2.0/24 with implicit deny.

- **E4 (RPKI/ROV).** StayRTR serves a self-made ROA (203.0.113.0/24, maxLength 24, AS65010); the transit connects over RTR. The /25 from AS65666 is marked Invalid (it exceeds maxLength). Before any policy, the Invalid route still stayed best and installed and the hijack succeeded. With route-map "deny match rpki invalid" inbound, it is rejected, the FIB stays on the victim, and Valid and NotFound routes still pass. RPKI labels; the route-map enforces.

- **E5 (forged-origin vs RPKI/ROV).** The attacker announces the victim's exact /24 with a forged AS_PATH "65666 65010" (route-map set as-path prepend 65010, outbound). RPKI reads origin 65010, matches the ROA, and marks it VALID, so the ROV route-map does not reject it. Without extra preference it loses best-path to the shorter real path; with local-preference 200 (standing in for topological closeness) it wins and the transit FIB moves to the attacker while ROV is fully active. RPKI validates the origin, not the path.

- **E6 (detector v1, polling).** Intent rules R1 wrong-origin, R2 sub-prefix, R3 invalid-adjacency over "show ip bgp json". R3 flags the forged route: link 65666 -> 65010 is not a known adjacency, while RPKI says valid, even before the route wins best-path. Negative control: clean baseline = 0 alerts. Blind spot: with ROV active, the /25 is rejected at ingress (route-map deny seq 10 hit counter > 0) and never reaches the post-policy table, so v1 sees nothing; with ROV disabled, the identical attack triggers R2 + R1.

- **E7 (detector v2, BMP).** The transit sends BMP pre-policy and post-policy views to goBMP (is_adj_rib_in_post_policy false = pre, true = post). The ROV-blocked /25 shows up as a pre-policy add and a post-policy del. v2 keys routes by (prefix, peer, AS_PATH) and marks each ACTIVE if it was ever added post-policy, BLOCKED if it was only seen pre-policy. Result: forged-origin /24 = ACTIVE (R3); sub-prefix /25 = BLOCKED (R1 + R2). The propagation echo (65666 65001 65010) is correctly not flagged. Negative control on a fresh BMP session = OK.

- **E8 (prefix-list vs forged-origin).** Runtime prefix-list PL-ATTACKER-IN (permit 192.0.2.0/24) inbound on the attacker peer, together with ROV. received-routes shows the forged 203.0.113.0/24 (65666 65010) arriving, "3 prefixes (2 filtered)"; the post-filter view keeps only 192.0.2.0/24; the transit keeps a single path (victim) and the FIB stays on 10.0.1.1. ROV alone passes this Valid route (E5), so the prefix-list did the blocking. Caveat: this only works at the first hop, where the provider knows exactly which prefixes the customer may announce.
