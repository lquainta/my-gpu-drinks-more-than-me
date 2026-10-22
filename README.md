# Jarvis

A voice interface for [Claude Code](https://claude.com/claude-code), in the manner of Tony Stark's J.A.R.V.I.S.
You speak, Jarvis listens, Claude Code does the work, and Jarvis answers aloud in a dry British voice.

```
 mic ──► faster-whisper (local) ──► claude -p (Claude Code) ──► macOS `say` (local) ──► speakers
```

- **Hearing** runs locally with [faster-whisper](https://github.com/SYSTRAN/faster-whisper). The model downloads once (~150 MB for `base.en`), then works offline.
- **Speaking** uses macOS's built-in `say` with the British "Daniel" voice. Nothing to download.
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
| `--voice` | `Daniel` | Any macOS voice, see `say -v '?'` |
| `--rate` | `185` | Speaking speed in words per minute |
| `--whisper-model` | `base.en` | `tiny.en` is faster, `small.en` is more accurate |
| `--model` | your Claude Code default | e.g. `sonnet` for faster replies |
| `--cwd` | current directory | Where Jarvis works |
| `--permission-mode` | `acceptEdits` | Nobody can click "allow" by voice, so pick ahead of time. `bypassPermissions` lets Jarvis run any command; use with care. |
| `--silence` | `1.2` | Seconds of quiet that end a sentence in hands-free mode |
| `--no-wake-word` | | In hands-free mode, respond to everything |
| `--mute` | | Print replies without speaking |

Better voices: macOS has higher-quality downloadable voices under
System Settings → Accessibility → Spoken Content → System Voice → Manage Voices.
Download "Daniel (Enhanced)" or "Jamie (Premium)", then pass `--voice "Jamie (Premium)"`.

## Layout

```
src/jarvis/
  cli.py      main loop, built-in phrases, argument parsing
  brain.py    runs `claude -p` with streaming JSON and resumes the session each turn
  persona.py  the J.A.R.V.I.S. personality, appended to Claude Code's system prompt
  stt.py      speech-to-text (faster-whisper)
  tts.py      text-to-speech (`say`), speaks sentence by sentence as the reply streams in
  audio.py    microphone capture: push-to-talk and voice-activity detection
```
