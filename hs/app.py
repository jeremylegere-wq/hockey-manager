"""Hockey Manager as a desktop application (docs/DESKTOP.md).

    python -m hs.app --saves saves --template auto --env auto

The game server runs on 127.0.0.1 in a background thread and the interface opens in its own window, not a browser
tab. In order of preference:

  1. a native window (pywebview): WebView2 on Windows, WebKit on macOS, Qt WebEngine or GTK WebKit on Linux;
  2. an app window from Chrome, Chromium, Edge or Brave (--app: no tabs, no address bar, its own profile);
  3. the default browser (last resort; the game says so on the title screen).

pywebview is not part of the standard library. The first time, the launcher offers to install it into a private
environment next to the game (.runtime/, nothing system-wide) and restarts itself from there; `--setup` does that
without asking, `--no-window` skips straight to option 2. Closing the window saves and stops the game.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import venv
from pathlib import Path

from .ui.server import make_server

TITLE = "Hockey Manager"
ROOT = Path(__file__).resolve().parent.parent          # the game folder (where play.sh lives)
RUNTIME = ROOT / ".runtime"


# ---------------------------------------------------------------- the window
class NativeWindow:
    """pywebview window; the server calls set_title and close from its threads."""

    def __init__(self, webview, url, storage):
        self.webview = webview
        self.win = webview.create_window(TITLE, url, width=1600, height=960, min_size=(1100, 680), maximized=True,
                                         background_color="#dfe7f1", text_select=True)
        self.storage = storage

    def set_title(self, t):
        try:
            self.win.set_title(f"{TITLE} - {t}" if t else TITLE)
        except Exception:
            pass

    def close(self):
        try:
            self.win.destroy()
        except Exception:
            pass

    def run(self):
        kw = dict(private_mode=False, storage_path=str(self.storage))
        gui = os.environ.get("HS_WEBVIEW_GUI")                  # e.g. qt or gtk, to force a Linux backend
        if gui:
            kw["gui"] = gui
        self.webview.start(**kw)


class AppWindow:
    """A Chromium-family browser in app mode, with its own profile so it opens as a separate window."""

    def __init__(self, exe, url, profile):
        self.proc = subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={profile}", "--window-size=1600,960",
                                      "--no-first-run", "--no-default-browser-check", "--disable-features=Translate"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def set_title(self, t):                                     # the page's <title> is the window title
        pass

    def close(self):
        try:
            self.proc.terminate()
        except Exception:
            pass

    def run(self):
        self.proc.wait()


def find_app_browser():
    names = ["chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "brave-browser", "microsoft-edge",
             "microsoft-edge-stable", "msedge", "chrome"]
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    cands = []
    if platform.system() == "Windows":
        for base in (os.environ.get("PROGRAMFILES(X86)", ""), os.environ.get("PROGRAMFILES", ""), os.environ.get("LOCALAPPDATA", "")):
            cands += [Path(base) / "Microsoft/Edge/Application/msedge.exe", Path(base) / "Google/Chrome/Application/chrome.exe"]
    elif platform.system() == "Darwin":
        cands += [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                  Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
                  Path("/Applications/Chromium.app/Contents/MacOS/Chromium")]
    for c in cands:
        if c.exists():
            return str(c)
    return None


# ---------------------------------------------------------------- pywebview, privately installed
def runtime_python():
    return RUNTIME / ("Scripts/python.exe" if platform.system() == "Windows" else "bin/python")


def webview_package():
    """What to install: on Linux the Qt backend comes from pip (GTK WebKit would need system packages)."""
    if platform.system() == "Linux":
        try:
            import gi  # noqa: F401
            gi.require_version("WebKit2", "4.1")
            return ["pywebview"]
        except Exception:
            return ["pywebview[qt]"]
    return ["pywebview"]


def setup_runtime(quiet=False):
    """Make .runtime/ (a venv that can still see this Python's packages) and install pywebview into it."""
    if not runtime_python().exists():
        print("Setting up the game window (one time): creating .runtime/ ...")
        try:
            venv.EnvBuilder(with_pip=True, system_site_packages=True).create(RUNTIME)
        except Exception as e:                                      # Debian/Ubuntu without python3-venv
            print(f"Could not create .runtime/ ({e}).")
            if platform.system() == "Linux":
                print("On Debian/Ubuntu: sudo apt install python3-venv   (then run ./play.sh again)")
            shutil.rmtree(RUNTIME, ignore_errors=True)
            return False
    pkgs = webview_package()
    print(f"Installing {', '.join(pkgs)} into .runtime/ (this is the only download; it can take a minute) ...")
    r = subprocess.run([str(runtime_python()), "-m", "pip", "install", "--disable-pip-version-check", *(["-q"] if quiet else []), *pkgs])
    return r.returncode == 0


def try_webview():
    try:
        import webview
        return webview
    except Exception:
        return None


def ask(prompt):
    if not sys.stdin or not sys.stdin.isatty():
        return False
    try:
        return input(prompt).strip().lower() in ("", "y", "yes")
    except EOFError:
        return False


# ---------------------------------------------------------------- main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db", nargs="?")
    ap.add_argument("--env", default="auto", help="league environment json (auto: save/env_2025.json or data/env_default.json)")
    ap.add_argument("--saves")
    ap.add_argument("--template", help="a built world, copied for each new game (auto: save/world.db, built on first run)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--setup", action="store_true", help="install the native window support and exit")
    ap.add_argument("--no-window", action="store_true", help="use a browser app window instead of a native one")
    a = ap.parse_args(argv)
    from .bootstrap import resolve
    a.template, a.env = resolve(a.template, a.env)
    if a.setup:
        sys.exit(0 if setup_runtime() else 1)

    webview = None if a.no_window else try_webview()
    marker = ROOT / ".runtime-declined"
    in_runtime = Path(sys.prefix).resolve() == RUNTIME.resolve()
    if webview is None and not a.no_window and not in_runtime:
        if runtime_python().exists():                              # installed earlier: restart from there
            os.execv(str(runtime_python()), [str(runtime_python()), "-m", "hs.app", *(argv if argv is not None else sys.argv[1:])])
        if not marker.exists():
            if ask("Hockey Manager runs in its own window. Install the window support now (pywebview, ~1 minute)? [Y/n] "):
                if setup_runtime():
                    os.execv(str(runtime_python()), [str(runtime_python()), "-m", "hs.app", *(argv if argv is not None else sys.argv[1:])])
                print("That did not work; using a browser window instead. Try again later with: python -m hs.app --setup ...")
            else:
                marker.write_text("delete this file to be asked again\n")

    httpd, url, game = make_server(a.db, json.load(open(a.env)), a.port, a.saves, a.template)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    store = Path(a.saves or ".").resolve() / ".window"
    store.mkdir(parents=True, exist_ok=True)

    if webview is not None:
        win = NativeWindow(webview, url, store)
        kind = "native window"
    else:
        exe = find_app_browser()
        if exe:
            win = AppWindow(exe, url, store / "browser")
            kind = f"app window ({Path(exe).name})"
        else:
            import webbrowser
            webbrowser.open(url)
            win = None
            kind = "your browser"
    game.desktop = win
    print(f"{TITLE} is open in a {kind} ({url}). Close the window (or File > Exit) to stop.")
    try:
        if win is not None:
            win.run()
        else:
            while True:
                time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        game.desktop = None
        try:
            if game.sim.running:
                game.sim.stop()
            if game.cli is not None:
                game.cli.conn.commit()
        except Exception:
            pass
        httpd.shutdown()


if __name__ == "__main__":
    main()
