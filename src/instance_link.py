"""Hands a request from VS Code over to an ADT Flutter Tools that already runs.

Every running app listens on a local socket and records its port in
~/.cache/adt_flutter_tools/instance.json (the latest started app wins). The VS Code
button starts `main.py --from-editor --project <folder>`; that process forwards the
folder here and exits, so the open window switches project instead of a second
window opening. Only stdlib imports: forwarding must not wait for Tkinter.
"""

import json
import os
import secrets
import socket
import threading

STATE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "adt_flutter_tools")
STATE_FILE = os.path.join(STATE_DIR, "instance.json")
_MAX_REQUEST_BYTES = 64 * 1024


def forward(request):
    """Sends [request] to the running app. False when no app answers (then start a new one)."""
    try:
        with open(STATE_FILE, encoding="utf-8") as file:
            state = json.load(file)
        with socket.create_connection(("127.0.0.1", int(state["port"])), timeout=1) as connection:
            connection.sendall((json.dumps({"token": state["token"], **request}) + "\n").encode("utf-8"))
            connection.settimeout(3)
            return connection.recv(16).startswith(b"ok")
    except (OSError, ValueError, KeyError, TypeError):
        return False


def listen(on_request):
    """
    Accepts requests from forward() and passes each one (a dict) to [on_request]
    on a background thread. Returns a function that stops listening.
    """
    token = secrets.token_hex(16)
    try:
        server = socket.create_server(("127.0.0.1", 0))
        port = server.getsockname()[1]
        os.makedirs(STATE_DIR, exist_ok=True)
        # The token keeps other local programs from driving the app; only the owner can read it.
        descriptor = os.open(STATE_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump({"port": port, "token": token, "pid": os.getpid()}, file)
    except OSError as error:
        print(f"--- VS Code propojení nedostupné: {error} ---")
        return lambda: None

    def serve():
        while True:
            try:
                connection, _ = server.accept()
            except OSError:
                return  # server closed
            with connection:
                try:
                    connection.settimeout(2)
                    data = b""
                    while not data.endswith(b"\n") and len(data) < _MAX_REQUEST_BYTES:
                        chunk = connection.recv(4096)
                        if not chunk:
                            break
                        data += chunk
                    request = json.loads(data.decode("utf-8"))
                    if not isinstance(request, dict) or request.pop("token", None) != token:
                        continue
                    connection.sendall(b"ok\n")
                except (OSError, ValueError):
                    continue
            on_request(request)

    threading.Thread(target=serve, name="instance-link", daemon=True).start()

    def stop():
        server.close()
        try:
            with open(STATE_FILE, encoding="utf-8") as file:
                still_ours = json.load(file).get("port") == port
            if still_ours:
                os.remove(STATE_FILE)
        except (OSError, ValueError):
            pass

    return stop
