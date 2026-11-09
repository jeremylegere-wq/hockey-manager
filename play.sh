#!/bin/sh
# Hockey Manager: opens the game in its own window (launch screen, then your careers). Careers are saved in ./saves.
# The first run builds the fictional world (a few seconds) and offers to install the window support (pywebview) into
# .runtime/ next to the game; nothing system-wide.
# Linux: the window uses Qt WebEngine from pip; if it will not start, install libxcb-cursor0 (Debian/Ubuntu) or run
#   ./play.sh --no-window    to use a Chromium/Chrome/Edge app window instead.
cd "$(dirname "$0")"
mkdir -p saves
exec python3 -m hs.app --saves saves --template auto --env auto "$@"
