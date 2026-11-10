#!/usr/bin/env bash
# Build a preview site from the fictional sample data, without touching tracked files.
# 用示例数据（虚构模型）生成一个预览站，不改动仓库里的任何文件。
# Usage / 用法: scripts/build_example.sh [output_dir]   (default: ./preview)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/preview}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
cp -R "$ROOT/public/." "$WORK/"
rm -rf "$WORK/site"
cp "$ROOT/example/sample-data.json" "$WORK/model-data_261105.json"
echo '[]' > "$WORK/published_urls.json"   # sample data has none of the production URLs
echo '{}' > "$WORK/url_redirects.json"
python3 "$WORK/build_public_261105.py"
rm -rf "$OUT" && mkdir -p "$OUT" && cp -R "$WORK/site/." "$OUT/"
echo "Preview written to $OUT  (serve with: python3 -m http.server -d \"$OUT\" 8000)"
