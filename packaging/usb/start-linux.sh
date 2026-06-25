#!/usr/bin/env bash
# DialMouse launcher (Linux). Run ./start-linux.sh, or pass args, e.g.
#   ./start-linux.sh --test     ./start-linux.sh --hid-test
set -euo pipefail
cd "$(dirname "$0")"

# First run: seed a personal config.json from the shipped example.
if [ ! -f config.json ] && [ -f config.example.json ]; then
    cp config.example.json config.json
    echo "Created config.json from config.example.json. Run --identify then --set-minimon N to pick your Mini Mon."
fi

exec "./bin/dialmouse-linux" "$@"
