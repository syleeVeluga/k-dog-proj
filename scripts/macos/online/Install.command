#!/bin/bash
set -euo pipefail
trap 'status=$?; if [[ $status -ne 0 && -t 0 ]]; then read -r -p "Installation failed. Press Enter to close."; fi' EXIT
cd -- "$(dirname -- "$0")"
if [[ $(uname -s) != Darwin ]]; then echo "This installer requires macOS." >&2; exit 1; fi
major=$(/usr/bin/sw_vers -productVersion); major=${major%%.*}
if (( major < 15 )); then echo "macOS 15 or newer is required." >&2; exit 1; fi
case $(uname -m) in
    arm64) export PATH="/opt/homebrew/bin:$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin" ;;
    x86_64) export PATH="/usr/local/bin:$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin" ;;
    *) echo "Unsupported Mac architecture." >&2; exit 1 ;;
esac
unset PYTHONHOME PYTHONPATH UV_PYTHON UV_PYTHON_DOWNLOADS
export PYTHONUTF8=1
# Detect extraction damage before installing Python or project dependencies.
/usr/bin/shasum -a 256 --check --status SHA256SUMS
brew_args=(install)
command -v uv >/dev/null || brew_args+=(uv)
if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then brew_args+=(ffmpeg); fi
if (( ${#brew_args[@]} > 1 )); then
    if ! command -v brew >/dev/null; then
        echo "Install uv and FFmpeg first. See macOS_설치안내.md (https://brew.sh)." >&2
        exit 1
    fi
    brew "${brew_args[@]}"
fi
cd backend
export UV_PROJECT_ENVIRONMENT="$PWD/.venv"
uv sync --locked --no-dev --python 3.14.8 --managed-python
python="$PWD/.venv/bin/python"
"$python" -X utf8 -m app.launcher --check
if [[ ${1:-} != --skip-accounts ]]; then
    for role in operator developer; do
        read -r -p "New $role account name (Enter to skip): " account
        if [[ -n $account ]]; then "$python" -X utf8 -m app.manage create-user "$account" --role "$role"; fi
    done
fi
echo "Installation complete. Open Start.command."
echo 'Data: KDOG_DATA_DIR or ~/Library/Application Support/K-DOG/data'
