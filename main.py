"""Standalone launcher for Stone of Fist.

This is the entry point used by PyInstaller.

Behaviour:
  - If port 5000 is already in use (another instance is running),
    just open a browser tab to it — no second server is started.
  - Otherwise start Flask, then open the browser once it's ready.
"""
import os
import socket
import threading
import time
import webbrowser

# Mark as local standalone mode before importing app
os.environ["LOCAL_MODE"] = "1"

from app import app

_PORT = 5000
_URL = f"http://127.0.0.1:{_PORT}"


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _open_browser():
    time.sleep(1.2)
    webbrowser.open(_URL)


if __name__ == "__main__":
    if _port_in_use(_PORT):
        # Another instance is already running — just bring it up in the browser
        webbrowser.open(_URL)
    else:
        t = threading.Thread(target=_open_browser, daemon=True)
        t.start()
        app.run(host="127.0.0.1", port=_PORT, debug=False, use_reloader=False)
