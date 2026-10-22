"""Microphone capture: push-to-talk and hands-free (energy-based voice detection)."""

import subprocess
import threading
from collections import deque

import numpy as np
import sounddevice as sd

from jarvis.stt import SAMPLE_RATE

BLOCK = int(SAMPLE_RATE * 0.03)  # 30 ms frames
_SOUNDS = "/System/Library/Sounds"


def chime(name: str = "Tink") -> None:
    """Play a short system sound without blocking."""
    subprocess.Popen(
        ["afplay", f"{_SOUNDS}/{name}.aiff"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _rms(frame: np.ndarray) -> float:
    return float(np.sqrt(np.mean(frame**2)))


def record_push_to_talk() -> np.ndarray:
    """Record from the moment this is called until the user presses Enter."""
    frames: list[np.ndarray] = []
    stop = threading.Event()

    def callback(indata, _frames, _time, _status):
        frames.append(indata[:, 0].copy())

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                        blocksize=BLOCK, callback=callback):
        chime("Tink")
        threading.Thread(target=lambda: (input(), stop.set()), daemon=True).start()
        stop.wait()
    chime("Pop")
    return np.concatenate(frames) if frames else np.zeros(0, dtype=np.float32)


def record_utterance(
    silence_seconds: float = 1.2,
    max_seconds: float = 30.0,
    sensitivity: float = 3.0,
) -> np.ndarray:
    """Wait for speech, then record until the speaker goes quiet.

    The noise floor is measured for half a second first, and anything louder than
    `sensitivity` times that floor counts as speech.
    """
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                        blocksize=BLOCK) as stream:
        calibration = [_rms(stream.read(BLOCK)[0][:, 0]) for _ in range(17)]
        threshold = max(float(np.median(calibration)) * sensitivity, 0.008)

        pre_roll: deque[np.ndarray] = deque(maxlen=10)  # keep 300 ms before speech
        recorded: list[np.ndarray] = []
        loud_streak = quiet_frames = 0
        speaking = False
        silence_limit = int(silence_seconds / 0.03)
        max_frames = int(max_seconds / 0.03)

        while True:
            frame = stream.read(BLOCK)[0][:, 0].copy()
            loud = _rms(frame) > threshold
            if not speaking:
                pre_roll.append(frame)
                loud_streak = loud_streak + 1 if loud else 0
                if loud_streak >= 3:
                    speaking = True
                    recorded.extend(pre_roll)
                continue
            recorded.append(frame)
            quiet_frames = 0 if loud else quiet_frames + 1
            if quiet_frames >= silence_limit or len(recorded) >= max_frames:
                return np.concatenate(recorded)
