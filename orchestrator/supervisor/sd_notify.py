"""Minimal stdlib ``sd_notify`` implementation (ADR-0002 D8).

Writes to the UNIX datagram socket named by the ``NOTIFY_SOCKET`` env
var, per the systemd notify protocol. A no-op when the env var is unset,
which is the common case under pytest and when running the daemon
outside systemd.

We write directly instead of depending on ``systemd-python`` to avoid a
C-extension dependency — the protocol is a single ``sendto`` call on a
UDP-style socket, and the stdlib covers it.
"""

from __future__ import annotations

import os
import socket

import structlog

__all__ = ["sd_notify"]

_log = structlog.get_logger(__name__).bind(component="sd-notify")


def sd_notify(message: str) -> bool:
    """Send ``message`` to systemd's notify socket if one is configured.

    Returns ``True`` when the message was sent, ``False`` when
    ``NOTIFY_SOCKET`` is unset. Socket errors are swallowed and logged
    at WARN — the daemon must not crash because systemd's notify channel
    is unreachable.
    """
    socket_path = os.environ.get("NOTIFY_SOCKET")
    if not socket_path:
        return False

    # Abstract-namespace sockets start with '@' which is mapped to a
    # leading NUL byte in the sockaddr.
    address = "\0" + socket_path[1:] if socket_path.startswith("@") else socket_path

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    except OSError as exc:
        _log.warning("sd_notify.socket", error=str(exc))
        return False
    try:
        sock.sendto(message.encode("utf-8"), address)
    except OSError as exc:
        _log.warning("sd_notify.send", error=str(exc), message=message)
        return False
    finally:
        sock.close()
    return True
