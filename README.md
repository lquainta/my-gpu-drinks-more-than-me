# Jarvis

A voice interface for [Claude Code](https://claude.com/claude-code), in the manner of Tony Stark's J.A.R.V.I.S.
You speak, Jarvis listens, Claude Code does the work, and Jarvis answers aloud in a dry British voice.

```
 mic ──► faster-whisper (local) ──► claude -p (Claude Code) ──► Kokoro voice (local) ──► speakers
```

- **Hearing** runs locally with [faster-whisper](https://github.com/SYSTRAN/faster-whisper). The model downloads once (~150 MB for `base.en`), then works offline.
- **Speaking** runs locally with [Kokoro](https://github.com/thewh1teagle/kokoro-onnx), a small neural voice model, as a refined British male voice with a subtle reverb for that AI-in-the-room sound. The model (~340 MB) downloads to `~/.cache/jarvis` on first run. `--tts say` switches to the macOS built-in voices instead.
- **Thinking** is Claude Code itself, so Jarvis can read and edit files and run commands in the directory you start it in. This is the only part that needs the internet.

## Requirements

- macOS
- [uv](https://docs.astral.sh/uv/)
- Claude Code installed and logged in (`claude` on your PATH)

## Usage

```sh
uv run jarvis                      # push-to-talk: press Enter, speak, press Enter
uv run jarvis --mode handsfree     # always listening; start with "Jarvis, ..."
uv run jarvis --mode text          # type instead of talk (still speaks back)
```

The first time you use a voice mode, macOS will ask to let your terminal use the microphone.

Things you can say:

| Say | Effect |
| --- | --- |
| "Jarvis, run the tests" | Anything you'd ask Claude Code |
| "New conversation" / "Start over" | Forget the current conversation |
| "That will be all" / "Goodbye" | Quit |

Press **Ctrl-C** while Jarvis is talking or working to interrupt; press it at the prompt to quit.

### Options

| Flag | Default | |
| --- | --- | --- |
| `--tts` | `kokoro` | `kokoro` (natural neural voice) or `say` (macOS voices) |
| `--voice` | `bm_george` | Kokoro: `bm_george`, `bm_lewis`, `bm_daniel`, `bm_fable`. With `--tts say`: any of `say -v '?'` |
| `--speed` | `1.05` | Kokoro speaking speed |
| `--rate` | `185` | `say` speaking speed in words per minute |
| `--no-fx` | | Turn off the reverb and doubling on the voice |
| `--whisper-model` | `base.en` | `tiny.en` is faster, `small.en` is more accurate |
| `--model` | your Claude Code default | e.g. `sonnet` for faster replies |
| `--cwd` | current directory | Where Jarvis works |
| `--permission-mode` | `acceptEdits` | Nobody can click "allow" by voice, so pick ahead of time. `bypassPermissions` lets Jarvis run any command; use with care. |
| `--silence` | `1.2` | Seconds of quiet that end a sentence in hands-free mode |
| `--no-wake-word` | | In hands-free mode, respond to everything |
| `--mute` | | Print replies without speaking |

The voice is styled after the character (calm, British, a little processed), not a copy of
any actor's voice.

## Layout

```
src/jarvis/
  cli.py      main loop, built-in phrases, argument parsing
  brain.py    runs `claude -p` with streaming JSON and resumes the session each turn
  persona.py  the J.A.R.V.I.S. personality, appended to Claude Code's system prompt
  stt.py      speech-to-text (faster-whisper)
  tts.py      text-to-speech (Kokoro or `say`) plus the voice effect; speaks each sentence
              as the reply streams in, synthesising the next while the current one plays
  audio.py    microphone capture: push-to-talk and voice-activity detection
```
