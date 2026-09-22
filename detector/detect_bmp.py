#!/usr/bin/env python3
"""
BMP-fed BGP anomaly detector (v2) - "ever-seen" model.

Reads goBMP JSON (one message per line) from stdin. For each UNIQUE route
(prefix, peer_asn, as_path) it records whether the route was ever seen in the
pre-policy Adj-RIB-In and/or added to the post-policy Adj-RIB-In. Then it
applies the intent rules (R1/R2/R3) once per unique route and classifies:

  ACTIVE  : route was 'add'ed post-policy at some point  (passed the filters)
  BLOCKED : route only ever seen pre-policy               (a defense removed it)

Including as_path in the key keeps distinct paths (e.g. a forged path vs a
propagation echo) from colliding. The model is monotonic (ever-seen flags only
go from False to True), so it is robust to message order and to the initial
table dump that BMP replays with old timestamps.

Note: ACTIVE means "passed policy", not necessarily "won best-path".

goBMP/OpenBMP: is_adj_rib_in_post_policy False->pre, True->post; action add/del.

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
    seen = {}   # (prefix, peer_asn, aspath_tuple) -> {"pre":bool,"post":bool}

    for line in sys.stdin:
        if '"prefix"' not in line:
            continue
        try:
            d = json.loads(line).get("msg_data", {})
        except json.JSONDecodeError:
            continue
        if not d.get("is_ipv4") or "prefix" not in d or d.get("action") != "add":
            continue   # only 'add' carries a path and proves presence
        try:
            net = ipaddress.ip_network(f"{d['prefix']}/{d['prefix_len']}")
        except (ValueError, KeyError):
            continue
        if not touches_protected(net, protected):
            continue
        aspath = tuple(int(a) for a in d.get("base_attrs", {}).get("as_path", []))
        if not aspath:
            continue
        key = (str(net), d.get("peer_asn"), aspath)
        rec = seen.setdefault(key, {"pre": False, "post": False})
        if d.get("is_adj_rib_in_post_policy"):
            rec["post"] = True
        else:
            rec["pre"] = True

    n = 0
    for (prefix, peer, aspath), rec in sorted(seen.items()):
        hits = rule_hits(ipaddress.ip_network(prefix), list(aspath), protected, adj)
        if not hits:
            continue
        cls = "ACTIVE " if rec["post"] else "BLOCKED"
        rules = "; ".join(f"{r}: {why}" for r, why in hits)
        print(f"[{cls}] {prefix} from AS{peer} "
              f"aspath={' '.join(map(str, aspath))} :: {rules}")
        n += 1
    if n == 0:
        print("OK  no anomalies in stream")


if __name__ == "__main__":
    main()
