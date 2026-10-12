"""本机出网代理。

沙箱保持 ``--unshare-net``。进程里的转发器只把流量送到这个 Unix 套接字，
由宿主机代理决定能不能连出去：包注册表和 GitHub 的只读访问直接放行，
其它域名第一次拒绝并记审计，用户批准后才放行。评测模式不启动代理。
"""

from __future__ import annotations

import os
import select
import socket
import threading
from pathlib import Path
from urllib.parse import urlsplit

_DIR: Path | None = None
_THREAD: threading.Thread | None = None
_LOCK = threading.Lock()
_GRANTED: set[str] = set()
_DENIED: list[str] = []

_RELAY = """\
import socket, threading
UNIX = "/egress/egress.sock"

def _pipe(src, dst):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except Exception:
        pass

def _handle(client):
    remote = None
    try:
        remote = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        remote.connect(UNIX)
        left = threading.Thread(target=_pipe, args=(client, remote), daemon=True)
        right = threading.Thread(target=_pipe, args=(remote, client), daemon=True)
        left.start()
        right.start()
        left.join()
        right.join()
    except Exception:
        pass
    finally:
        client.close()
        if remote is not None:
            remote.close()

def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 3128))
    srv.listen(64)
    while True:
        conn, _addr = srv.accept()
        threading.Thread(target=_handle, args=(conn,), daemon=True).start()

if __name__ == "__main__":
    main()
"""


def proxy_dir() -> Path | None:
    """确保代理在听 Unix 套接字，返回挂进沙箱的目录。失败时返回 None。"""
    global _DIR, _THREAD
    with _LOCK:
        if _DIR is not None and (_DIR / "egress.sock").exists():
            return _DIR
        try:
            root = Path(os.environ.get("TMPDIR") or "/tmp") / "agent-egress"
            root.mkdir(parents=True, exist_ok=True)
            sock_path = root / "egress.sock"
            if sock_path.exists():
                sock_path.unlink()
            (root / "relay.py").write_text(_RELAY, encoding="utf-8")
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(sock_path))
            server.listen(64)
            os.chmod(sock_path, 0o666)
        except OSError:
            return None
        _DIR = root
        _THREAD = threading.Thread(target=_serve, args=(server,), name="egress-proxy", daemon=True)
        _THREAD.start()
        return _DIR


def grant_hosts(hosts: list[str]) -> None:
    with _LOCK:
        for host in hosts:
            name = _host_name(host)
            if name:
                _GRANTED.add(name)


def host_granted(host: str) -> bool:
    name = _host_name(host)
    with _LOCK:
        return bool(name) and name in _GRANTED


def drain_denied() -> list[str]:
    with _LOCK:
        found = list(dict.fromkeys(_DENIED))
        _DENIED.clear()
        return found


def wrap_shell(command: str) -> str:
    """在用户命令前拉起沙箱内的本地转发，并让常见工具走它。"""
    return (
        "python3 /egress/relay.py >/tmp/egress-relay.log 2>&1 & "
        "sleep 0.05; "
        "export http_proxy=http://127.0.0.1:3128 https_proxy=http://127.0.0.1:3128 "
        "HTTP_PROXY=http://127.0.0.1:3128 HTTPS_PROXY=http://127.0.0.1:3128 "
        "ALL_PROXY=http://127.0.0.1:3128 no_proxy=127.0.0.1,localhost "
        "GOPROXY=https://proxy.golang.org; "
        + command
    )


def _serve(server: socket.socket) -> None:
    while True:
        try:
            client, _addr = server.accept()
        except OSError:
            return
        threading.Thread(target=_handle_client, args=(client,), daemon=True).start()


def _handle_client(client: socket.socket) -> None:
    remote = None
    try:
        client.settimeout(15)
        header = b""
        while b"\r\n\r\n" not in header and len(header) < 65536:
            piece = client.recv(4096)
            if not piece:
                return
            header += piece
        head, _, rest = header.partition(b"\r\n\r\n")
        line = head.split(b"\r\n", 1)[0].decode("latin-1", errors="replace")
        parts = line.split()
        if len(parts) < 2:
            _reject(client, "")
            return
        method, target = parts[0].upper(), parts[1]
        host, port = _split_target(method, target)
        if not host or _verdict(host, port, method) != "allow":
            _reject(client, host)
            return
        remote = socket.create_connection((host, port), timeout=15)
        remote.settimeout(None)
        client.settimeout(None)
        if method == "CONNECT":
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        else:
            remote.sendall(head + b"\r\n\r\n" + rest)
            rest = b""
        if rest and method == "CONNECT":
            remote.sendall(rest)
        _splice(client, remote)
    except OSError:
        try:
            _reject(client, "")
        except OSError:
            return
    finally:
        client.close()
        if remote is not None:
            remote.close()


def _reject(client: socket.socket, host: str) -> None:
    name = _host_name(host) or "unknown"
    if name != "unknown":
        with _LOCK:
            if name not in _DENIED:
                _DENIED.append(name)
                del _DENIED[:-40]
    body = f"EGRESS_APPROVAL_REQUIRED host={name}\n".encode()
    client.sendall(
        b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/plain\r\nContent-Length: "
        + str(len(body)).encode()
        + b"\r\nConnection: close\r\n\r\n"
        + body
    )


def _verdict(host: str, port: int, method: str) -> str:
    from app.policy.egress import _registry_host, resolve_blocked
    from app.policy.egress_audit import note_egress_host

    name = _host_name(host)
    if not name or port not in {80, 443}:
        return "deny"
    if resolve_blocked(name):
        note_egress_host(name, "deny")
        return "deny"
    allowed_method = method in {"CONNECT", "GET", "HEAD"}
    if _registry_host(name) or host_granted(name):
        if not allowed_method:
            note_egress_host(name, "require_approval")
            return "deny"
        note_egress_host(name, "allow")
        return "allow"
    note_egress_host(name, "require_approval")
    return "deny"


def _split_target(method: str, target: str) -> tuple[str, int]:
    if method == "CONNECT":
        host, _, port = target.partition(":")
        try:
            return host, int(port or "443")
        except ValueError:
            return host, 0
    parsed = urlsplit(target)
    if not parsed.hostname:
        return "", 0
    return parsed.hostname, int(parsed.port or (443 if parsed.scheme == "https" else 80))


def _host_name(host: str) -> str:
    return (host or "").strip().lower().rstrip(".")


def _splice(left: socket.socket, right: socket.socket) -> None:
    pair = [left, right]
    while pair:
        ready, _, _ = select.select(pair, [], [], 30)
        if not ready:
            return
        for sock in ready:
            other = right if sock is left else left
            data = sock.recv(65536)
            if not data:
                return
            other.sendall(data)
