#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")/backend"
if [[ $(uname -s) != Darwin ]]; then echo "This launcher requires macOS." >&2; exit 1; fi
case $(uname -m) in
    arm64) export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin" ;;
    *) export PATH="/usr/local/bin:$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin" ;;
esac
unset PYTHONHOME PYTHONPATH
export PYTHONUTF8=1
if [[ ! -x .venv/bin/python ]]; then
    echo "Run Install.command first. Press Enter to close." >&2
    if [[ -t 0 ]]; then read -r; fi
    exit 1
fi
exec .venv/bin/python -X utf8 -m app.launcher "$@"
