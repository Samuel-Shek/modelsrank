#!/usr/bin/env bash
# Copy the open-source files from the private working repo into this repo, scan, commit, and optionally push.
# 从私有工作仓库把可公开的文件同步到本仓库，扫描密钥后提交，可选推送。
#
# Usage / 用法:
#   scripts/sync_from_private.sh <private-repo-dir> [--push]
#   e.g. scripts/sync_from_private.sh ~/AI/workspaces/model-rankings --push
#
# Only the whitelist below is copied. Data files (model-data_*.json) and the generated site/ are never copied.
# 只复制下方白名单；数据文件 model-data_*.json 和生成的 site/ 永远不复制。
set -euo pipefail
PRIV="${1:?private repo dir required}"; PUSH="${2:-}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$PRIV/public"
FILES=(build_public_261105.py check_public_261105.py
       public_text_261105.json published_urls.json url_redirects.json
       assets/og.png assets/make_og.py assets/google529a71ca053abf05.html)
# Every page template (public, model, about, ...) is included automatically.
# 所有页面模板（首页、详情、关于……）自动包含。
shopt -s nullglob
for t in "$SRC"/template_*_261105.html; do FILES+=("$(basename "$t")"); done
shopt -u nullglob
for f in "${FILES[@]}"; do
  [ -f "$SRC/$f" ] || { echo "missing: $SRC/$f" >&2; exit 1; }
  mkdir -p "$ROOT/public/$(dirname "$f")"; cp "$SRC/$f" "$ROOT/public/$f"
done
cd "$ROOT"
if git ls-files --others --cached --exclude-standard | grep -E '(^|/)model-data[^/]*\.json$|^public/site/' ; then
  echo "refusing: data file or generated site would be committed" >&2; exit 1
fi
scripts/build_example.sh "$(mktemp -d)/preview" >/dev/null
gitleaks dir . --redact --no-banner --exit-code 1 || { echo "refusing: gitleaks found something" >&2; exit 1; }
git add -A
if git diff --cached --quiet; then echo "nothing to sync"; exit 0; fi
git diff --cached --stat
git commit -q -m "sync: site code and text $(date +%Y-%m-%d)"
if [ "$PUSH" = "--push" ]; then git push -q origin HEAD; echo "pushed"; else echo "committed locally (add --push to publish)"; fi
