"""Echo (ἠχώ): keeps an iMessage thread whole when you answer it from Hermes Desktop.

A Photon (iMessage) conversation can be opened and continued in Hermes Desktop.  A turn made there is saved
in the conversation, but nothing reaches the phone.  After such a turn this plugin posts both halves to the
iMessage thread the conversation belongs to: your message under a short header, then her reply as a normal
message from her, the way a reply to a message from the phone is sent.

Only turns made in Desktop are echoed: a turn that came in from the phone runs in the messaging gateway, which
binds the conversation's platform and chat to the turn, and is skipped.  The messages go straight to the
gateway's Photon sidecar, not through ``hermes send``, which would also copy them into the conversation a
second time.

Only the standard library is imported at load: Hermes executes every top-level module in this folder.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

__version__ = "0.1.0"

logger = logging.getLogger(__name__)

DEFAULTS: Dict[str, Any] = {"enabled": True, "header": "💻 You, on Desktop:", "echo_reply": True}
MAX_MESSAGE_LENGTH = 8000          # what the Photon adapter itself sends at most per message
SIDECAR_RECORD = Path("runtime") / "photon-sidecar.json"
MAX_PARENT_HOPS = 8


def _hermes_home() -> Path:
    from hermes_constants import get_hermes_home
    return Path(get_hermes_home())


def _session_env(name: str) -> str:
    try:
        from gateway.session_context import get_session_env
        return get_session_env(name, "") or ""
    except Exception:
        return os.environ.get(name, "")


def turn_came_from_messaging() -> bool:
    """The gateway binds the platform and chat of every turn it runs; Desktop binds neither."""
    return bool(_session_env("HERMES_SESSION_PLATFORM") or _session_env("HERMES_SESSION_CHAT_ID"))


def photon_chat_for(session_id: str, lookup=None) -> Optional[str]:
    """The iMessage chat a conversation belongs to: its own row if it is a Photon session, else the nearest
    ancestor that is (a conversation continued in Desktop may be a child of the Photon one)."""
    lookup = lookup or _lookup_session
    seen = set()
    current = session_id
    for _ in range(MAX_PARENT_HOPS):
        if not current or current in seen:
            return None
        seen.add(current)
        row = lookup(current) or {}
        if str(row.get("source") or "").lower() == "photon" and row.get("chat_id"):
            return str(row["chat_id"])
        current = row.get("parent_session_id")
    return None


def _lookup_session(session_id: str) -> Optional[Dict[str, Any]]:
    from hermes_state_registry import acquire, release_or_close
    db = acquire()
    try:
        return db.get_session(session_id)
    finally:
        release_or_close(db)


def _sidecar() -> Tuple[int, str]:
    record = json.loads((_hermes_home() / SIDECAR_RECORD).read_text(encoding="utf-8"))
    return int(record["port"]), str(record["token"])


def _markdown_enabled() -> bool:
    return str(os.environ.get("PHOTON_MARKDOWN", "true")).strip().lower() not in ("0", "false", "no", "off")


def send_to_thread(space_id: str, text: str, *, sidecar=None, opener=None) -> bool:
    """POST one message to the gateway's Photon sidecar, as the adapter does.  False (logged) on any failure:
    the gateway may be stopped, and an echo must never disturb the turn."""
    text = (text or "").strip()
    if not text:
        return False
    try:
        port, token = (sidecar or _sidecar)()
    except (OSError, ValueError, KeyError) as exc:
        logger.info("echo: no running Photon sidecar to post through (%s); is the gateway running?", exc)
        return False
    body: Dict[str, Any] = {"spaceId": space_id, "text": text[:MAX_MESSAGE_LENGTH]}
    if _markdown_enabled():
        body["format"] = "markdown"
    req = urllib.request.Request(f"http://127.0.0.1:{port}/send", json.dumps(body).encode("utf-8"),
                                 {"Content-Type": "application/json", "X-Hermes-Sidecar-Token": token})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=30) as resp:
            ok = bool(json.loads(resp.read() or b"{}").get("ok"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        logger.warning("echo: posting to the iMessage thread failed: %s", exc)
        return False
    if not ok:
        logger.warning("echo: the Photon sidecar did not accept the message")
    return ok


class Echo:
    def __init__(self, settings=None, chat_for=None, sender=None, from_messaging=None, run=None) -> None:
        self.settings = settings or (lambda: dict(DEFAULTS))
        self.chat_for = chat_for or photon_chat_for
        self.sender = sender or send_to_thread
        self.from_messaging = from_messaging or turn_came_from_messaging
        self.run = run or (lambda fn: threading.Thread(target=fn, name="echo", daemon=True).start())

    def after_turn(self, session_id: str = "", user_message: Any = "", assistant_response: Any = "",
                   **_: Any) -> None:
        cfg = dict(DEFAULTS, **(self.settings() or {}))
        if not cfg["enabled"] or self.from_messaging():
            return
        mine = _text(user_message)
        reply = _text(assistant_response)
        if not (mine or reply):
            return
        try:
            space = self.chat_for(str(session_id or ""))
        except Exception as exc:                 # the session store must never fail the turn
            logger.debug("echo: session lookup failed: %s", exc)
            return
        if not space:
            return
        header = str(cfg.get("header") or "").strip()

        def deliver() -> None:
            if mine:
                self.sender(space, f"{header}\n{mine}" if header else mine)
            if reply and cfg["echo_reply"]:
                self.sender(space, reply)

        self.run(deliver)


def _text(value: Any) -> str:
    """The text of a message, whether a string or a list of content parts."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(str(p.get("text") or "") for p in value if isinstance(p, dict) and p.get("type") == "text").strip()
    return ""


def register(ctx) -> None:
    def settings() -> Dict[str, Any]:
        out = {}
        for key in DEFAULTS:
            try:
                value = ctx.get_config(key)
            except Exception:
                value = None
            if value is not None:
                out[key] = value
        return out

    echo = Echo(settings=settings)
    ctx.register_hook("post_llm_call", echo.after_turn)
