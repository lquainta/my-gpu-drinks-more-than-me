"""Text-to-speech using the macOS built-in `say` command, fully offline."""

import queue
import re
import subprocess
import threading

_SENTENCE_END = re.compile(r"(?<=[.!?:;])\s+|\n+")


def clean_for_speech(text: str) -> str:
    """Strip markdown and other things that sound terrible when read aloud."""
    text = re.sub(r"```.*?(```|$)", " I've put the code on screen. ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # [label](url) -> label
    text = re.sub(r"https?://\S+", "the link on screen", text)
    text = re.sub(r"^\s*(#+|[-*+]|\d+\.)\s+", "", text, flags=re.M)
    text = re.sub(r"[*_#>|~]", "", text)
    return re.sub(r"\s+", " ", text).strip()


class Speaker:
    """Speaks queued sentences one after another in a background thread."""

    def __init__(self, voice: str = "Daniel", rate: int = 185, enabled: bool = True):
        self.voice = voice
        self.rate = rate
        self.enabled = enabled
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while True:
            text = self._queue.get()
            try:
                if text is None:
                    return
                with self._lock:
                    self._proc = subprocess.Popen(
                        ["say", "-v", self.voice, "-r", str(self.rate), text],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                self._proc.wait()
            finally:
                self._queue.task_done()

    def say(self, text: str) -> None:
        text = clean_for_speech(text)
        if self.enabled and text:
            self._queue.put(text)

    def wait(self) -> None:
        """Block until everything queued has been spoken."""
        self._queue.join()

    def stop(self) -> None:
        """Stop speaking immediately and discard anything queued."""
        try:
            while True:
                self._queue.get_nowait()
                self._queue.task_done()
        except queue.Empty:
            pass
        with self._lock:
            if self._proc and self._proc.poll() is None:
                self._proc.terminate()


class SentenceStream:
    """Collects streamed text and hands complete sentences to a Speaker."""

    def __init__(self, speaker: Speaker):
        self.speaker = speaker
        self._buffer = ""

    def feed(self, delta: str) -> None:
        self._buffer += delta
        while True:
            # Hold code blocks back until they close so they are summarised, not read.
            if self._buffer.count("```") % 2 == 1:
                return
            match = _SENTENCE_END.search(self._buffer)
            if not match:
                return
            sentence, self._buffer = self._buffer[: match.start()], self._buffer[match.end():]
            self.speaker.say(sentence)

    def flush(self) -> None:
        self.speaker.say(self._buffer)
        self._buffer = ""
