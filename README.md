# Echo

*ἠχώ, the voice that carries what was said elsewhere*

Keeps your iMessage thread with her whole. When you reply to that conversation in Hermes Desktop, your
message and her answer are echoed to the thread on your phone.

An iMessage (Photon) conversation can be opened and continued in Hermes Desktop. A turn made there is saved
in the conversation, but until now nothing reached the phone, so the thread there had a gap. With echo, after
such a turn:

1. your message is posted to the thread under a header (`💻 You, on Desktop:` by default), since it can
   only appear on her side of the screen
2. her reply follows as a normal message from her, sent the way a reply to a message from your phone is

## What it leaves alone

- **Turns from the phone.** They run in the messaging gateway, which binds the turn's platform and chat, so
  echo sees they came from iMessage and does nothing. Nothing is ever sent twice.
- **Other conversations.** Only conversations whose session (or the session they continue) came from
  Photon are echoed.
- **The conversation history.** The messages go straight to the gateway's running Photon sidecar, not
  through `hermes send`, which would also copy them into the conversation a second time.

If the gateway is not running, there is no sidecar to post through. The turn is unaffected, and the log says
why nothing was echoed.

## Install

```
sync-plugin echo --restart        # or copy this folder to ~/.hermes/plugins/echo
hermes plugins enable echo
systemctl --user restart hermes-gateway hermes-serve
```

## Settings

On its page in Hermes Desktop (**Settings → Plugins → echo**), under `plugins.entries.echo.settings`:

| Setting | Default | |
|---|---|---|
| `enabled` | `true` | Echo Desktop turns in iMessage conversations |
| `header` | `💻 You, on Desktop:` | The line above your message in the thread; empty for none |
| `echo_reply` | `true` | Also post her reply; off posts only your message |

## Testing

```
python3 -m pytest tests
```

## Licence

MIT
