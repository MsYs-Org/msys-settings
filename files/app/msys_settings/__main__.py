"""Application lifecycle entrypoint."""

from __future__ import annotations

from .client import SettingsClient
from .ipc import ComponentChannel, MipcError, PublicMipcClient
from .model import SettingsModel
from .ui import SettingsApplication


def main() -> int:
    channel = ComponentChannel.from_env()
    rpc = channel if channel is not None else PublicMipcClient()
    app = SettingsApplication(
        SettingsModel(SettingsClient(rpc)),
        defer_initial_refresh=channel is not None,
    )
    try:
        if channel is not None:
            channel.handshake(SettingsApplication.EVENT_TOPICS)
            channel.start(app.post_event)
            app.start_initial_refresh()
        else:
            app.set_status(app.tr("status.standalone"))
        app.run()
        return 0
    except MipcError as exc:
        app.set_status(str(exc), error=True)
        app.run()
        return 1
    finally:
        if channel is not None:
            channel.close()


if __name__ == "__main__":
    raise SystemExit(main())
