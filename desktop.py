"""StemSplitter as a native Mac window (no browser tab).

Starts the FastAPI server in the background (or reuses one already running on the port),
then opens the UI in a pywebview window. Closing the window quits the app and frees RAM.
"""
from __future__ import annotations

import os
import socket
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import webview

PORT = int(os.environ.get("PORT", 7861))
URL = f"http://127.0.0.1:{PORT}"
DOWNLOADS = Path.home() / "Downloads"


def _port_open() -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", PORT)) == 0


def _start_server() -> None:
    """Run the server in this process unless one is already listening."""
    if _port_open():
        return
    import uvicorn
    import server  # noqa: F401  (imports the FastAPI app and loads the library)

    config = uvicorn.Config(server.app, host="127.0.0.1", port=PORT, log_level="warning")
    uvicorn.Server(config).run()


class Api:
    """Methods callable from the page as window.pywebview.api.*"""

    window = None  # set after the window is created

    def save_url(self, path: str) -> str | None:
        """Download a server path (e.g. /api/jobs/.../mix?...) through a native Save dialog."""
        full = URL + path
        with urllib.request.urlopen(full) as r:
            cd = r.headers.get("Content-Disposition", "")
            name = "download"
            if "filename*=utf-8''" in cd:
                name = urllib.parse.unquote(cd.split("filename*=utf-8''", 1)[1].split(";")[0])
            elif 'filename="' in cd:
                name = cd.split('filename="', 1)[1].split('"', 1)[0]
            chosen = self.window.create_file_dialog(
                webview.SAVE_DIALOG, directory=str(DOWNLOADS), save_filename=name)
            if not chosen:
                return None
            target = chosen if isinstance(chosen, str) else chosen[0]
            with open(target, "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
        return target

    def reveal(self, path: str) -> None:
        os.system(f'open -R "{path}"')


def main() -> None:
    threading.Thread(target=_start_server, daemon=True).start()
    for _ in range(120):
        if _port_open():
            break
        time.sleep(0.5)

    api = Api()
    window = webview.create_window(
        "StemSplitter", URL, js_api=api, width=1280, height=860,
        min_size=(900, 640), background_color="#15141c")
    api.window = window
    webview.start(debug=bool(os.environ.get("STEM_DEBUG")))


if __name__ == "__main__":
    main()
