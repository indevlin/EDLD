"""core/discord.py — posting to a Discord webhook.

    hook = Webhook(url, username="ED Live Dashboard", avatar_url=…)
    hook.thread_name = "CMDR NAME"        # a forum channel: the first post
                                          # starts the thread, the rest go in it
    hook.send("text")
    hook.send(embeds=[Embed("Title", "00e5ff").add_field("Name", "Value")])

A failed post raises DiscordError with Discord's status and answer. A 429 is
waited out once, for as long as Discord asks, then retried.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Optional

#: The longest a 429 is waited out before giving up.
MAX_RETRY_WAIT_S = 10.0


class DiscordError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"HTTP {status}: {body[:300]}")
        self.status = status
        self.body = body


class Embed:
    def __init__(self, title: str = "", color: str | int = "") -> None:
        self.data: dict = {}
        if title:
            self.data["title"] = title
        if color != "":
            self.data["color"] = int(color, 16) if isinstance(color, str) else int(color)

    def add_field(self, name: str, value: str, inline: bool = True) -> "Embed":
        self.data.setdefault("fields", []).append(
            {"name": str(name)[:256], "value": str(value)[:1024], "inline": bool(inline)})
        return self

    def set_footer(self, text: str) -> "Embed":
        self.data["footer"] = {"text": str(text)[:2048]}
        return self

    def set_timestamp(self, when: Optional[datetime] = None) -> "Embed":
        self.data["timestamp"] = (when or datetime.now(timezone.utc)).isoformat()
        return self


class Webhook:
    def __init__(self, url: str, username: Optional[str] = None,
                 avatar_url: Optional[str] = None, timeout: float = 10.0) -> None:
        self.url = url
        self.username = username
        self.avatar_url = avatar_url
        self.timeout = timeout
        #: A forum channel: the thread the first post starts, by name …
        self.thread_name: Optional[str] = None
        #: … and the thread posts go to once it exists.
        self.thread_id: Optional[str] = None

    def send(self, content: str = "", embeds: Optional[list] = None) -> dict:
        """Post a message; Discord's answer (the message) as a dict."""
        payload: dict = {}
        if content:
            payload["content"] = content[:2000]
        if embeds:
            payload["embeds"] = [e.data if isinstance(e, Embed) else e for e in embeds]
        if self.username:
            payload["username"] = self.username
        if self.avatar_url:
            payload["avatar_url"] = self.avatar_url
        query = {"wait": "true"}
        if self.thread_id:
            query["thread_id"] = self.thread_id
        elif self.thread_name:
            payload["thread_name"] = self.thread_name[:100]
        url = f"{self.url}{'&' if '?' in self.url else '?'}{urllib.parse.urlencode(query)}"
        answer = self._post(url, payload, retry=True)
        if self.thread_name and not self.thread_id and answer.get("channel_id"):
            self.thread_id = str(answer["channel_id"])
        return answer

    def _post(self, url: str, payload: dict, retry: bool) -> dict:
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "User-Agent": "EDLD"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            if exc.code == 429 and retry:
                try:
                    wait = float(json.loads(body).get("retry_after", 1))
                except (ValueError, AttributeError):
                    wait = 1.0
                if wait <= MAX_RETRY_WAIT_S:
                    time.sleep(wait)
                    return self._post(url, payload, retry=False)
            raise DiscordError(exc.code, body) from None
        try:
            return json.loads(body) if body.strip() else {}
        except ValueError:
            return {}
