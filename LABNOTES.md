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
