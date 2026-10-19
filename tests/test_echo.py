"""Tests for echo.  Pure Python: the session store, the sidecar and the gateway's turn context are faked."""
import importlib.util
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("echo_plugin", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
echo = importlib.util.module_from_spec(spec)
sys.modules["echo_plugin"] = echo
spec.loader.exec_module(echo)

ROWS = {
    "photon-1": {"source": "photon", "chat_id": "any;-;+13073091327"},
    "desktop-child": {"source": "tui", "parent_session_id": "photon-1"},
    "plain-desktop": {"source": "tui"},
    "loop-a": {"source": "tui", "parent_session_id": "loop-b"},
    "loop-b": {"source": "tui", "parent_session_id": "loop-a"},
}


def make(settings=None, from_messaging=False):
    sent = []
    e = echo.Echo(settings=lambda: settings or {}, chat_for=lambda sid: echo.photon_chat_for(sid, ROWS.get),
                  sender=lambda space, text: sent.append((space, text)) or True,
                  from_messaging=lambda: from_messaging, run=lambda fn: fn())
    return e, sent


def test_a_desktop_turn_in_an_imessage_conversation_reaches_the_thread():
    e, sent = make()
    e.after_turn(session_id="photon-1", user_message="How was your day?", assistant_response="Quiet and good.")
    assert sent == [("any;-;+13073091327", "💻 You, on Desktop:\nHow was your day?"),
                    ("any;-;+13073091327", "Quiet and good.")]


def test_a_conversation_continued_as_a_child_session_still_finds_its_thread():
    e, sent = make()
    e.after_turn(session_id="desktop-child", user_message="hi", assistant_response="hello")
    assert [space for space, _ in sent] == ["any;-;+13073091327"] * 2


def test_turns_from_the_phone_are_never_echoed_back():
    e, sent = make(from_messaging=True)
    e.after_turn(session_id="photon-1", user_message="hi", assistant_response="hello")
    assert sent == []


def test_other_conversations_and_loops_are_left_alone():
    e, sent = make()
    for sid in ("plain-desktop", "loop-a", "missing", ""):
        e.after_turn(session_id=sid, user_message="hi", assistant_response="hello")
    assert sent == []


def test_settings_turn_it_off_change_the_header_or_keep_her_reply_out():
    e, sent = make({"enabled": False})
    e.after_turn(session_id="photon-1", user_message="hi", assistant_response="hello")
    assert sent == []
    e, sent = make({"header": "From the desk:", "echo_reply": False})
    e.after_turn(session_id="photon-1", user_message="hi", assistant_response="hello")
    assert sent == [("any;-;+13073091327", "From the desk:\nhi")]
    e, sent = make({"header": ""})
    e.after_turn(session_id="photon-1", user_message="hi", assistant_response="")
    assert sent == [("any;-;+13073091327", "hi")]


def test_content_parts_are_read_as_text():
    e, sent = make()
    e.after_turn(session_id="photon-1", user_message=[{"type": "text", "text": "look"}, {"type": "image_url"}],
                 assistant_response="I see it.")
    assert sent[0][1].endswith("\nlook")


def test_a_failing_session_lookup_never_breaks_the_turn():
    def boom(_):
        raise RuntimeError("database locked")
    sent = []
    e = echo.Echo(settings=dict, chat_for=boom, sender=lambda *a: sent.append(a), from_messaging=lambda: False,
                  run=lambda fn: fn())
    e.after_turn(session_id="photon-1", user_message="hi", assistant_response="hello")
    assert sent == []


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_the_sidecar_gets_what_the_photon_adapter_sends(monkeypatch):
    seen = {}

    def opener(req, timeout):
        seen.update(url=req.full_url, body=json.loads(req.data), token=req.headers.get("X-hermes-sidecar-token"))
        return _Resp(b'{"ok": true, "messageId": "m1"}')

    monkeypatch.delenv("PHOTON_MARKDOWN", raising=False)
    assert echo.send_to_thread("any;-;+1", "**hi**", sidecar=lambda: (8789, "tok"), opener=opener) is True
    assert seen == {"url": "http://127.0.0.1:8789/send", "token": "tok",
                    "body": {"spaceId": "any;-;+1", "text": "**hi**", "format": "markdown"}}
    monkeypatch.setenv("PHOTON_MARKDOWN", "false")
    echo.send_to_thread("any;-;+1", "x" * 9000, sidecar=lambda: (1, "t"), opener=opener)
    assert "format" not in seen["body"] and len(seen["body"]["text"]) == echo.MAX_MESSAGE_LENGTH


def test_no_sidecar_or_a_refusal_is_a_quiet_false():
    def missing():
        raise OSError("no runtime record")
    assert echo.send_to_thread("s", "hi", sidecar=missing) is False
    assert echo.send_to_thread("s", "hi", sidecar=lambda: (1, "t"), opener=lambda r, timeout: _Resp(b'{"ok": false}')) is False
    assert echo.send_to_thread("s", "   ", sidecar=lambda: (1, "t")) is False


def test_the_gateway_turn_context_marks_a_turn_from_messaging(monkeypatch):
    monkeypatch.setattr(echo, "_session_env", lambda name: {"HERMES_SESSION_PLATFORM": "photon"}.get(name, ""))
    assert echo.turn_came_from_messaging() is True
    monkeypatch.setattr(echo, "_session_env", lambda name: {"HERMES_SESSION_SOURCE": "photon"}.get(name, ""))
    assert echo.turn_came_from_messaging() is False      # Desktop binds the source, never the platform or chat


def test_register_hooks_after_each_turn():
    hooks = []

    class Ctx:
        def get_config(self, key):
            return None

        def register_hook(self, name, fn):
            hooks.append(name)

    echo.register(Ctx())
    assert hooks == ["post_llm_call"]
