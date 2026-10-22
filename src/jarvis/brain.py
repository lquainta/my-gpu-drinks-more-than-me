"""Drives Claude Code in headless mode, keeping one conversation across turns."""

import json
import subprocess
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass

from jarvis.persona import PERSONA


@dataclass
class Event:
    kind: str  # "text", "tool", "error", "cost", or "done"
    value: str = ""


class Brain:
    def __init__(self, cwd: str, model: str | None = None,
                 permission_mode: str = "acceptEdits"):
        self.cwd = cwd
        self.model = model
        self.permission_mode = permission_mode
        self.session_id: str | None = None
        self._proc: subprocess.Popen | None = None

    def _command(self, prompt: str) -> list[str]:
        cmd = [
            "claude", "-p", prompt,
            "--output-format", "stream-json", "--verbose", "--include-partial-messages",
            "--append-system-prompt", PERSONA,
            "--permission-mode", self.permission_mode,
        ]
        if self.session_id:
            cmd += ["--resume", self.session_id]
        if self.model:
            cmd += ["--model", self.model]
        return cmd

    def ask(self, prompt: str) -> Iterator[Event]:
        """Send a prompt and yield the reply as it streams in."""
        stderr = tempfile.TemporaryFile(mode="w+")
        self._proc = subprocess.Popen(
            self._command(prompt), cwd=self.cwd, text=True,
            stdout=subprocess.PIPE, stderr=stderr,
        )
        try:
            for line in self._proc.stdout:
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if msg.get("session_id"):
                    self.session_id = msg["session_id"]
                # Only the main agent speaks; ignore sub-agent chatter.
                if msg.get("type") == "result":
                    if msg.get("is_error"):
                        yield Event("error", str(msg.get("result", "unknown error")))
                    if msg.get("total_cost_usd") is not None:
                        yield Event("cost", str(msg["total_cost_usd"]))
                    continue
                if msg.get("type") != "stream_event" or msg.get("parent_tool_use_id"):
                    continue
                event = msg["event"]
                if event["type"] == "content_block_delta" and event["delta"]["type"] == "text_delta":
                    yield Event("text", event["delta"]["text"])
                elif event["type"] == "content_block_start" and event["content_block"]["type"] == "tool_use":
                    yield Event("tool", event["content_block"]["name"])
                elif event["type"] == "message_stop":
                    # Separates text from consecutive assistant messages in a tool loop.
                    yield Event("text", "\n")
            self._proc.wait()
            if self._proc.returncode not in (0, None, -15):
                stderr.seek(0)
                err = stderr.read().strip()
                if err:
                    yield Event("error", err.splitlines()[-1])
        finally:
            self.cancel()
            stderr.close()
        yield Event("done")

    def cancel(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    def reset(self) -> None:
        self.session_id = None
