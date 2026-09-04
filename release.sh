#!/bin/bash
# Tokei 一键发布:打包 → R2 三件套 → GitHub Release → 英雄页 → 全链路校验。
# 用法: ./release.sh [--notes "版本说明"]
set -euo pipefail
cd "$(dirname "$0")"

NOTES="${2:-}"
[ "${1:-}" = "--notes" ] || NOTES=""

VERSION="$(sed -nE 's/.*releaseTag = "v([^"]+)".*/\1/p' Tokei/Sources/Tokei/Updater.swift | head -n 1)"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "❌ 无法从 Updater.swift 读取版本号"; exit 1; }
TAG="v$VERSION"
echo "==> 目标版本: $TAG"

# ---- 预检:防止双机竞争覆盖 ----
ONLINE_TAG="$(curl -sf "https://dl.lanshuagent.com/tokei/latest.json?ts=$(date +%s)" | /usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin).get("tag_name",""))' 2>/dev/null || echo "")"
echo "==> 线上版本: ${ONLINE_TAG:-未知}"
if [ "$ONLINE_TAG" = "$TAG" ]; then
    read -r -p "⚠️  线上已是 $TAG(可能另一台设备已发布)。继续会覆盖线上包,确定? [y/N] " ans
    [ "$ans" = "y" ] || { echo "已取消"; exit 1; }
fi
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "❌ 工作区有未提交改动,先提交再发布"; exit 1
fi
git fetch -q && [ -z "$(git log HEAD..origin/main --oneline)" ] || { echo "❌ 本地落后远端,先 git pull"; exit 1; }
[ -z "$(git log origin/main..HEAD --oneline)" ] || { echo "❌ 有未 push 的提交,先 git push"; exit 1; }

# ---- 打包 ----
echo "==> 打包"
# 公开发布固定 ad-hoc 签名：package.sh 的自动探测是给本地开发保 Keychain ACL 的,
# 发布产物不能取决于构建机上恰好装了哪张个人证书。
( cd Tokei && TOKEI_CODESIGN_IDENTITY=- ./package.sh ) | grep -E 'Built|DMG|metadata' || true
DMG="Tokei/Tokei.dmg"
[ -f "$DMG" ] || { echo "❌ DMG 未生成"; exit 1; }
SHA="$(shasum -a 256 "$DMG" | cut -d' ' -f1)"
echo "==> 本地 DMG sha256: $SHA"

# ---- R2 三件套 ----
echo "==> 上传 R2"
wrangler r2 object put "lanshu/tokei/Tokei-$TAG.dmg" --file="$DMG" --remote | tail -1
wrangler r2 object put "lanshu/tokei/latest.json" --file=Tokei/latest.json --content-type=application/json --remote | tail -1
wrangler r2 object put "lanshu/tokei/usage.30s.py" --file=usage.30s.py --remote | tail -1

# ---- GitHub Release ----
echo "==> GitHub Release"
if gh release view "$TAG" --repo cclank/tokei >/dev/null 2>&1; then
    cp "$DMG" "/tmp/Tokei-$TAG.dmg"
    gh release upload "$TAG" "/tmp/Tokei-$TAG.dmg" --repo cclank/tokei --clobber
    rm -f "/tmp/Tokei-$TAG.dmg"
else
    gh release create "$TAG" "$DMG#Tokei-$TAG.dmg" --repo cclank/tokei \
        --title "$TAG" --notes "${NOTES:-Release $TAG}"
fi

# ---- 英雄页 ----
echo "==> 英雄页"
sed -i '' -E "s/Tokei-v[0-9]+\.[0-9]+\.[0-9]+\.dmg/Tokei-$TAG.dmg/g" site/index.html
wrangler pages deploy site --project-name=tokei --commit-dirty=true | tail -1
if ! git diff --quiet site/index.html; then
    git add site/index.html
    git commit -m "chore: 英雄页下载链接切换到 $TAG"
    git push --no-verify
fi

# ---- 全链路校验 ----
echo "==> 校验"
sleep 3
ONLINE_JSON="$(curl -sf "https://dl.lanshuagent.com/tokei/latest.json?ts=$(date +%s)")"
ONLINE_TAG2="$(echo "$ONLINE_JSON" | /usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"])')"
ONLINE_SHA="$(echo "$ONLINE_JSON" | /usr/bin/python3 -c 'import json,sys; print(json.load(sys.stdin)["sha256"])')"
[ "$ONLINE_TAG2" = "$TAG" ] || { echo "❌ latest.json 版本不对: $ONLINE_TAG2"; exit 1; }
[ "$ONLINE_SHA" = "$SHA" ] || { echo "❌ latest.json sha 与本地包不一致"; exit 1; }
SERVED_SHA="$(curl -sf "https://dl.lanshuagent.com/tokei/Tokei-$TAG.dmg" | shasum -a 256 | cut -d' ' -f1)"
[ "$SERVED_SHA" = "$SHA" ] || { echo "❌ 线上 DMG 与 latest.json 校验值不一致(可能被另一台设备覆盖)"; exit 1; }
echo "✅ $TAG 全渠道发布完成且校验一致"
