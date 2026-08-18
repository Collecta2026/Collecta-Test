"""Launcher. On a workstation it opens the browser and serves on localhost.
On a server, set HOST=0.0.0.0 (and PORT) to serve on the network; the browser
is not opened in that case. Uses waitress (falls back to Flask's server)."""
import os
import threading
import webbrowser

from app import app

PORT = int(os.environ.get("PORT", "8000"))
HOST = os.environ.get("HOST", "127.0.0.1")
URL = f"http://127.0.0.1:{PORT}"


def _open():
    webbrowser.open(URL)


if __name__ == "__main__":
    local = HOST in ("127.0.0.1", "localhost")
    print("=" * 56)
    print("  Scientific Gate - Credit Control System")
    if local:
        print(f"  Open your browser at:  {URL}")
        print("  (First run: complete the quick setup screen.)")
    else:
        print(f"  Serving on {HOST}:{PORT} - reach it at http://<server-ip>:{PORT}")
    print("  Keep this running. Close the window / Ctrl+C to stop.")
    print("=" * 56)
    if local:
        threading.Timer(1.5, _open).start()
    try:
        from waitress import serve
        serve(app, host=HOST, port=PORT)
    except ImportError:
        app.run(host=HOST, port=PORT)
