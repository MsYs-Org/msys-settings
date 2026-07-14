"""Small, zero-dependency mIPC transport used by the Settings application."""

from __future__ import annotations

import json
import os
import queue
import socket
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable

MAX_PACKET = 256 * 1024


class MipcError(RuntimeError):
    """Base error for a local transport or remote mIPC failure."""


class MipcUnavailable(MipcError):
    """The selected MSYS control transport is unavailable."""


class MipcRemoteError(MipcError):
    """An mIPC provider returned a structured error."""

    def __init__(
        self,
        code: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.code = code or "REMOTE_ERROR"
        self.message = message or self.code
        self.payload = payload or {}
        super().__init__(f"{self.code}: {self.message}")


def _json_bytes(message: dict[str, Any], *, newline: bool) -> bytes:
    encoded = json.dumps(
        message,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_PACKET:
        raise MipcError("mIPC packet exceeds the 256 KiB limit")
    return encoded + (b"\n" if newline else b"")


def _recv_line(sock: socket.socket, timeout: float) -> dict[str, Any]:
    sock.settimeout(timeout)
    data = bytearray()
    while True:
        chunk = sock.recv(min(65536, MAX_PACKET + 1 - len(data)))
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > MAX_PACKET:
            raise MipcError("mIPC response exceeds the 256 KiB limit")
        newline = data.find(b"\n")
        if newline >= 0:
            del data[newline:]
            break
    if not data:
        raise MipcError("empty mIPC response")
    try:
        decoded = json.loads(bytes(data).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MipcError(f"invalid mIPC JSON response: {exc}") from exc
    if not isinstance(decoded, dict):
        raise MipcError("mIPC response must be a JSON object")
    return decoded


Exchange = Callable[[Path, dict[str, Any], float], dict[str, Any]]


def _socket_exchange(
    socket_path: Path,
    request: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(str(socket_path))
            welcome = _recv_line(sock, timeout)
            if welcome.get("type") != "welcome":
                raise MipcError("public control socket did not send a welcome packet")
            sock.sendall(_json_bytes(request, newline=True))
            return _recv_line(sock, timeout)
    except MipcError:
        raise
    except (FileNotFoundError, ConnectionRefusedError, TimeoutError, OSError) as exc:
        raise MipcUnavailable(f"cannot connect to {socket_path}: {exc}") from exc


class PublicMipcClient:
    """One-request-per-connection client for ``control.sock``.

    This is the explicit standalone/operator fallback. Installed Settings uses
    :class:`ComponentChannel`, so its manifest identity and ACL are preserved.
    """

    def __init__(
        self,
        runtime_dir: str | os.PathLike[str] | None = None,
        *,
        default_timeout: float = 5.0,
        exchange: Exchange | None = None,
    ) -> None:
        selected = runtime_dir or os.environ.get("MSYS_RUNTIME_DIR", "/run/msys/main")
        self.socket_path = Path(selected) / "control.sock"
        self.default_timeout = float(default_timeout)
        self._exchange = exchange or _socket_exchange
        self._request_lock = threading.Lock()
        self._next_id = 1

    def call(
        self,
        target: str,
        method: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        idempotent: bool = False,
    ) -> dict[str, Any]:
        if not target or not method:
            raise ValueError("mIPC target and method are required")
        call_timeout = self.default_timeout if timeout is None else float(timeout)
        if call_timeout <= 0:
            raise ValueError("mIPC timeout must be positive")
        with self._request_lock:
            request_id = self._next_id
            self._next_id += 1
        request = {
            "type": "call",
            "id": request_id,
            "target": target,
            "method": method,
            "payload": payload or {},
            "deadline_ms": int(time.monotonic() * 1000 + call_timeout * 1000),
            "idempotent": bool(idempotent),
        }
        response = self._exchange(self.socket_path, request, call_timeout)
        if response.get("id") != request_id:
            raise MipcError(
                f"mIPC response id mismatch: expected {request_id}, got {response.get('id')!r}"
            )
        response_type = response.get("type")
        if response_type == "error":
            raw_payload = response.get("payload")
            raise MipcRemoteError(
                str(response.get("code", "REMOTE_ERROR")),
                str(response.get("message", "mIPC call failed")),
                raw_payload if isinstance(raw_payload, dict) else None,
            )
        if response_type != "return":
            raise MipcError(f"unexpected mIPC response type: {response_type!r}")
        raw_payload = response.get("payload", {})
        if raw_payload is None:
            return {}
        if not isinstance(raw_payload, dict):
            return {"value": raw_payload}
        return raw_payload

    def broadcast(
        self,
        topic: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        return self.call(
            "msys.core",
            "broadcast",
            {"topic": topic, "payload": payload or {}},
            timeout=timeout,
        )


class ComponentChannel:
    """Authenticated component channel with one reader and concurrent RPC."""

    def __init__(self, sock: socket.socket, component_id: str, generation: int) -> None:
        self.sock = sock
        self.component_id = component_id
        self.generation = generation
        self._send_lock = threading.Lock()
        self._closed = threading.Event()
        self._pending_lock = threading.Lock()
        self._next_id = 1
        self._pending: dict[int, queue.Queue[dict[str, Any] | BaseException]] = {}
        self._pump_lock = threading.Lock()
        self._pump_thread: threading.Thread | None = None

    @classmethod
    def from_env(cls) -> "ComponentChannel | None":
        raw_fd = os.environ.get("MSYS_CONTROL_FD")
        if not raw_fd:
            return None
        try:
            fd = int(raw_fd)
            generation = int(os.environ.get("MSYS_GENERATION", "0"))
        except ValueError as exc:
            raise MipcError("invalid inherited mIPC descriptor metadata") from exc
        return cls(
            socket.socket(fileno=fd),
            os.environ.get("MSYS_COMPONENT_ID", "org.msys.settings:main"),
            generation,
        )

    def send(self, message: dict[str, Any]) -> None:
        packet = _json_bytes(message, newline=False)
        with self._send_lock:
            self.sock.sendall(packet)

    def recv(self, timeout: float | None = None) -> dict[str, Any] | None:
        self.sock.settimeout(timeout)
        try:
            packet = self.sock.recv(MAX_PACKET + 1)
        except socket.timeout:
            return None
        if not packet:
            return {"type": "eof"}
        if len(packet) > MAX_PACKET:
            raise MipcError("component mIPC packet exceeds the 256 KiB limit")
        try:
            message = json.loads(packet.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MipcError(f"invalid component mIPC packet: {exc}") from exc
        if not isinstance(message, dict):
            raise MipcError("component mIPC packet must be an object")
        return message

    def handshake(self, subscriptions: Iterable[str] = ()) -> dict[str, Any]:
        self.send(
            {
                "type": "hello",
                "component": self.component_id,
                "generation": self.generation,
            }
        )
        welcome = self.recv(timeout=3.0)
        if not welcome or welcome.get("type") != "welcome":
            raise MipcError("msysd did not accept the component handshake")
        for topic in subscriptions:
            self.send({"type": "subscribe", "topic": topic})
        self.send({"type": "ready"})
        return welcome

    def call(
        self,
        target: str,
        method: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        idempotent: bool = False,
    ) -> dict[str, Any]:
        if not target or not method:
            raise ValueError("mIPC target and method are required")
        if payload is not None and not isinstance(payload, dict):
            raise ValueError("mIPC payload must be an object")
        call_timeout = 5.0 if timeout is None else float(timeout)
        if call_timeout <= 0:
            raise ValueError("mIPC timeout must be positive")
        if self._pump_thread is None:
            raise MipcError("component mIPC reader is not running")
        waiter: queue.Queue[dict[str, Any] | BaseException] = queue.Queue(maxsize=1)
        with self._pending_lock:
            if self._closed.is_set():
                raise MipcUnavailable("component mIPC channel is closed")
            request_id = self._next_id
            self._next_id += 1
            self._pending[request_id] = waiter
        try:
            self.send(
                {
                    "type": "call",
                    "id": request_id,
                    "target": target,
                    "method": method,
                    "payload": payload or {},
                    "deadline_ms": int(
                        time.monotonic() * 1000 + call_timeout * 1000
                    ),
                    "idempotent": bool(idempotent),
                }
            )
            try:
                response = waiter.get(timeout=call_timeout)
            except queue.Empty:
                raise MipcUnavailable(
                    f"mIPC call timed out: {target}.{method}"
                ) from None
            if isinstance(response, BaseException):
                raise response
            if response.get("type") == "error":
                raw_payload = response.get("payload")
                raise MipcRemoteError(
                    str(response.get("code", "REMOTE_ERROR")),
                    str(response.get("message", "mIPC call failed")),
                    raw_payload if isinstance(raw_payload, dict) else None,
                )
            if response.get("type") != "return":
                raise MipcError(
                    f"unexpected mIPC response type: {response.get('type')!r}"
                )
            raw_payload = response.get("payload", {})
            if raw_payload is None:
                return {}
            return (
                raw_payload
                if isinstance(raw_payload, dict)
                else {"value": raw_payload}
            )
        finally:
            with self._pending_lock:
                if self._pending.get(request_id) is waiter:
                    del self._pending[request_id]

    def start(self, callback: Callable[[dict[str, Any]], None]) -> None:
        with self._pump_lock:
            if self._pump_thread is not None:
                raise MipcError("component mIPC reader is already running")
            thread = threading.Thread(
                target=self.pump,
                args=(callback,),
                name=f"settings-mipc:{self.component_id}",
                daemon=True,
            )
            self._pump_thread = thread
            thread.start()

    def _fail_pending(self, error: BaseException) -> None:
        with self._pending_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for waiter in pending:
            try:
                waiter.put_nowait(error)
            except queue.Full:
                pass

    def pump(self, callback: Callable[[dict[str, Any]], None]) -> None:
        while not self._closed.is_set():
            try:
                message = self.recv(timeout=1.0)
            except (MipcError, OSError) as exc:
                self._fail_pending(MipcUnavailable(str(exc)))
                return
            if message is None:
                continue
            if message.get("type") in {"eof", "shutdown"}:
                self._fail_pending(MipcUnavailable("component mIPC channel closed"))
                return
            request_id = message.get("id")
            if (
                message.get("type") in {"return", "error"}
                and isinstance(request_id, int)
                and not isinstance(request_id, bool)
            ):
                with self._pending_lock:
                    waiter = self._pending.get(request_id)
                if waiter is not None:
                    try:
                        waiter.put_nowait(message)
                    except queue.Full:
                        pass
                    continue
            if message.get("type") == "event":
                callback(message)

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        self._fail_pending(MipcUnavailable("component mIPC channel closed"))
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()
