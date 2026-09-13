#!/usr/bin/env bash

set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

echo "[1/4] Compile backend"
python3 -m compileall -q backend/app

echo "[2/4] Run backend tests"
python3 -m pytest backend/tests -q

echo "[3/5] Run webtoon cut frontend tests"
npm --prefix frontend run test:webtoon-cut

echo "[4/5] Build frontend"
npm run build

echo "[5/5] Check diff whitespace"
git diff --check

echo "Verification completed."
