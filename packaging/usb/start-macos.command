#!/bin/bash
# DialMouse launcher (macOS). Double-click in Finder, or run from Terminal with
# args, e.g.  ./start-macos.command --test
cd "$(dirname "$0")"

# First run: seed a personal config.json from the shipped example.
if [ ! -f config.json ] && [ -f config.example.json ]; then
    cp config.example.json config.json
    echo "Created config.json from config.example.json. Run --identify then --set-minimon N to pick your Mini Mon."
fi

# Unsigned binary: if macOS blocks it, right-click dialmouse-macos -> Open once,
# and grant Accessibility under System Settings -> Privacy & Security.
exec "./bin/dialmouse-macos" "$@"
