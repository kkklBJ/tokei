#!/usr/bin/env python3
"""从 ~/.tokei/sync 的 git 提交历史回填 Claude 每日用量到持久账本。

原理:同步快照每小时提交一次,其中 claude.ranges.today/yesterday 携带
当天完整的 token+模型明细。逐提交回放即可重建每日数据;更早(无提交
历史覆盖)的部分,用峰值快照的累计值减去可重建部分得到残差,按该快照
_dashboard.daily 的每日成本比例分摊,模型构成按同期整体比例。

用法:
  python3 scripts/backfill_ledger.py <device>.json            # dry-run
  python3 scripts/backfill_ledger.py <device>.json --apply    # 合并进本机 ledger
  python3 scripts/backfill_ledger.py <device>.json --out F    # 写到指定文件(给其他设备)
"""
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta

SYNC_DIR = os.path.expanduser("~/.tokei/sync")
LEDGER_FILE = os.path.expanduser("~/.tokei/ledger.json")
FIELDS = ("in", "out", "cr", "cw")


def day_total(d):
    return sum(float(d.get(k, 0) or 0) for k in FIELDS)


def git_show(rev, path):
    r = subprocess.run(["git", "-C", SYNC_DIR, "show", f"{rev}:{path}"],
                       capture_output=True, text=True)
    if r.returncode:
        return None
    try:
        return json.loads(r.stdout)
    except (json.JSONDecodeError, ValueError):
        return None


def extract_range(snap, key):
    r = ((snap.get("claude") or {}).get("ranges") or {}).get(key) or {}
    if day_total(r) <= 0:
        return None
    out = {k: int(r.get(k, 0) or 0) for k in FIELDS}
    out["cost"] = float(r.get("cost", 0) or 0)
    models = {}
    for m in (r.get("models") or []):
        name = m.get("name")
        if not name:
            continue
        models[name] = {k: int(m.get(k, 0) or 0) for k in FIELDS}
        models[name]["cost"] = float(m.get("cost", 0) or 0)
    if models:
        out["models"] = models
    return out


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    device_file = args[0]
    apply_local = "--apply" in args
    out_path = None
    if "--out" in args:
        out_path = args[args.index("--out") + 1]

    revs = subprocess.run(
        ["git", "-C", SYNC_DIR, "log", "--reverse", "--format=%H %ct", "--", device_file],
        capture_output=True, text=True).stdout.split("\n")
    commits = []
    for line in revs:
        parts = line.split()
        if len(parts) == 2:
            commits.append((parts[0], int(parts[1])))
    if not commits:
        print(f"没有找到 {device_file} 的提交历史")
        return 1
    print(f"提交数: {len(commits)}  时间范围: "
          f"{datetime.fromtimestamp(commits[0][1]).date()} → "
          f"{datetime.fromtimestamp(commits[-1][1]).date()}")

    days = {}            # date_iso -> day dict (取高水位)
    peak = (0.0, None, None)   # (all_total, snap, commit_date)

    def consider(dk, candidate):
        if candidate is None:
            return
        kept = days.get(dk)
        if kept is None or day_total(candidate) > day_total(kept):
            days[dk] = candidate

    for i, (rev, ts) in enumerate(commits):
        snap = git_show(rev, device_file)
        if not snap:
            continue
        cdate = datetime.fromtimestamp(ts).date()
        consider(cdate.isoformat(), extract_range(snap, "today"))
        consider((cdate - timedelta(days=1)).isoformat(), extract_range(snap, "yesterday"))
        allr = ((snap.get("claude") or {}).get("ranges") or {}).get("all") \
            or ((snap.get("claude") or {}).get("ranges") or {}).get("year") or {}
        at = day_total(allr)
        if at > peak[0]:
            peak = (at, snap, cdate)
        if i % 500 == 0:
            print(f"  进度 {i}/{len(commits)}")

    recon_total = sum(day_total(v) for v in days.values())
    print(f"重建天数: {len(days)}  重建总量: {recon_total/1e8:.1f}亿")
    print(f"历史峰值累计: {peak[0]/1e8:.1f}亿 @ {peak[2]}")

    # 已知天基准:本机应用时=本机账本 ∪ 重建;导出给其他设备时只用该设备自身重建
    existing = {}
    if not out_path:
        try:
            with open(LEDGER_FILE) as f:
                existing = json.load(f)["tools"].get("claude", {})
        except (OSError, json.JSONDecodeError, ValueError, KeyError):
            existing = {}
    known = {}
    for src in (existing, days):
        for dk, v in src.items():
            if dk not in known or day_total(v) > day_total(known[dk]):
                known[dk] = v
    first_known = min(known) if known else None

    # 残差 = 峰值累计 - 已知天中 ≤峰值日 的部分 → 只分摊到 first_known 之前
    known_until_peak = sum(day_total(v) for dk, v in known.items()
                           if dk <= peak[2].isoformat())
    residual = peak[0] - known_until_peak
    if residual > 1e6 and peak[1] is not None:
        daily = ((peak[1].get("_dashboard") or {}).get("daily") or [])
        pre_days = [(x["date"], float(x.get("claude", 0) or 0)) for x in daily
                    if x.get("date", "") < (first_known or "9999")
                    and float(x.get("claude", 0) or 0) > 0]
        cost_sum = sum(c for _, c in pre_days)
        allr = ((peak[1].get("claude") or {}).get("ranges") or {}).get("all") or {}
        ratio = {k: (allr.get(k, 0) or 0) / max(peak[0], 1) for k in FIELDS}
        peak_models = extract_range(peak[1], "all") or {}
        recon_models = {}
        for v in days.values():
            for mn, mv in (v.get("models") or {}).items():
                agg = recon_models.setdefault(mn, dict.fromkeys(FIELDS, 0))
                for k in FIELDS:
                    agg[k] += mv.get(k, 0)
        res_models = {}
        for mn, mv in (peak_models.get("models") or {}).items():
            diff = {k: max(mv.get(k, 0) - recon_models.get(mn, {}).get(k, 0), 0) for k in FIELDS}
            if sum(diff.values()) > 0:
                diff["cost"] = max(mv.get("cost", 0.0), 0.0)
                res_models[mn] = diff
        print(f"残差(提交历史之前,{len(pre_days)} 天按成本分摊): {residual/1e8:.1f}亿")
        for dk, cost in pre_days:
            share = cost / cost_sum if cost_sum else 1.0 / max(len(pre_days), 1)
            entry = {k: int(residual * ratio[k] * share) for k in FIELDS}
            entry["cost"] = round(cost, 4)
            entry["models"] = {
                mn: {**{k: int(mv[k] * share) for k in FIELDS},
                     "cost": round(mv["cost"] * share, 4)}
                for mn, mv in res_models.items()}
            consider(dk, entry)

    final_total = sum(day_total(v) for v in days.values())
    print(f"回填后总量: {final_total/1e8:.1f}亿  天数: {len(days)}")

    if out_path:
        payload = {"v": 1, "tools": {"claude": days}}
        with open(out_path, "w") as f:
            json.dump(payload, f, separators=(',', ':'))
        print(f"已写出: {out_path}(拷贝到目标设备 ~/.tokei/ledger.json,"
              f"若目标已有账本请先合并)")
        return 0
    if not apply_local:
        print("dry-run 完成。加 --apply 合并进本机账本,或 --out <file> 导出")
        return 0

    try:
        with open(LEDGER_FILE) as f:
            ledger = json.load(f)
    except (OSError, json.JSONDecodeError, ValueError):
        ledger = {"v": 1, "tools": {}}
    stored = ledger.setdefault("tools", {}).setdefault("claude", {})
    updated = 0
    for dk, v in days.items():
        kept = stored.get(dk)
        if kept is None or day_total(v) > day_total(kept):
            stored[dk] = v
            updated += 1
    tmp = LEDGER_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(ledger, f, separators=(',', ':'))
    os.replace(tmp, LEDGER_FILE)
    print(f"已合并进 {LEDGER_FILE}: 更新 {updated} 天")
    return 0


if __name__ == "__main__":
    sys.exit(main())
