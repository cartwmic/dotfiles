#!/usr/bin/env python3
"""Read-only capability-tier resolver. Prints which model@effort each slot would get.

Reads the registry (tiers.toml) and a quota snapshot (the pi-sub cache or a fixture). Makes no model call,
writes nothing, and is wired into no harness. Exit 0: every slot resolved. 1: usage or registry error.
2: at least one slot has no available candidate (fail closed).
"""
import argparse
import hashlib
import json
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

EFFORTS = ("off", "minimal", "low", "medium", "high", "xhigh", "max")
HERE = Path(__file__).resolve().parent
DEFAULT_REGISTRY = HERE / "tiers.toml"
DEFAULT_QUOTA = Path.home() / ".pi" / "agent" / "cache" / "sub-core" / "cache.json"


class Fail(Exception):
    pass


def parse_candidate(text):
    spec, _, effort = text.rpartition("@")
    if not spec or effort not in EFFORTS or "/" not in spec:
        raise Fail(f"bad candidate {text!r}: expected provider/model@effort with effort in {', '.join(EFFORTS)}")
    provider, _, model = spec.partition("/")
    return {"id": text, "provider": provider, "model": f"{provider}/{model}", "effort": effort}


def load_registry(path):
    raw = Path(path).read_bytes()
    try:
        reg = tomllib.loads(raw.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise Fail(f"registry {path}: {exc}")
    tiers = reg.get("tiers") or {}
    providers = reg.get("providers") or {}
    if not tiers:
        raise Fail("registry has no [tiers]")
    for name, tier in tiers.items():
        cands = tier.get("candidates") or []
        if not cands:
            raise Fail(f"tier {name!r} has no candidates")
        tier["parsed"] = [parse_candidate(c) for c in cands]
        for c in tier["parsed"]:
            if c["provider"] not in providers:
                raise Fail(f"tier {name!r} candidate {c['id']!r}: provider {c['provider']!r} is not in [providers]")
    for pname, p in providers.items():
        if not p.get("pool"):
            raise Fail(f"provider {pname!r} has no pool")
    for role, tier in (reg.get("roles") or {}).items():
        if tier not in tiers:
            raise Fail(f"role {role!r} maps to unknown tier {tier!r}")
    default = reg.get("default_tier")
    if default is not None and default not in tiers:
        raise Fail(f"default_tier {default!r} is not a tier")
    reg["sha256"] = hashlib.sha256(raw).hexdigest()
    return reg


def iso_to_epoch(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def load_quota(path):
    if path is None or not Path(path).exists():
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Fail(f"quota file {path}: {exc}")
    return data if isinstance(data, dict) else {}


def pool_status(pool, quota, now, stale_after, near, forced):
    """status: ok | near-limit | unknown | exhausted. Only 'exhausted' excludes a pool."""
    if pool in forced:
        return {"pool": pool, "status": "exhausted", "reason": "reported exhausted (--exhausted)", "reset_at": None, "windows": []}
    entry = quota.get(pool)
    if not isinstance(entry, dict) or "fetchedAt" not in entry:
        return {"pool": pool, "status": "unknown", "reason": "no quota data", "reset_at": None, "windows": []}
    fetched = entry["fetchedAt"] / 1000 if entry["fetchedAt"] > 1e11 else entry["fetchedAt"]
    age = int(now - fetched)
    windows = []
    for w in (entry.get("usage") or {}).get("windows") or []:
        reset = iso_to_epoch(w["resetAt"]) if w.get("resetAt") else None
        windows.append({"label": w.get("label"), "used_percent": w.get("usedPercent"), "reset_at": w.get("resetAt"), "_reset": reset})
    base = {"pool": pool, "age_seconds": age, "windows": [{k: v for k, v in w.items() if k != "_reset"} for w in windows]}
    if not windows:
        return {**base, "status": "unknown", "reason": "quota entry has no usage windows", "reset_at": None}
    if age > stale_after:
        return {**base, "status": "unknown", "reason": f"quota data is stale ({age}s old, limit {stale_after}s)", "reset_at": None}
    live = [w for w in windows if w["_reset"] is None or w["_reset"] > now]
    full = [w for w in live if (w["used_percent"] or 0) >= 100]
    if full:
        resets = [w["_reset"] for w in full if w["_reset"] is not None]
        reset_iso = datetime.fromtimestamp(max(resets), timezone.utc).isoformat() if resets else None
        labels = ", ".join(str(w["label"]) for w in full)
        return {**base, "status": "exhausted", "reason": f"window at 100%: {labels}", "reset_at": reset_iso}
    hot = [w for w in live if (w["used_percent"] or 0) >= near]
    if hot:
        return {**base, "status": "near-limit", "reason": "window at or above the near-limit hint: " + ", ".join(str(w["label"]) for w in hot), "reset_at": None}
    return {**base, "status": "ok", "reason": "", "reset_at": None}


def parse_slot(text, taken):
    head, *opts = text.split("|")
    label, eq, role = head.partition("=")
    if not eq:
        label, role = head, head
    if not role:
        raise Fail(f"bad --slot {text!r}")
    slot = {"role": role, "tier": None, "effort": None, "reason": None}
    for opt in opts:
        key, eq, value = opt.partition("=")
        if not eq or key not in slot or key == "role":
            raise Fail(f"bad option {opt!r} in --slot {text!r}: use tier=, effort= or reason=")
        slot[key] = value
    if slot["effort"] is not None and slot["effort"] not in EFFORTS:
        raise Fail(f"bad effort {slot['effort']!r} in --slot {text!r}")
    n = taken.get(label, 0) + 1
    taken[label] = n
    slot["label"] = label if n == 1 else f"{label}#{n}"
    return slot


def resolve(reg, slots, statuses, run_tier, run_effort, known_models):
    providers, tiers, roles = reg["providers"], reg["tiers"], reg.get("roles") or {}
    peer_roles = set((reg.get("peers") or {}).get("roles") or [])
    used_by_tier = {}  # tier -> {model: [labels]} for peer-role slots
    out, warnings = [], []
    for slot in slots:
        role = slot["role"]
        if slot["tier"]:
            tier, origin = slot["tier"], "slot override" + (f" ({slot['reason']})" if slot["reason"] else "")
        elif run_tier:
            tier, origin = run_tier, "run override"
        elif role in roles:
            tier, origin = roles[role], "role default"
        elif reg.get("default_tier"):
            tier, origin = reg["default_tier"], "global default (role not in registry)"
        else:
            raise Fail(f"role {role!r} has no tier and the registry has no default_tier")
        if tier not in tiers:
            raise Fail(f"slot {slot['label']!r}: unknown tier {tier!r}")
        effort_override = slot["effort"] or run_effort
        effort_origin = ("slot override" if slot["effort"] else "run override") if effort_override else None
        is_peer = role in peer_roles
        used = used_by_tier.setdefault(tier, {}) if is_peer else {}
        skipped, available = [], []
        for cand in tiers[tier]["parsed"]:
            prov = providers[cand["provider"]]
            if prov.get("enabled", True) is False:
                skipped.append({"candidate": cand["id"], "reason": "provider disabled in registry", "reset_at": None})
            elif statuses[prov["pool"]]["status"] == "exhausted":
                st = statuses[prov["pool"]]
                skipped.append({"candidate": cand["id"], "reason": f"pool {prov['pool']} exhausted: {st['reason']}", "reset_at": st["reset_at"]})
            else:
                available.append(cand)
        chosen, same_model_as = None, []
        if available:
            fresh = [c for c in available if c["model"] not in used]
            chosen = (fresh or available)[0]
            if is_peer and chosen["model"] in used:
                same_model_as = used[chosen["model"]][:]
            if is_peer:
                used.setdefault(chosen["model"], []).append(slot["label"])
        entry = {"slot": slot["label"], "role": role, "tier": tier, "tier_origin": origin}
        if chosen:
            first = tiers[tier]["parsed"][0]
            entry.update(status="resolved", provider=chosen["provider"], model=chosen["model"],
                         effort=effort_override or chosen["effort"], candidate_effort=chosen["effort"],
                         effort_origin=effort_origin or "tier candidate")
            if chosen is not first and any(s["candidate"] == first["id"] for s in skipped):
                entry["fallback"] = {"from": first["id"], "reason": next(s["reason"] for s in skipped if s["candidate"] == first["id"])}
            if same_model_as:
                entry["same_model_review"] = same_model_as
                warnings.append(f"{slot['label']}: same-model review (same model as {', '.join(same_model_as)})")
            pool = providers[chosen["provider"]]["pool"]
            if statuses[pool]["status"] in ("near-limit", "unknown"):
                warnings.append(f"{slot['label']}: pool {pool} is {statuses[pool]['status']}: {statuses[pool]['reason']}")
            if known_models is not None and chosen["model"] not in known_models:
                warnings.append(f"{slot['label']}: {chosen['model']} is not in the known-models list")
        else:
            resets = sorted(s["reset_at"] for s in skipped if s["reset_at"])
            entry.update(status="unavailable", reason=f"no available candidate in tier {tier}",
                         earliest_reset=resets[0] if resets else None)
        entry["skipped"] = skipped
        out.append(entry)
    return out, warnings


def render_text(plan):
    lines = [f"capability-tier plan  registry {plan['registry']['sha256'][:12]}  profile {plan['registry'].get('profile')}  at {plan['now']}",
             "quota:"]
    for p in plan["quota"]:
        wins = ", ".join(f"{w['label']} {w['used_percent']}%" for w in p["windows"]) or "no windows"
        extra = f" ({p['reason']})" if p["reason"] else ""
        lines.append(f"  {p['pool']:<11} {p['status']:<10} {wins}{extra}")
    lines.append("slots:")
    for a in plan["assignments"]:
        if a["status"] == "resolved":
            notes = []
            if a.get("fallback"):
                notes.append(f"fallback from {a['fallback']['from']}")
            if a.get("same_model_review"):
                notes.append("same-model review")
            if a["effort_origin"] != "tier candidate":
                notes.append(f"effort from {a['effort_origin']}")
            lines.append(f"  {a['slot']:<20} {a['tier']:<7} ({a['tier_origin']}) -> {a['model']}@{a['effort']}" + (f"  [{'; '.join(notes)}]" if notes else ""))
        else:
            reset = f"; earliest reset {a['earliest_reset']}" if a["earliest_reset"] else ""
            lines.append(f"  {a['slot']:<20} {a['tier']:<7} ({a['tier_origin']}) -> UNAVAILABLE: {a['reason']}{reset}")
        for s in a["skipped"]:
            lines.append(f"      skipped {s['candidate']}: {s['reason']}")
    for w in plan["warnings"]:
        lines.append(f"warning: {w}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    ap.add_argument("--quota", default=str(DEFAULT_QUOTA), help="pi-sub cache JSON or a fixture of the same shape")
    ap.add_argument("--now", help="ISO time to resolve at (default: now); for fixtures")
    ap.add_argument("--stale-after", type=int, help="seconds before quota data counts as unknown (default: registry [quota])")
    ap.add_argument("--exhausted", action="append", default=[], metavar="POOL", help="treat a pool as exhausted (a reported provider failure)")
    ap.add_argument("--run-tier")
    ap.add_argument("--run-effort", choices=EFFORTS)
    ap.add_argument("--slot", action="append", required=True, metavar="SPEC",
                    help="[LABEL=]ROLE[|tier=T][|effort=E][|reason=TEXT]; repeat for several slots")
    ap.add_argument("--known-models", metavar="FILE", help="'pi --list-models' output; warns on ids not listed")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    try:
        reg = load_registry(args.registry)
        now = iso_to_epoch(args.now) if args.now else time.time()
        q = reg.get("quota") or {}
        stale = args.stale_after if args.stale_after is not None else q.get("stale_after_seconds", 600)
        near = q.get("near_limit_percent", 97)
        quota = load_quota(args.quota)
        taken = {}
        slots = [parse_slot(s, taken) for s in args.slot]
        for t in (args.run_tier,):
            if t and t not in reg["tiers"]:
                raise Fail(f"unknown --run-tier {t!r}")
        pools = sorted({p["pool"] for p in reg["providers"].values() if p.get("enabled", True) is not False})
        for pool in args.exhausted:
            if pool not in pools:
                raise Fail(f"unknown pool {pool!r} for --exhausted (pools: {', '.join(pools)})")
        statuses = {p: pool_status(p, quota, now, stale, near, set(args.exhausted)) for p in pools}
        known = None
        if args.known_models:
            known = set()
            for line in Path(args.known_models).read_text(encoding="utf-8").splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 2:
                    known.add(f"{parts[0]}/{parts[1]}")
        assignments, warnings = resolve(reg, slots, statuses, args.run_tier, args.run_effort, known)
    except Fail as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    plan = {"plan_version": 1, "now": datetime.fromtimestamp(now, timezone.utc).isoformat(),
            "registry": {"path": str(args.registry), "sha256": reg["sha256"], "profile": reg.get("profile")},
            "stale_after_seconds": stale, "quota": [statuses[p] for p in pools],
            "assignments": assignments, "warnings": warnings}
    print(json.dumps(plan, indent=2) if args.json else render_text(plan))
    return 2 if any(a["status"] == "unavailable" for a in assignments) else 0


if __name__ == "__main__":
    sys.exit(main())
