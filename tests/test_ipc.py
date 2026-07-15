from __future__ import annotations

import json
import socket
import threading
import unittest
from pathlib import Path

from msys_settings.ipc import ComponentChannel, MipcRemoteError, PublicMipcClient


class PublicMipcClientTests(unittest.TestCase):
    def test_call_builds_deadline_and_unwraps_payload(self) -> None:
        seen: list[tuple[Path, dict, float]] = []

        def exchange(path: Path, request: dict, timeout: float) -> dict:
            seen.append((path, request, timeout))
            return {"type": "return", "id": request["id"], "payload": {"ok": True}}

        client = PublicMipcClient("/tmp/example", exchange=exchange)
        result = client.call(
            "msys.core", "list_roles", {}, timeout=2.0, idempotent=True
        )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(seen[0][0], Path("/tmp/example/control.sock"))
        self.assertEqual(seen[0][1]["target"], "msys.core")
        self.assertTrue(seen[0][1]["idempotent"])
        self.assertGreater(seen[0][1]["deadline_ms"], 0)

    def test_remote_error_preserves_code_and_payload(self) -> None:
        def exchange(_path: Path, request: dict, _timeout: float) -> dict:
            return {
                "type": "error",
                "id": request["id"],
                "code": "NO_PROVIDER",
                "message": "HAL is not installed",
                "payload": {"interface": "org.msys.hal.manager.v1"},
            }

        with self.assertRaises(MipcRemoteError) as caught:
            PublicMipcClient(exchange=exchange).call(
                "interface:org.msys.hal.manager.v1", "inventory"
            )
        self.assertEqual(caught.exception.code, "NO_PROVIDER")
        self.assertEqual(caught.exception.payload["interface"], "org.msys.hal.manager.v1")

    def test_broadcast_uses_core_contract(self) -> None:
        requests: list[dict] = []

        def exchange(_path: Path, request: dict, _timeout: float) -> dict:
            requests.append(request)
            return {"type": "return", "id": request["id"], "payload": {"ok": True}}

        PublicMipcClient(exchange=exchange).broadcast("msys.update.check", {"source": "index.json"})
        request = requests[0]
        self.assertEqual(request["target"], "msys.core")
        self.assertEqual(request["method"], "broadcast")
        self.assertEqual(request["payload"]["topic"], "msys.update.check")


@unittest.skipUnless(hasattr(socket, "SOCK_SEQPACKET"), "SOCK_SEQPACKET unavailable")
class ComponentChannelTests(unittest.TestCase):
    def test_private_inbound_navigation_call_returns_handler_result(self) -> None:
        app_socket, daemon_socket = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        channel = ComponentChannel(app_socket, "org.msys.settings:main", 8)
        channel.start(
            lambda _message: None,
            call_handler=lambda message: {
                "handled": message.get("method") == "navigation_back",
                "page": "home",
            },
        )
        daemon_socket.send(json.dumps({
            "type": "call",
            "id": 42,
            "target": "org.msys.settings:main",
            "method": "navigation_back",
            "payload": {},
        }).encode("utf-8"))
        response = json.loads(daemon_socket.recv(65536).decode("utf-8"))
        channel.close()
        daemon_socket.close()

        self.assertEqual(response, {
            "type": "return",
            "id": 42,
            "payload": {"handled": True, "page": "home"},
        })

    def test_inbound_handler_can_make_nested_core_call_without_reader_deadlock(self) -> None:
        app_socket, daemon_socket = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        channel = ComponentChannel(app_socket, "org.msys.settings:main", 9)

        def handler(_message: dict) -> dict:
            return channel.call(
                "msys.core",
                "set_session_preferences",
                {"language": "zh-CN"},
                timeout=1,
            )

        channel.start(lambda _message: None, call_handler=handler)
        daemon_socket.send(json.dumps({
            "type": "call",
            "id": 43,
            "target": "org.msys.settings:main",
            "method": "set_language",
            "payload": {"language": "zh-CN"},
        }).encode("utf-8"))
        nested = json.loads(daemon_socket.recv(65536).decode("utf-8"))
        self.assertEqual(nested["target"], "msys.core")
        self.assertEqual(nested["method"], "set_session_preferences")
        daemon_socket.send(json.dumps({
            "type": "return",
            "id": nested["id"],
            "payload": {"ok": True, "language": "zh-CN"},
        }).encode("utf-8"))
        response = json.loads(daemon_socket.recv(65536).decode("utf-8"))
        channel.close()
        daemon_socket.close()

        self.assertEqual(response, {
            "type": "return",
            "id": 43,
            "payload": {"ok": True, "language": "zh-CN"},
        })

    def test_private_rpc_preserves_events_and_manifest_identity(self) -> None:
        app_socket, daemon_socket = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        channel = ComponentChannel(app_socket, "org.msys.settings:main", 8)
        events: list[dict] = []
        channel.start(events.append)
        replies: list[dict] = []

        caller = threading.Thread(
            target=lambda: replies.append(
                channel.call(
                    "role:install-agent",
                    "registry",
                    {},
                    timeout=1,
                    idempotent=True,
                )
            )
        )
        caller.start()
        request = json.loads(daemon_socket.recv(65536).decode("utf-8"))
        daemon_socket.send(
            b'{"type":"event","topic":"msys.install.package_changed","payload":{}}'
        )
        daemon_socket.send(
            json.dumps(
                {
                    "type": "return",
                    "id": request["id"],
                    "payload": {"schema": "msys.installed.v1", "packages": []},
                }
            ).encode("utf-8")
        )
        caller.join(timeout=2)
        channel.close()
        daemon_socket.close()

        self.assertFalse(caller.is_alive())
        self.assertEqual(replies[0]["schema"], "msys.installed.v1")
        self.assertEqual(events[0]["topic"], "msys.install.package_changed")
        self.assertEqual(request["target"], "role:install-agent")
        self.assertTrue(request["idempotent"])

    def test_private_rpc_remote_acl_error_is_typed(self) -> None:
        app_socket, daemon_socket = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        channel = ComponentChannel(app_socket, "org.msys.settings:main", 1)
        channel.start(lambda _message: None)

        def daemon() -> None:
            request = json.loads(daemon_socket.recv(65536).decode("utf-8"))
            daemon_socket.send(
                json.dumps(
                    {
                        "type": "error",
                        "id": request["id"],
                        "code": "ACCESS_DENIED",
                        "message": "permission missing",
                        "payload": {"operation": "call"},
                    }
                ).encode("utf-8")
            )

        server = threading.Thread(target=daemon)
        server.start()
        with self.assertRaises(MipcRemoteError) as caught:
            channel.call("msys.core", "select_role", timeout=1)
        channel.close()
        daemon_socket.close()
        server.join(timeout=1)
        self.assertEqual(caught.exception.code, "ACCESS_DENIED")


if __name__ == "__main__":
    unittest.main()
