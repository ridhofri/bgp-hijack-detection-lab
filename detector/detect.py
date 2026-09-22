#!/usr/bin/env python3
"""
BGP origin/path anomaly detector (intent-based, ARTEMIS-style).

Reads a running FRR node's BGP table as JSON and checks every path for a
protected prefix against a declared intent file. Emits alerts for:
  R1 wrong-origin      : origin AS != the prefix's legit origin
  R2 sub-prefix        : a route more specific than a protected prefix
  R3 invalid-adjacency : path claims the legit origin but the AS just before it
                         is not a declared neighbor of that origin (forged-origin;
                         RPKI marks this 'valid' and cannot catch it)

Usage: python3 detect.py --node clab-bgp-lab-transit --intent detector/intent.json
Exit code: 0 if no alerts, 1 if any alert (usable as a CI gate).
"""
import argparse, ipaddress, json, subprocess, sys


def load_intent(path):
    with open(path) as f:
        intent = json.load(f)
    protected = [{
        "net": ipaddress.ip_network(p["prefix"]),
        "prefix": p["prefix"],
        "legit_origin": int(p["legit_origin"]),
    } for p in intent["protected_prefixes"]]
    adj = set()
    for a, b in intent["legit_adjacencies"]:
        adj.add((int(a), int(b)))
        adj.add((int(b), int(a)))   # links are bidirectional
    return protected, adj


def fetch_bgp(node):
    out = subprocess.run(
        ["docker", "exec", node, "vtysh", "-c", "show ip bgp json"],
        capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def as_path_list(path):
    """Handle both JSON schemas: detailed (aspath.segments) and table (path string)."""
    a = path.get("aspath")
    if isinstance(a, dict) and a.get("segments"):
        seq = []
        for s in a["segments"]:
            seq.extend(int(x) for x in s.get("list", []))
        if seq:
            return seq
    s = None
    if isinstance(a, dict) and a.get("string") is not None:
        s = a["string"]
    elif isinstance(path.get("path"), str):
        s = path["path"]
    if s:
        return [int(t) for t in s.split() if t.isdigit()]
    return []


def peer_of(path):
    p = path.get("peer")
    if isinstance(p, dict):
        return p.get("hostname") or p.get("peerId") or "?"
    return path.get("peerId", "?")


def is_best(path):
    b = path.get("bestpath")
    return b.get("overall", False) if isinstance(b, dict) else bool(b)


def analyze(bgp, protected, adj):
    alerts = []
    routes = bgp.get("routes", bgp)
    for prefix_str, paths in routes.items():
        try:
            net = ipaddress.ip_network(prefix_str)
        except ValueError:
            continue
        if not isinstance(paths, list):
            continue
        for prot in protected:
            same = net == prot["net"]
            more_specific = net != prot["net"] and net.subnet_of(prot["net"])
            if not (same or more_specific):
                continue
            for path in paths:
                aspath = as_path_list(path)
                if not aspath:
                    continue
                origin = aspath[-1]
                before = aspath[-2] if len(aspath) >= 2 else None
                raw = path.get("rpkiValidationState")
                if raw is None:
                    rv = path.get("rpkiValid")
                    raw = "valid" if rv is True else ("invalid/notfound" if rv is False else "n/a")
                rpki = raw
                tag = (f"[{prot['prefix']}] {prefix_str} via {peer_of(path)} "
                       f"aspath={' '.join(map(str, aspath))} rpki={rpki} "
                       f"best={is_best(path)}")
                if more_specific:
                    alerts.append(("R2 sub-prefix",
                        f"more-specific of protected prefix. {tag}"))
                if origin != prot["legit_origin"]:
                    alerts.append(("R1 wrong-origin",
                        f"origin {origin} != legit {prot['legit_origin']}. {tag}"))
                elif before is not None and (before, origin) not in adj:
                    alerts.append(("R3 invalid-adjacency",
                        f"link ({before}->{origin}) is not a known adjacency "
                        f"[forged-origin; RPKI={rpki}]. {tag}"))
    return alerts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--node", default="clab-bgp-lab-transit")
    ap.add_argument("--intent", default="detector/intent.json")
    args = ap.parse_args()
    protected, adj = load_intent(args.intent)
    alerts = analyze(fetch_bgp(args.node), protected, adj)
    if not alerts:
        print(f"OK  no anomalies at {args.node} "
              f"({len(protected)} protected prefix(es) checked)")
        sys.exit(0)
    print(f"ALERT  {len(alerts)} anomaly(ies) at {args.node}:")
    for rule, msg in alerts:
        print(f"  [{rule}] {msg}")
    sys.exit(1)


if __name__ == "__main__":
    main()
