#!/usr/bin/env python3
"""BudgetRoom engine: all the money math the chat agent relies on.

The agent never does arithmetic itself; it calls this script and relays the
output. Standard library only (matplotlib is optional, for PNG charts).

Data layout (all under ./data, override with BUDGET_DATA):
  profiles/<id>.json      budget plan for one person
  ledgers/<id>.csv        every expense / extra income they logged
  households/<id>.json    who is parent / child, for allowance requests
  households/<id>-requests.json

Set BUDGET_TODAY=YYYY-MM-DD to freeze "today" (demos and tests).
"""
from __future__ import annotations

import argparse
import calendar
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(os.environ.get("BUDGET_DATA", Path(__file__).resolve().parent / "data"))
FIELDS = ["id", "date", "type", "amount", "category", "note", "by"]
SYMBOLS = {"EUR": ("€", True), "USD": ("$", True), "MAD": ("MAD", False)}


class BudgetError(Exception):
    pass


# ---------------------------------------------------------------- helpers

def today() -> date:
    forced = os.environ.get("BUDGET_TODAY")
    return date.fromisoformat(forced) if forced else date.today()


def money(amount: float, currency: str) -> str:
    sym, prefix = SYMBOLS.get(currency, (currency, False))
    sign = "-" if amount < 0 else ""
    txt = f"{abs(amount):,.2f}"
    txt = txt[:-3] if txt.endswith(".00") else txt
    return f"{sign}{sym}{txt}" if prefix else f"{sign}{txt} {sym}"


def bar(pct: float, width: int = 10) -> str:
    filled = max(0, min(width, round(pct / 100 * width)))
    return "█" * filled + "░" * (width - filled)


def load_profile(pid: str) -> dict:
    path = ROOT / "profiles" / f"{pid}.json"
    if not path.exists():
        known = ", ".join(sorted(p.stem for p in (ROOT / "profiles").glob("*.json")))
        raise BudgetError(f"Unknown profile '{pid}'. Known profiles: {known or 'none'}")
    prof = json.loads(path.read_text())
    prof.setdefault("id", pid)
    prof.setdefault("fixed", {})
    prof.setdefault("categories", {})
    prof.setdefault("savings_goal", 0)
    return prof


def ledger_path(pid: str) -> Path:
    return ROOT / "ledgers" / f"{pid}.csv"


def read_ledger(pid: str) -> list[dict]:
    path = ledger_path(pid)
    if not path.exists():
        return []
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["amount"] = float(r["amount"])
        r["date"] = date.fromisoformat(r["date"])
    return rows


def write_ledger(pid: str, rows: list[dict]) -> None:
    path = ledger_path(pid)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({**r, "date": r["date"].isoformat(), "amount": f"{r['amount']:.2f}"})


def append_entry(pid: str, kind: str, amount: float, category: str, note: str,
                 by: str = "", on: date | None = None) -> dict:
    if amount <= 0:
        raise BudgetError("Amount must be positive.")
    rows = read_ledger(pid)
    next_id = max((int(r["id"]) for r in rows), default=0) + 1
    entry = {"id": str(next_id), "date": on or today(), "type": kind,
             "amount": round(amount, 2), "category": category.lower(),
             "note": note, "by": by}
    rows.append(entry)
    write_ledger(pid, rows)
    return entry


def month_rows(rows: list[dict], ref: date) -> list[dict]:
    return [r for r in rows if r["date"].year == ref.year and r["date"].month == ref.month]


# ---------------------------------------------------------------- core math

def snapshot(prof: dict, ref: date | None = None) -> dict:
    """Everything about the current month in one dict."""
    ref = ref or today()
    rows = month_rows(read_ledger(prof["id"]), ref)
    days_in_month = calendar.monthrange(ref.year, ref.month)[1]
    days_left = days_in_month - ref.day + 1  # today still counts
    elapsed_pct = ref.day / days_in_month * 100

    planned_income = sum(prof.get("income", {}).values())
    extra_income = sum(r["amount"] for r in rows if r["type"] == "income")
    fixed_total = sum(prof["fixed"].values())
    fixed_names = {k.lower() for k in prof["fixed"]}

    spent = defaultdict(float)
    for r in rows:
        if r["type"] == "expense" and r["category"] not in fixed_names:
            spent[r["category"]] += r["amount"]

    flex_budget = planned_income + extra_income - fixed_total - prof["savings_goal"]
    flex_spent = sum(spent.values())
    flex_left = flex_budget - flex_spent

    cats = []
    names = list(prof["categories"]) + [c for c in spent if c not in prof["categories"]]
    for c in names:
        limit = prof["categories"].get(c, 0)
        s = spent.get(c, 0.0)
        pct = s / limit * 100 if limit else (100.0 if s else 0.0)
        if limit == 0 and s > 0:
            flag = "unplanned"
        elif s > limit:
            flag = "over"
        elif pct > elapsed_pct + 30 and pct >= 50:
            flag = "fast"
        else:
            flag = "ok"
        cats.append({"name": c, "limit": limit, "spent": s, "pct": pct, "flag": flag})

    planned_flex = sum(prof["categories"].values()) or max(flex_budget, 0)
    planned_daily = planned_flex / days_in_month
    avg_daily = flex_spent / ref.day

    return {"ref": ref, "days_in_month": days_in_month, "days_left": days_left,
            "elapsed_pct": elapsed_pct, "planned_income": planned_income,
            "extra_income": extra_income, "fixed_total": fixed_total,
            "savings_goal": prof["savings_goal"], "flex_budget": flex_budget,
            "flex_spent": flex_spent, "flex_left": flex_left,
            "per_day_left": flex_left / days_left, "avg_daily": avg_daily,
            "planned_daily": planned_daily,
            "categories": cats, "rows": rows}


def afford(prof: dict, amount: float, category: str | None = None) -> dict:
    snap = snapshot(prof)
    after = snap["flex_left"] - amount
    per_day = after / snap["days_left"]
    need = snap["planned_daily"]
    if after < 0:
        verdict = "no"
    elif per_day >= need:
        verdict = "yes"
    elif per_day >= 0.6 * need:
        verdict = "tight"
    else:
        verdict = "no"
    cat_warning = None
    if category:
        cat = next((c for c in snap["categories"] if c["name"] == category.lower()), None)
        if cat and cat["limit"] and cat["spent"] + amount > cat["limit"]:
            cat_warning = (category.lower(), cat["spent"] + amount - cat["limit"])
    return {"snap": snap, "amount": amount, "after": after, "per_day": per_day,
            "need": need, "verdict": verdict, "cat_warning": cat_warning,
            "savings_at_risk": after < 0 and after + snap["savings_goal"] >= 0}


# ---------------------------------------------------------------- rendering

FLAG_ICON = {"ok": "🟢", "fast": "🟡", "over": "🔴", "unplanned": "⚪"}


def render_status(prof: dict, snap: dict) -> str:
    cur = prof["currency"]
    ref = snap["ref"]
    out = [f"**{prof['name']}**: {ref:%B %Y}, day {ref.day}/{snap['days_in_month']}",
           f"Flexible budget: {money(snap['flex_spent'], cur)} spent of "
           f"{money(snap['flex_budget'], cur)} → **{money(snap['flex_left'], cur)} left** "
           f"(~{money(snap['per_day_left'], cur)}/day for {snap['days_left']} days)", ""]
    out.append("| | Category | Spent | Limit | |")
    out.append("|---|---|---:|---:|---|")
    for c in snap["categories"]:
        out.append(f"| {FLAG_ICON[c['flag']]} | {c['name']} | {money(c['spent'], cur)} | "
                   f"{money(c['limit'], cur)} | {bar(c['pct'])} {c['pct']:.0f}% |")
    notes = []
    for c in snap["categories"]:
        if c["flag"] == "over":
            notes.append(f"🔴 {c['name']} is over by {money(c['spent'] - c['limit'], cur)}")
        elif c["flag"] == "fast":
            notes.append(f"🟡 {c['name']} at {c['pct']:.0f}% while the month is at "
                         f"{snap['elapsed_pct']:.0f}%")
        elif c["flag"] == "unplanned":
            notes.append(f"⚪ {c['name']} has no budget line ({money(c['spent'], cur)} spent)")
    if snap["savings_goal"]:
        status = "safe" if snap["flex_left"] >= 0 else "**at risk**"
        notes.append(f"💰 Savings goal {money(snap['savings_goal'], cur)}: {status}")
    if notes:
        out += [""] + notes
    return "\n".join(out)


def render_afford(prof: dict, res: dict, what: str) -> str:
    cur = prof["currency"]
    snap = res["snap"]
    head = {"yes": "✅ Yes, comfortably.", "tight": "⚠️ Possible, but tight.",
            "no": "❌ Not without breaking the plan."}[res["verdict"]]
    out = [f"{head} {what} = {money(res['amount'], cur)}",
           f"- Left after buying: **{money(res['after'], cur)}** for {snap['days_left']} days "
           f"(~{money(res['per_day'], cur)}/day)",
           f"- Your plan assumes ~{money(res['need'], cur)}/day "
           f"(so far this month: ~{money(snap['avg_daily'], cur)}/day)"]
    if snap["per_day_left"] < res["need"]:
        out.append("- Heads-up: even before this purchase you're spending faster than planned")
    if res["cat_warning"]:
        c, over = res["cat_warning"]
        out.append(f"- It would push **{c}** over its limit by {money(over, cur)}")
    if res["savings_at_risk"]:
        out.append(f"- Only possible by dipping into this month's savings goal "
                   f"({money(snap['savings_goal'], cur)})")
    return "\n".join(out)


def render_report(prof: dict, days: int = 7) -> str:
    cur = prof["currency"]
    end = today()
    start = end - timedelta(days=days - 1)
    prev_start = start - timedelta(days=days)
    fixed_names = {k.lower() for k in prof["fixed"]}
    rows = [r for r in read_ledger(prof["id"])
            if r["type"] == "expense" and r["category"] not in fixed_names]
    cur_rows = [r for r in rows if start <= r["date"] <= end]
    prev_rows = [r for r in rows if prev_start <= r["date"] < start]
    total, prev_total = sum(r["amount"] for r in cur_rows), sum(r["amount"] for r in prev_rows)
    by_cat = defaultdict(float)
    for r in cur_rows:
        by_cat[r["category"]] += r["amount"]
    out = [f"📊 **{prof['name']}**: last {days} days ({start:%d %b} → {end:%d %b})",
           f"Day-to-day spending: **{money(total, cur)}** in {len(cur_rows)} expenses "
           f"(fixed costs excluded)"]
    if prev_rows:
        delta = total - prev_total
        word = "more" if delta > 0 else "less"
        out[-1] += f" ({money(abs(delta), cur)} {word} than the {days} days before)"
    if by_cat:
        out.append("")
        for c, v in sorted(by_cat.items(), key=lambda kv: -kv[1]):
            out.append(f"- {c}: {money(v, cur)}")
        top = sorted(cur_rows, key=lambda r: -r["amount"])[:3]
        out.append("")
        out.append("Biggest: " + ", ".join(
            f"{money(r['amount'], cur)} {r['note'] or r['category']}" for r in top))
    out += ["", render_status(prof, snapshot(prof))]
    return "\n".join(out)


def save_chart(prof: dict, path: str) -> str:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        raise BudgetError("PNG charts need matplotlib: pip install -r requirements.txt")
    snap = snapshot(prof)
    cats = [c for c in snap["categories"] if c["limit"] or c["spent"]]
    names = [c["name"] for c in cats]
    fig, ax = plt.subplots(figsize=(7, 0.55 * len(cats) + 1.5))
    ax.barh(names, [c["limit"] for c in cats], color="#e5e7eb", label="limit")
    colors = {"ok": "#16a34a", "fast": "#d97706", "over": "#dc2626", "unplanned": "#6b7280"}
    ax.barh(names, [c["spent"] for c in cats], height=0.5,
            color=[colors[c["flag"]] for c in cats], label="spent")
    ax.invert_yaxis()
    ax.set_xlabel(prof["currency"])
    ax.set_title(f"{prof['name']}: {snap['ref']:%B %Y} (day {snap['ref'].day})")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="lower right", frameon=False)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    return path


# ---------------------------------------------------------------- households

def household_for(pid: str) -> tuple[dict, Path]:
    for path in (ROOT / "households").glob("*.json"):
        if path.name.endswith("-requests.json"):
            continue
        h = json.loads(path.read_text())
        if pid in h.get("parents", []) + h.get("children", []):
            return h, path.with_name(f"{path.stem}-requests.json")
    raise BudgetError(f"'{pid}' is not part of any household.")


def load_requests(path: Path) -> list[dict]:
    return json.loads(path.read_text()) if path.exists() else []


def request_money(child: str, amount: float, reason: str) -> str:
    h, rpath = household_for(child)
    if child not in h["children"]:
        raise BudgetError(f"Only children can send requests in household {h['id']}.")
    prof = load_profile(child)
    reqs = load_requests(rpath)
    rid = max((r["id"] for r in reqs), default=0) + 1
    reqs.append({"id": rid, "child": child, "amount": amount, "reason": reason,
                 "status": "pending", "date": today().isoformat()})
    rpath.write_text(json.dumps(reqs, indent=2))
    parent = load_profile(h["parents"][0])
    res = afford(parent, amount, parent.get("allowance_category"))
    return (f"📨 Request #{rid}: {prof['name']} asks for {money(amount, prof['currency'])}: "
            f"\"{reason}\"\n\nImpact for {parent['name']}: "
            f"{render_afford(parent, res, 'Sending it')}\n\n"
            f"Reply `approve {rid}` or `deny {rid}`.")


def decide(parent: str, rid: int, approve: bool, note: str = "") -> str:
    h, rpath = household_for(parent)
    if parent not in h["parents"]:
        raise BudgetError("Only a parent can approve or deny requests.")
    reqs = load_requests(rpath)
    req = next((r for r in reqs if r["id"] == rid), None)
    if not req:
        raise BudgetError(f"No request #{rid}.")
    if req["status"] != "pending":
        raise BudgetError(f"Request #{rid} is already {req['status']}.")
    child, pprof = load_profile(req["child"]), load_profile(parent)
    if child["currency"] != pprof["currency"]:
        raise BudgetError("Parent and child use different currencies; log the transfer manually.")
    req["status"] = "approved" if approve else "denied"
    req["decided_by"], req["decision_note"] = parent, note
    rpath.write_text(json.dumps(reqs, indent=2))
    amt = money(req["amount"], child["currency"])
    if not approve:
        return f"🚫 Request #{rid} denied. {note}".strip()
    append_entry(req["child"], "income", req["amount"], "allowance",
                 f"from {pprof['name']}: {req['reason']}", by=parent)
    append_entry(parent, "expense", req["amount"], pprof.get("allowance_category", "family"),
                 f"to {child['name']}: {req['reason']}", by=parent)
    return f"✅ Request #{rid} approved: {amt} moved from {pprof['name']} to {child['name']}."


# ---------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("profiles", help="list profiles")
    s = sub.add_parser("add", help="log an expense")
    s.add_argument("profile"); s.add_argument("amount", type=float); s.add_argument("category")
    s.add_argument("note", nargs="?", default=""); s.add_argument("--by", default="")
    s.add_argument("--date", type=date.fromisoformat)
    s = sub.add_parser("income", help="log extra income (gift, side job...)")
    s.add_argument("profile"); s.add_argument("amount", type=float); s.add_argument("source")
    s.add_argument("--by", default=""); s.add_argument("--date", type=date.fromisoformat)
    s = sub.add_parser("undo", help="remove the last ledger entry")
    s.add_argument("profile")
    s = sub.add_parser("status", help="month overview")
    s.add_argument("profile")
    s = sub.add_parser("afford", help="can I afford X?")
    s.add_argument("profile"); s.add_argument("amount", type=float)
    s.add_argument("category", nargs="?"); s.add_argument("--what", default="This purchase")
    s = sub.add_parser("report", help="weekly report")
    s.add_argument("profile"); s.add_argument("--days", type=int, default=7)
    s.add_argument("--png", help="also save a chart to this path")
    s = sub.add_parser("request", help="child asks parent for money")
    s.add_argument("profile"); s.add_argument("amount", type=float); s.add_argument("reason")
    for name in ("approve", "deny"):
        s = sub.add_parser(name, help=f"parent {name}s a request")
        s.add_argument("profile"); s.add_argument("request_id", type=int)
        s.add_argument("note", nargs="?", default="")
    s = sub.add_parser("requests", help="list a household's requests")
    s.add_argument("profile")

    a = p.parse_args(argv)
    try:
        if a.cmd == "profiles":
            for path in sorted((ROOT / "profiles").glob("*.json")):
                pr = load_profile(path.stem)
                print(f"- {pr['id']}: {pr['name']} ({pr.get('type', '?')}, {pr['currency']}) "
                      f"chat users: {', '.join(pr.get('chat_users', [])) or '-'}")
        elif a.cmd in ("add", "income"):
            prof = load_profile(a.profile)
            kind = "expense" if a.cmd == "add" else "income"
            cat = a.category if kind == "expense" else a.source
            e = append_entry(a.profile, kind, a.amount, cat,
                             a.note if kind == "expense" else "", a.by, a.date)
            verb = "Logged" if kind == "expense" else "Added income"
            print(f"✅ {verb} #{e['id']}: {money(e['amount'], prof['currency'])} · {e['category']}"
                  + (f" · {e['note']}" if e["note"] else ""))
            if kind == "expense":
                snap = snapshot(prof, e["date"]) if e["date"].month == today().month else snapshot(prof)
                c = next((c for c in snap["categories"] if c["name"] == e["category"]), None)
                if c:
                    print(f"{FLAG_ICON[c['flag']]} {c['name']}: {money(c['spent'], prof['currency'])}"
                          f" / {money(c['limit'], prof['currency'])} ({c['pct']:.0f}%) · "
                          f"{money(snap['flex_left'], prof['currency'])} flexible left this month")
                elif e["category"] in {k.lower() for k in prof["fixed"]}:
                    print("ℹ️ Fixed cost, already reserved in the plan.")
        elif a.cmd == "undo":
            prof = load_profile(a.profile)
            rows = read_ledger(a.profile)
            if not rows:
                raise BudgetError("Ledger is empty.")
            last = rows.pop()
            write_ledger(a.profile, rows)
            print(f"↩️ Removed #{last['id']}: {money(last['amount'], prof['currency'])} · "
                  f"{last['category']} ({last['date']})")
        elif a.cmd == "status":
            prof = load_profile(a.profile)
            print(render_status(prof, snapshot(prof)))
        elif a.cmd == "afford":
            prof = load_profile(a.profile)
            print(render_afford(prof, afford(prof, a.amount, a.category), a.what))
        elif a.cmd == "report":
            prof = load_profile(a.profile)
            print(render_report(prof, a.days))
            if a.png:
                print(f"\n![chart]({save_chart(prof, a.png)})")
        elif a.cmd == "request":
            print(request_money(a.profile, a.amount, a.reason))
        elif a.cmd in ("approve", "deny"):
            print(decide(a.profile, a.request_id, a.cmd == "approve", a.note))
        elif a.cmd == "requests":
            h, rpath = household_for(a.profile)
            reqs = load_requests(rpath)
            if not reqs:
                print("No requests yet.")
            for r in reqs:
                print(f"#{r['id']} {r['date']} {r['child']} {r['amount']:g}: {r['reason']} [{r['status']}]")
    except BudgetError as e:
        print(f"⚠️ {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
