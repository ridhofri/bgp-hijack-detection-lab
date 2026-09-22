#!/usr/bin/env python3
"""
BMP-fed BGP anomaly detector (v3) - "ever-seen" model over three RIB views.

Reads goBMP JSON (one message per line) from stdin. For each unique route it
records whether it was ever seen pre-policy, post-policy, and in the Loc-RIB,
then applies intent rules (R1/R2/R3) once and classifies by severity:

  BLOCKED : only ever seen pre-policy            (a filter removed it)
  ACTIVE  : reached post-policy but not Loc-RIB   (passed filters, lost best-path)
  WINNING : present in the Loc-RIB                (won best-path; traffic is actually diverted)

Adj-RIB-In messages carry the real peer (e.g. 65666). Loc-RIB messages use a
synthetic peer (peer_asn = local AS, peer_ip 0.0.0.0, peer_type 3, RFC 9069),
so routes are matched across views by (prefix, as_path), NOT by peer.

goBMP flags: is_adj_rib_in_post_policy (false=pre, true=post), is_loc_rib.
action add = present, del = withdrawn (del has no as_path).

Usage: docker logs --since <ts> clab-bgp-lab-gobmp 2>&1 | python3 detector/detect_bmp.py
"""
import ipaddress, json, sys


def load_intent(path="detector/intent.json"):
    intent = json.load(open(path))
    protected = [{
        "net": ipaddress.ip_network(p["prefix"]),
        "prefix": p["prefix"],
        "legit_origin": int(p["legit_origin"]),
    } for p in intent["protected_prefixes"]]
    adj = set()
    for a, b in intent["legit_adjacencies"]:
        adj.add((int(a), int(b)))
        adj.add((int(b), int(a)))
    return protected, adj


def touches_protected(net, protected):
    return any(net == p["net"] or net.subnet_of(p["net"]) for p in protected)


def rule_hits(net, aspath, protected, adj):
    if not aspath:
        return []
    origin = aspath[-1]
    before = aspath[-2] if len(aspath) >= 2 else None
    hits = []
    for prot in protected:
        same = net == prot["net"]
        more_specific = net != prot["net"] and net.subnet_of(prot["net"])
        if not (same or more_specific):
            continue
        if more_specific:
            hits.append(("R2 sub-prefix", f"more-specific of {prot['prefix']}"))
        if origin != prot["legit_origin"]:
            hits.append(("R1 wrong-origin",
                         f"origin {origin} != legit {prot['legit_origin']}"))
        elif before is not None and (before, origin) not in adj:
            hits.append(("R3 invalid-adjacency",
                         f"link ({before}->{origin}) not a known adjacency"))
    return hits


def main():
    protected, adj = load_intent()
    # keyed by (prefix, as_path) so views match across pre/post/loc-rib
    seen = {}

    for line in sys.stdin:
        if '"prefix"' not in line:
            continue
        try:
            d = json.loads(line).get("msg_data", {})
        except json.JSONDecodeError:
            continue
        if not d.get("is_ipv4") or "prefix" not in d or d.get("action") != "add":
            continue
        try:
            net = ipaddress.ip_network(f"{d['prefix']}/{d['prefix_len']}")
        except (ValueError, KeyError):
            continue
        if not touches_protected(net, protected):
            continue
        aspath = tuple(int(a) for a in d.get("base_attrs", {}).get("as_path", []))
        if not aspath:
            continue
        key = (str(net), aspath)
        rec = seen.setdefault(key, {"pre": False, "post": False, "loc": False,
                                    "peers": set()})
        if d.get("is_loc_rib"):
            rec["loc"] = True
        elif d.get("is_adj_rib_in_post_policy"):
            rec["post"] = True
            rec["peers"].add(d.get("peer_asn"))
        else:
            rec["pre"] = True
            rec["peers"].add(d.get("peer_asn"))

    n = 0
    for (prefix, aspath), rec in sorted(seen.items()):
        hits = rule_hits(ipaddress.ip_network(prefix), list(aspath), protected, adj)
        if not hits:
            continue
        if rec["loc"]:
            cls = "WINNING"
        elif rec["post"]:
            cls = "ACTIVE "
        elif rec["pre"]:
            cls = "BLOCKED"
        else:
            continue
        peers = ",".join(f"AS{p}" for p in sorted(x for x in rec["peers"] if x is not None)) or "loc-rib"
        rules = "; ".join(f"{r}: {why}" for r, why in hits)
        print(f"[{cls}] {prefix} via {peers} "
              f"aspath={' '.join(map(str, aspath))} :: {rules}")
        n += 1
    if n == 0:
        print("OK  no anomalies in stream")


if __name__ == "__main__":
    main()
