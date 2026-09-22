# Lab Notes

## 2026-09-21 — Session 1: Baseline topology (3 ASes)

**Topology:** victim (AS65010, originates 203.0.113.0/24) — transit (AS65001) — user (AS65020, originates 198.51.100.0/24)
**Environment:** see VERSIONS.md (FRR 10.7.1 pinned by digest, containerlab 0.79.0, Docker 28.5.2, Kali 2026.2)

### Deployment
- All 3 FRR nodes started successfully; config files are bind-mounted read-only.
- Repo files remain owned by UID/GID 1000 after deploy (containers did not modify them).
- containerlab working directory `clab-bgp-lab/` is owned by root (expected; gitignored).
- Resource usage: ~200 MiB for 3 routers (~65 MiB per router); available RAM 4.2 -> 4.0 GiB.
- Rough capacity estimate: ~35-40 routers with a 1.5 GiB safety margin (idle BGP only; re-check under route churn).

### Baseline — control plane
- All eBGP sessions Established; NOTIFICATION messages sent/received: 0/0.
- Transit: PfxRcd = 1 from each neighbor, PfxSnt = 2 to each neighbor.
- User RIB: `*> 203.0.113.0/24 via 10.0.2.1, AS_PATH "65001 65010" i` (origin AS = 65010).

### Baseline — data plane
- Ping user (src 198.51.100.1) -> victim (203.0.113.1): 0% loss, TTL 63 (= 1 router hop), RTT ~0.1 ms.
- TTL 63 is recorded as the hop-count baseline for later hijack comparison.

### Verified findings
- Loopback /24: assigning 203.0.113.1/24 on `lo` makes the entire /24 local (203.0.113.99 replies).
- AS_PATH loop detection: transit re-advertises 203.0.113.0/24 back to victim (PfxSnt = 2), but victim
  discards it (2 total paths, not 3) because its own ASN 65010 appears in the AS_PATH.
- Config-drift protection: `write memory` inside a router fails ("Resource busy" on rename +
  "Read-only file system"); repo configs unchanged -> read-only binds keep Git as the single source of truth.
- Reproducibility: destroy -> reboot -> redeploy reproduced the baseline exactly
  (PfxRcd 1/1, AS_PATH "65001 65010", TTL 63, 0% loss). Deploy works without sudo/sg after reboot.

### Experiment E1 — `bgp ebgp-requires-policy` on transit (RFC 8212 default-deny)
- Prediction: not recorded before execution (process gap -> write predictions BEFORE running from now on).
- Method: enable on transit via non-interactive vtysh, `clear bgp * soft`, wait 5 s, observe; then revert.
- Result (enabled):
  - Transit: PfxRcd and PfxSnt show `(Policy)` for both neighbors; RIB entries = 0; sessions stay Established.
  - User: 203.0.113.0/24 disappears from the RIB (only its own 198.51.100.0/24 remains).
  - Data plane: ping user -> victim 100% loss.
- Result (reverted): route returns and ping is back to 0% loss within <= 5 s (not measured precisely).
- Interpretation: default-deny blocks every eBGP route that lacks an explicit policy. This is strong
  protection against route leaks (e.g., the 2014 Indosat mis-origination spread through an unfiltered
  upstream), but it causes a full outage when policies are missing -> security vs availability trade-off.
- Implication for Phase 3: keep default-deny enabled and write explicit prefix-lists/route-maps
  instead of disabling it.

### Validity notes / limitations
- Lab RTT (~0.1 ms, single kernel) is unrealistic -> timing metrics (detection latency, convergence)
  will be optimistic; consider adding delay/jitter with `tc netem`.
- Current configs use `no bgp ebgp-requires-policy` as a temporary shortcut; to be replaced by
  explicit policies in Phase 3.

### Next
- Session 2: expand to 5 ASes (add attacker + second transit), run the first sub-prefix hijack,
  and compare AS_PATH/TTL against this baseline.

## 2026-09-21 — Session 2: First sub-prefix hijack (added attacker AS65666)
- Topology: added attacker off transit (transit:eth3 <-> attacker:eth1, 10.0.3.0/30).
  Attacker owns legit 192.0.2.0/24; pre-stages 203.0.113.1/25 on lo (announced on demand).
- Experiment E2 — sub-prefix hijack (attacker announces 203.0.113.0/25):
  - Prediction: not recorded (again) — MUST write predictions before running next time.
  - /24 and /25 coexist in user RIB; user matches /25 for 203.0.113.1 (longest-prefix-match),
    AS_PATH "65001 65666".
  - Transit FIB for 203.0.113.1 flips victim(10.0.1.1/eth1) -> attacker(10.0.3.2/eth3).
  - Scope proven: .1 (in /25) hijacked, .200 (out of /25) still to victim.
  - Victim itself loses its own /25 range (installs /25 via transit over connected /24).
  - Ping stayed 0% loss — attacker answered. Key lesson: availability != integrity;
    silent interception is worse than an outage.
  - TTL unchanged (63): equal hop counts, so TTL is NOT a usable hijack signal here.
    Detection relied on control-plane (foreign AS_PATH) + FIB, not hop count.
- Repro: scenarios/01-subprefix-hijack.sh (inject), scenarios/restore.sh (withdraw).

## 2026-09-21 — Session 3: Defense part 1 — prefix-list (E3)
- Prefix-list PL-ATTACKER-IN (permit 192.0.2.0/24 only) applied inbound on transit's
  neighbor 10.0.3.2 (attacker). Config-based (permanent), not runtime.
- A/B result: same sub-prefix attack -> BLOCKED. /25 never enters transit table;
  FIB stays on victim; legit /24 of attacker still passes; session stays Established.
- Note: "% Inbound soft reconfiguration not enabled" is expected — rejected routes are
  dropped by default (memory saving). Enable `soft-reconfiguration inbound` to audit them.
- First cell of RQ1 matrix filled: sub-prefix x prefix-list = BLOCKED. See RESULTS-matrix.md.

## 2026-09-22 — Session 4: RPKI/ROV (E4)
- New component: StayRTR (rpki/stayrtr v0.6.4) serving self-made ROA from rpki/roas.json,
  bound to :3323, run manually on the clab network (approach "B" — not yet a clab node).
- Isolation: prefix-list from E3 removed on transit so RPKI is the ONLY defense under test.
- Finding (label vs action): before any policy, the /25 was tagged rpki validation-state:
  invalid but stayed valid/external/best/installed -> hijack STILL succeeded (FIB -> attacker).
  RPKI validation only labels; it does not change route selection by itself.
- ROV enforcement: route-map RM-RPKI-IN (deny 10 match rpki invalid; permit 20) inbound on
  attacker peer. Result: /25 rejected ("% Network not in table"), FIB stays on victim,
  Valid+NotFound routes still pass (permit 20 proven necessary).
- RQ1 updated: sub-prefix x RPKI = BLOCKED (E4).
- Debt: rtr runs outside the topology; IP happened to stay 172.20.20.6 but this is fragile
  -> promote StayRTR to a clab node (approach "A") to make it reproducible.

## 2026-09-22 — Session 5: Forged-origin hijack bypasses RPKI/ROV (E5)
- Attack: attacker (AS65666) announces victim's exact 203.0.113.0/24 with forged AS_PATH
  "65666 65010" (route-map RM-FORGE-OUT: set as-path prepend 65010, applied outbound).
  Repro: scenarios/02-forged-origin.sh / restore-forged.sh.
- Predictions P1-P4 all correct: path "65666 65010", RPKI valid, ROV lets it pass,
  FIB initially stays on victim (forged path longer: 2 hops vs 1).
- Key insight #1: RPKI marks the forged route VALID because it only checks the ORIGIN
  (65010), which matches the ROA. Path authenticity is never verified.
- Key insight #2 (the payoff): with local-preference 200 on the forged route (simulating an
  AS topologically closer to the attacker), it wins best-path and FIB -> attacker (10.0.3.2)
  WHILE the ROV route-map is still active. ROV only rejects Invalid; this route is Valid.
- Conclusion: RPKI/ROV does not stop forged-origin hijacks. Mitigations that would: BGPsec
  (signs the whole AS_PATH) and ASPA (validates AS adjacencies). => matrix E5.
- Real-world tie-in: this is why partial-impact hijacks (e.g., Indosat 2014) affect only the
  ASes for whom the bogus path looks better.

## 2026-09-22 — Session 6: Intent-based anomaly detector (E6)
- detector/detect.py + detector/intent.json read FRR "show ip bgp json" (post-policy Loc-RIB)
  and check each path vs intent. Rules: R1 wrong-origin, R2 sub-prefix,
  R3 invalid-adjacency (ASPA-style: AS before the origin must be a declared neighbor).
- WIN: R3 catches the forged-origin route (65666 65010) that RPKI marks valid and ROV lets
  through -> detection succeeds exactly where cryptographic prevention fails. Fires even when
  the forged route is not yet best (early warning): "RPKI=valid" but flagged as anomaly.
- Negative control passes: clean baseline => 0 alerts.
- Post-policy blind spot: with ROV active the /25 is rejected at ingress (route-map deny
  seq10 Invoked=3, "% Network not in table"), so a Loc-RIB detector sees nothing. Disabling
  ROV, the identical attack immediately triggers R2+R1. => a post-policy detector cannot see
  attacks a defense already blocked; pre-policy (Adj-RIB-In via soft-reconfiguration or BMP)
  is needed to log attempted-but-blocked attacks.
- Schema note: table view uses "path" (string) + "rpkiValid" (boolean); detail view uses
  "aspath.segments" + "rpkiValidationState" (valid/invalid/notfound). Parser handles both;
  boolean true is rendered "valid".

## 2026-09-22 — Session 6: Intent-based anomaly detector (E6)
- detector/detect.py + detector/intent.json read FRR "show ip bgp json" (post-policy Loc-RIB)
  and check each path vs intent. Rules: R1 wrong-origin, R2 sub-prefix,
  R3 invalid-adjacency (ASPA-style: AS before the origin must be a declared neighbor).
- WIN: R3 catches the forged-origin route (65666 65010) that RPKI marks valid and ROV lets
  through -> detection succeeds exactly where cryptographic prevention fails. Fires even when
  the forged route is not yet best (early warning): "RPKI=valid" but flagged as anomaly.
- Negative control passes: clean baseline => 0 alerts.
- Post-policy blind spot: with ROV active the /25 is rejected at ingress (route-map deny
  seq10 Invoked=3, "% Network not in table"), so a Loc-RIB detector sees nothing. Disabling
  ROV, the identical attack immediately triggers R2+R1. => a post-policy detector cannot see
  attacks a defense already blocked; pre-policy (Adj-RIB-In via soft-reconfiguration or BMP)
  is needed to log attempted-but-blocked attacks.
- Schema note: table view uses "path" (string) + "rpkiValid" (boolean); detail view uses
  "aspath.segments" + "rpkiValidationState" (valid/invalid/notfound). Parser handles both;
  boolean true is rendered "valid".

## 2026-09-22 — Session 7: BMP-fed detector v2 (E7)
- Infra debt paid: StayRTR and goBMP are containerlab nodes with pinned mgmt IPs
  (.200 and .201); transit RPKI cache moved to .200. One deploy brings up all 6 nodes.
  StayRTR and goBMP image digests recorded in VERSIONS.md.
- Transit: bgpd -M rpki -M bmp; bmp targets COLLECTOR -> 172.20.20.201:5000, monitoring
  ipv4 unicast pre-policy + post-policy; soft-reconfiguration inbound on the attacker peer.
  "show bmp": session Up.
- goBMP schema: is_adj_rib_in_post_policy false = pre-policy, true = post-policy;
  'del' messages carry no as_path.
- H1 confirmed: under ROV, the sub-prefix /25 appears as a pre-policy 'add' and a
  post-policy 'del' -> a blocked attempt is now visible.
- Detector v2 (detect_bmp.py), "ever-seen" model keyed by (prefix, peer, as_path):
  ACTIVE if ever added post-policy, BLOCKED if only seen pre-policy.
  Result: forged-origin /24 = ACTIVE (R3); sub-prefix /25 = BLOCKED (R1+R2).
  Negative control (fresh BMP session, no attack) = OK.
  Propagation echo (65666 65001 65010) correctly NOT flagged.
- Debugging lessons (three failed designs before the working one):
  1) evaluating on every message -> duplicate alerts and false "origin -1" alerts from 'del';
  2) evaluating only the final state (level-triggered) erased the withdrawn forged-origin attack;
  3) keying by (prefix, peer) let the forged path collide with a propagation echo from the
     same peer; BMP's initial dump replays old timestamps, so time-ordered episodes were fragile.
  Also: docker restart does not clear docker logs -> read with --since.
- Limitations: batch over logs (not live alerts); ACTIVE = passed policy, not best-path
  (needs loc-rib monitoring); the ever-seen model records no end time.

## 2026-09-22 — Session 7b: Prefix-list vs forged-origin (E8) — matrix correction
- Why: the RQ1 matrix listed prefix-list vs forged-origin as "HIT (origin only)" without a test.
- Method: runtime prefix-list PL-ATTACKER-IN (permit 192.0.2.0/24) inbound on the attacker
  peer, together with ROV; ran scenarios/02-forged-origin.sh; then removed it (config files
  unchanged).
- Result: received-routes showed the forged 203.0.113.0/24 (65666 65010), "3 prefixes
  (2 filtered)"; post-filter routes = 192.0.2.0/24 only; transit kept one path (victim) and
  the FIB stayed on 10.0.1.1 -> BLOCKED.
- Attribution: ROV alone lets this Valid route through (E5), so the prefix-list did the blocking.
- Lesson: prefix filters check the prefix, not the path, so they stop forged-origin at the
  first hop. They fail once the forged route arrives via a provider/peer that legitimately
  carries the prefix. And: an untested cell in a results matrix is a claim, not a result.
- Detector v2 ("ever-seen" model) negative control re-run on a fresh BMP session: OK.

## 2026-09-22 — Session 8: Loc-RIB monitoring, detector v3 (E9)
- Added "bmp monitor ipv4 unicast loc-rib" on transit (now pre + post + loc-rib).
- goBMP loc-rib schema: is_loc_rib=true, and a SYNTHETIC peer (peer_asn = local AS 65001,
  peer_ip 0.0.0.0, peer_type 3, per RFC 9069) — NOT the route's real origin peer.
  => detector v3 matches routes across views by (prefix, as_path), not by peer.
- Three severity classes: BLOCKED (only pre-policy), ACTIVE (post-policy but not loc-rib),
  WINNING (in loc-rib = actually selected / traffic diverted).
- Results (same forged-origin attack, only local-pref changed):
  - baseline loc-rib for 203.0.113.0/24 = aspath [65010] (victim wins) -> H1 confirmed.
  - forged-origin, no local-pref: post-policy yes, loc-rib no -> ACTIVE (H2 confirmed).
  - forged-origin, local-pref 200: enters loc-rib -> WINNING (H3 confirmed).
  - negative control (fresh BMP session) = OK.
- Meaning: the detector now distinguishes "passed policy" from "won best-path / traffic
  actually hijacked" — the limitation noted at the end of Session 7 is resolved.
