"""core/discord.py against a local stand-in for Discord's webhook endpoint."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from core import discord
from core.discord import DiscordError, Embed, Webhook


@pytest.fixture
def server():
    seen: list = []
    replies: list = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            parts = urlsplit(self.path)
            seen.append((parts.path, parse_qs(parts.query), body))
            status, answer = replies.pop(0) if replies else (200, {"id": "1", "channel_id": "777"})
            data = json.dumps(answer).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    url = f"http://127.0.0.1:{httpd.server_port}/api/webhooks/1/tok"
    yield SimpleNamespace(url=url, seen=seen, replies=replies)
    httpd.shutdown()


def test_a_message_carries_its_content_and_identity(server):
    hook = Webhook(server.url, username="ED Live Dashboard", avatar_url="http://a/b.png")
    hook.send("hello")
    path, query, body = server.seen[0]
    assert path == "/api/webhooks/1/tok"
    assert query["wait"] == ["true"]
    assert body == {"content": "hello", "username": "ED Live Dashboard",
                    "avatar_url": "http://a/b.png"}


def test_an_embed_is_sent_as_discord_expects_it():
    e = (Embed("▶  Monitoring Active", "00e5ff")
         .add_field("Commander", "CMDR X", inline=False)
         .set_footer("v1"))
    e.set_timestamp()
    assert e.data["color"] == 0x00E5FF
    assert e.data["fields"] == [{"name": "Commander", "value": "CMDR X", "inline": False}]
    assert e.data["footer"] == {"text": "v1"}
    assert e.data["timestamp"].endswith("+00:00")


def test_a_forum_thread_is_started_once_then_posted_into(server):
    hook = Webhook(server.url)
    hook.thread_name = "CMDR X"
    hook.send("first")
    hook.send("second")
    (_, q1, b1), (_, q2, b2) = server.seen
    assert b1["thread_name"] == "CMDR X" and "thread_id" not in q1
    assert "thread_name" not in b2 and q2["thread_id"] == ["777"]


def test_a_refused_post_says_why(server):
    server.replies.append((400, {"message": "Webhooks posted to forum channels must have a thread_name or thread_id"}))
    with pytest.raises(DiscordError) as err:
        Webhook(server.url).send("x")
    assert err.value.status == 400 and "thread_name" in str(err.value)


def test_a_rate_limit_is_waited_out_once(server, monkeypatch):
    monkeypatch.setattr(discord.time, "sleep", lambda s: None)
    server.replies.append((429, {"retry_after": 0.5}))
    Webhook(server.url).send("x")
    assert len(server.seen) == 2

    server.replies.extend([(429, {"retry_after": 0.5}), (429, {"retry_after": 0.5})])
    with pytest.raises(DiscordError):
        Webhook(server.url).send("y")


def _emitter(server, **dc):
    from core.emit import Emitter
    cfg = SimpleNamespace(discord_cfg={"WebhookURL": server.url, **dc}, app_settings={})
    state = SimpleNamespace(pilot_name="Jameson")
    em = Emitter.__new__(Emitter)
    em._cfg, em._state, em.notify_test = cfg, state, False
    em._discord_update_pending, em._update_version = False, None
    from core.discord import Webhook as W
    em._discord_hook, em._discord_up = W(server.url), True
    return em


def test_the_forum_setting_names_the_thread_after_the_commander(server):
    em = _emitter(server, ForumChannel=True, ThreadCmdrNames=True, Identity=True)
    em._post("one")
    em._post("two")
    (_, _, b1), (_, q2, b2) = server.seen
    assert b1["thread_name"] == "CMDR Jameson" and b1["username"] == "ED Live Dashboard"
    assert q2["thread_id"] == ["777"]


def test_a_forum_without_commander_names_still_gets_a_thread(server):
    em = _emitter(server, ForumChannel=True)
    em._post("one")
    assert server.seen[0][2]["thread_name"].startswith("ED Live Dashboard ")
    assert "username" not in server.seen[0][2]


def test_an_ordinary_channel_gets_no_thread(server):
    em = _emitter(server)
    em._post("one")
    em._post("two")
    assert all("thread_name" not in b and "thread_id" not in q for _, q, b in server.seen)
