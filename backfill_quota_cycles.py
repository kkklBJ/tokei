#!/usr/bin/env python3
"""从 ~/.tokei/sync 的 git 历史回填额度周期锚点。

周额度的 resets_at 会不定期重锚,历史边界推不出来只能观测。同步仓库里每个设备
快照都带着当时的 resets_at,每 40-80 分钟一次提交,把它们全翻出来就是一份现成的
观测记录。跑一次就够了,之后 usage.30s.py 每次刷新会自己追加。

用法: python3 backfill_quota_cycles.py [--dry-run]
"""
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime

HOME = os.path.expanduser("~")
ANCHOR_FILE = os.path.join(HOME, ".tokei", "quota_cycles.json")
JITTER = 120

# 工具 → (reset 字段, 已用% 字段)
FIELDS = {
    "claude": ("q7_reset", "q7"),
    "codex": ("rw", "pw"),
    "grok": ("reset", "pct"),
}


def sync_dir():
    try:
        with open(os.path.join(HOME, ".tokei", "config.json"), encoding="utf-8") as f:
            configured = json.load(f).get("sync_dir")
    except (OSError, ValueError):
        configured = None
    return os.path.expanduser(configured or os.path.join(HOME, ".tokei", "sync"))


def snapshots(root, name):
    """[(提交时间, 快照)] —— 该设备快照文件的每一个历史版本。"""
    revs = subprocess.run(
        ["git", "rev-list", "--format=%H %ct", "--no-commit-header", "HEAD", "--", name],
        cwd=root, capture_output=True, text=True).stdout.split()
    pairs = [(revs[i], int(revs[i + 1])) for i in range(0, len(revs) - 1, 2)]
    if not pairs:
        return []
    spec = ("\n".join(f"{h}:{name}" for h, _ in pairs) + "\n").encode()
    blob = subprocess.run(["git", "cat-file", "--batch"], cwd=root,
                          input=spec, capture_output=True).stdout

    out, cursor = [], 0
    for _h, when in pairs:
        newline = blob.index(b"\n", cursor)
        header = blob[cursor:newline].split()
        if len(header) < 3 or header[1] != b"blob":
            cursor = newline + 1
            continue
        size = int(header[2])
        try:
            out.append((when, json.loads(blob[newline + 1:newline + 1 + size])))
        except ValueError:
            pass
        cursor = newline + 1 + size + 1
    return out


def record(anchors, tool, reset, used, when):
    rows = anchors.setdefault(tool, [])
    for row in rows:
        if abs(row["reset"] - reset) <= JITTER:
            row["max_used"] = max(row["max_used"], used)
            row["first_seen"] = min(row["first_seen"], when)
            row["last_seen"] = max(row["last_seen"], when)
            return False
    rows.append({"reset": reset, "first_seen": when, "last_seen": when, "max_used": used})
    return True


def main():
    root = sync_dir()
    if not os.path.isdir(os.path.join(root, ".git")):
        sys.exit(f"{root} 不是 git 仓库，没有历史可回填")

    try:
        with open(ANCHOR_FILE, encoding="utf-8") as f:
            anchors = json.load(f).get("anchors") or {}
    except (OSError, ValueError):
        anchors = {}
    before = {tool: len(rows) for tool, rows in anchors.items()}

    names = [n for n in sorted(os.listdir(root)) if n.endswith(".json")]
    for name in names:
        for when, snapshot in snapshots(root, name):
            if not isinstance(snapshot, dict):
                continue
            for tool, (reset_key, used_key) in FIELDS.items():
                data = snapshot.get(tool)
                if not isinstance(data, dict):
                    continue
                reset, used = data.get(reset_key), data.get(used_key)
                if not isinstance(reset, (int, float)) or reset <= 0:
                    continue
                record(anchors, tool, int(reset), float(used or 0), when)

    stamp = lambda e: datetime.fromtimestamp(e).strftime("%m-%d %H:%M")
    for tool in sorted(anchors):
        rows = sorted(anchors[tool], key=lambda r: r["reset"])
        anchors[tool] = rows
        real = [r for r in rows if r["max_used"] >= 2]
        print(f"\n{tool}: {len(rows)} 个锚点 (+{len(rows) - before.get(tool, 0)} 新增)，"
              f"其中 {len(real)} 个有真实用量")
        span = 7 * 86400
        for i, row in enumerate(real):
            start = row["reset"] - span
            end = (min(row["reset"], real[i + 1]["reset"] - span)
                   if i + 1 < len(real) else row["reset"])
            print(f"  {stamp(start)} → {stamp(end)}  {(end - start) / 86400:5.2f}天  "
                  f"用到 {row['max_used']:5.1f}%")

    if "--dry-run" in sys.argv:
        print("\n--dry-run，未写入")
        return

    os.makedirs(os.path.dirname(ANCHOR_FILE), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tokei-cycles-", suffix=".json",
                               dir=os.path.dirname(ANCHOR_FILE))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"anchors": anchors}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ANCHOR_FILE)
    print(f"\n已写入 {ANCHOR_FILE}")


if __name__ == "__main__":
    main()
