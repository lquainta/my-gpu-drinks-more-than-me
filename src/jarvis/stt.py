"""Speech-to-text with faster-whisper, running locally on the CPU."""

import numpy as np

SAMPLE_RATE = 16_000


class Transcriber:
    def __init__(self, model_size: str = "base.en"):
        # Imported lazily: loading the library is slow and text mode doesn't need it.
        from faster_whisper import WhisperModel

        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe mono float32 audio sampled at 16 kHz."""
        segments, _ = self.model.transcribe(
            audio,
            language="en",
            beam_size=1,
            vad_filter=True,
            # Biases recognition towards the name, which whisper otherwise mangles.
            initial_prompt="Jarvis, sir.",
        )
        return " ".join(s.text.strip() for s in segments).strip()

    def transcribe_file(self, path: str) -> str:
        return self.transcribe(load_audio(path))


def load_audio(path: str) -> np.ndarray:
    """Decode any audio file macOS understands to 16 kHz mono float32."""
    import subprocess
    import tempfile
    import wave

    with tempfile.NamedTemporaryFile(suffix=".wav") as tmp:
        subprocess.run(
            ["afconvert", "-f", "WAVE", "-d", f"LEI16@{SAMPLE_RATE}", "-c", "1", path, tmp.name],
            check=True,
        )
        with wave.open(tmp.name) as wav:
            pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0
