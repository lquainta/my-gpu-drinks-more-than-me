"""Text-to-speech, fully offline: Kokoro (neural) or the macOS `say` command."""

import os
import queue
import re
import subprocess
import tempfile
import threading
import time
import urllib.request

import numpy as np
import sounddevice as sd

_SENTENCE_END = re.compile(r"(?<=[.!?:;])\s+|\n+")
_MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"
_CACHE = os.path.expanduser("~/.cache/jarvis")


def clean_for_speech(text: str) -> str:
    """Strip markdown and other things that sound terrible when read aloud."""
    text = re.sub(r"```.*?(```|$)", " I've put the code on screen. ", text, flags=re.S)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # [label](url) -> label
    text = re.sub(r"https?://\S+", "the link on screen", text)
    text = re.sub(r"^\s*(#+|[-*+]|\d+\.)\s+", "", text, flags=re.M)
    text = re.sub(r"[*_#>|~]", "", text)
    return re.sub(r"\s+", " ", text).strip()


class KokoroVoice:
    """Kokoro-82M neural voice. Downloads its model (~340 MB) on first use."""

    def __init__(self, voice: str = "bm_george", speed: float = 1.05):
        from kokoro_onnx import Kokoro

        files = [_fetch(name) for name in ("kokoro-v1.0.onnx", "voices-v1.0.bin")]
        self.model = Kokoro(*files)
        if voice not in self.model.get_voices():
            raise SystemExit(f"Unknown Kokoro voice {voice!r}. Try one of: "
                             + ", ".join(self.model.get_voices()))
        self.voice = voice
        self.speed = speed
        self.lang = "en-gb" if voice.startswith("b") else "en-us"

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        return self.model.create(text, voice=self.voice, speed=self.speed, lang=self.lang)


class SayVoice:
    """The macOS built-in `say` voices."""

    def __init__(self, voice: str = "Daniel", rate: int = 185):
        self.voice = voice
        self.rate = rate

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        from jarvis.stt import load_audio

        with tempfile.NamedTemporaryFile(suffix=".aiff") as tmp:
            subprocess.run(["say", "-v", self.voice, "-r", str(self.rate), "-o", tmp.name, text],
                           check=True)
            return load_audio(tmp.name, sample_rate=22_050), 22_050


def _fetch(name: str) -> str:
    path = os.path.join(_CACHE, name)
    if not os.path.exists(path):
        os.makedirs(_CACHE, exist_ok=True)
        print(f"Downloading voice model {name} (one time only)...")
        urllib.request.urlretrieve(_MODEL_URL + name, path + ".part")
        os.replace(path + ".part", path)
    return path


def jarvis_fx(audio: np.ndarray, sr: int) -> np.ndarray:
    """A subtle 'AI in the room' polish: a faint double and a short, bright reverb."""
    # A quiet copy 11 ms behind gives a slightly synthetic, doubled sheen.
    delay = int(sr * 0.011)
    doubled = audio.copy()
    doubled[delay:] += 0.18 * audio[:-delay]

    # A short reverb tail from exponentially decaying noise; fixed seed so it never varies.
    length = int(sr * 0.4)
    rng = np.random.default_rng(7)
    impulse = rng.standard_normal(length) * np.exp(-np.linspace(0, 9, length))
    impulse[0] = 0
    n = len(doubled) + length - 1
    size = 1 << (n - 1).bit_length()
    wet = np.fft.irfft(np.fft.rfft(doubled, size) * np.fft.rfft(impulse, size), size)[:n]
    wet *= 0.08 / (np.max(np.abs(wet)) + 1e-9)

    out = np.zeros(n, dtype=np.float32)
    out[: len(doubled)] += doubled
    out += wet
    # Trim the tail to a quarter second so sentences don't smear together.
    out = out[: len(audio) + int(sr * 0.25)]
    return (0.9 * out / (np.max(np.abs(out)) + 1e-9)).astype(np.float32)


class Speaker:
    """Speaks queued sentences in order.

    One thread synthesises while another plays, so the next sentence is usually ready
    by the time the current one finishes.
    """

    def __init__(self, voice=None, fx: bool = False, enabled: bool = True):
        self.voice = voice
        self.fx = fx
        self.enabled = enabled and voice is not None
        self._text: queue.Queue[tuple[int, str]] = queue.Queue()
        self._audio: queue.Queue[tuple[int, np.ndarray, int]] = queue.Queue()
        self._generation = 0  # bumped by stop() so stale audio is dropped
        self._now_playing: tuple[np.ndarray, int, float] | None = None
        threading.Thread(target=self._synthesize_loop, daemon=True).start()
        threading.Thread(target=self._play_loop, daemon=True).start()

    def _synthesize_loop(self) -> None:
        while True:
            generation, text = self._text.get()
            try:
                if generation == self._generation:
                    audio, sr = self.voice.synthesize(text)
                    if self.fx:
                        audio = jarvis_fx(audio, sr)
                    self._audio.put((generation, audio, sr))
            except Exception as exc:  # a bad sentence shouldn't kill the voice
                print(f"\n[speech error: {exc}]")
            finally:
                self._text.task_done()

    def _play_loop(self) -> None:
        while True:
            generation, audio, sr = self._audio.get()
            try:
                if generation == self._generation:
                    self._now_playing = (audio, sr, time.monotonic())
                    sd.play(audio, sr)
                    sd.wait()
            finally:
                self._now_playing = None
                self._audio.task_done()

    def is_speaking(self) -> bool:
        return self._now_playing is not None

    def level(self) -> float:
        """Loudness of the audio playing right now, for visualisation."""
        playing = self._now_playing
        if not playing:
            return 0.0
        audio, sr, started = playing
        i = int((time.monotonic() - started) * sr)
        window = audio[i : i + 1024]
        return float(np.sqrt(np.mean(window**2))) if len(window) else 0.0

    def say(self, text: str) -> None:
        text = clean_for_speech(text)
        if self.enabled and text:
            self._text.put((self._generation, text))

    def wait(self) -> None:
        """Block until everything queued has been spoken."""
        self._text.join()
        self._audio.join()

    def stop(self) -> None:
        """Stop speaking immediately and discard anything queued."""
        self._generation += 1
        sd.stop()


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
