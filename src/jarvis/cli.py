"""Jarvis: talk to Claude Code out loud."""

import argparse
import os
import random
import re
import sys
import threading

from jarvis.brain import Brain
from jarvis.tts import SentenceStream, Speaker
from jarvis.ui import PlainUI

GREETINGS = [
    "At your service, sir.",
    "Good to see you, sir. All systems are online.",
    "Jarvis online. How may I assist you, sir?",
]
FAREWELLS = ["Very good, sir.", "As you wish, sir. Powering down.", "Until next time, sir."]
EXIT_PHRASES = re.compile(
    r"\b(that will be all|that'll be all|goodbye|good night|power down|shut down|exit)\b", re.I)
RESET_PHRASES = re.compile(r"\b(new conversation|start over|clear (the )?(context|memory))\b", re.I)
WAKE_WORD = re.compile(r"^\W*(hey |ok |okay )?(jarvis|jervis|travis|javis)\b[\s,.!?]*", re.I)


def respond(brain: Brain, speaker: Speaker, ui, prompt: str) -> None:
    """Stream Claude's reply to the screen and the speaker at the same time."""
    sentences = SentenceStream(speaker)
    interrupted = threading.Event()

    def interrupt():
        interrupted.set()
        brain.cancel()
        speaker.stop()

    ui.on_interrupt = interrupt
    ui.state("thinking")
    ui.reply_begin()
    try:
        for event in brain.ask(prompt):
            if event.kind == "text":
                ui.reply_delta(event.value)
                sentences.feed(event.value)
            elif event.kind == "tool":
                ui.tool(event.value)
            elif event.kind == "error":
                ui.error(event.value)
                speaker.say("I'm afraid something went wrong, sir. Details are on screen.")
            elif event.kind == "cost":
                ui.info(cost=float(event.value))
        ui.reply_end()
        if not interrupted.is_set():
            sentences.flush()
            speaker.wait()
    except KeyboardInterrupt:
        interrupt()
    if interrupted.is_set():
        ui.notice("interrupted")
    ui.on_interrupt = None
    ui.info(session=brain.session_id)


def announce(speaker: Speaker, ui, line: str) -> None:
    ui.jarvis(line)
    speaker.say(line)
    speaker.wait()


def handle_command(text: str, brain: Brain, speaker: Speaker, ui) -> bool | None:
    """Handle built-in phrases. Returns False to quit, True if handled, None otherwise."""
    if EXIT_PHRASES.search(text) and len(text.split()) <= 6:
        announce(speaker, ui, random.choice(FAREWELLS))
        return False
    if RESET_PHRASES.search(text):
        brain.reset()
        ui.info(session=None, turns=0, cost=0.0)
        announce(speaker, ui, "Conversation cleared, sir. Starting afresh.")
        return True
    return None


def listen(args, transcriber, ui) -> str:
    from jarvis import audio

    if args.mode == "ptt":
        ui.state("standby")
        ui.wait_to_talk()
        ui.state("listening")
        samples = audio.record_push_to_talk(ui.talk_finished(), on_level=ui.mic_level)
    else:
        ui.state("listening")
        samples = audio.record_utterance(silence_seconds=args.silence, on_level=ui.mic_level)
    if len(samples) < 16_000 * 0.3:
        return ""
    ui.state("transcribing")
    return transcriber.transcribe(samples)


def main() -> None:
    parser = argparse.ArgumentParser(prog="jarvis", description=__doc__)
    parser.add_argument("--mode", choices=["ptt", "handsfree", "text"], default="ptt",
                        help="ptt: press Enter to talk (default); handsfree: voice-activated; "
                             "text: type instead of talking")
    parser.add_argument("--no-wake-word", dest="wake_word", action="store_false",
                        help="in handsfree mode, respond to everything, not just 'Jarvis ...'")
    parser.add_argument("--tts", choices=["kokoro", "say"], default="kokoro",
                        help="kokoro: natural neural voice (default); say: macOS built-in voices")
    parser.add_argument("--voice", help="kokoro: bm_george (default), bm_lewis, bm_daniel, "
                                        "bm_fable; say: Daniel (default) or see `say -v '?'`")
    parser.add_argument("--speed", type=float, default=1.05, help="kokoro speaking speed")
    parser.add_argument("--rate", type=int, default=185, help="say speaking rate, words per minute")
    parser.add_argument("--fx", action="store_true",
                        help="add a reverb and doubling effect to the voice (off by default)")
    parser.add_argument("--mute", action="store_true", help="print replies without speaking")
    parser.add_argument("--plain", action="store_true",
                        help="plain scrolling output instead of the full-screen HUD")
    parser.add_argument("--whisper-model", default="base.en",
                        help="tiny.en, base.en, small.en, medium.en (bigger = more accurate, slower)")
    parser.add_argument("--silence", type=float, default=1.2,
                        help="seconds of quiet that end an utterance in handsfree mode")
    parser.add_argument("--model", help="Claude model for Claude Code, e.g. sonnet or opus")
    parser.add_argument("--cwd", default=os.getcwd(), help="directory Jarvis works in")
    parser.add_argument("--permission-mode", default="acceptEdits",
                        choices=["default", "acceptEdits", "plan", "bypassPermissions"],
                        help="Claude Code permission mode (no one can click 'allow' by voice)")
    args = parser.parse_args()

    if args.plain or not sys.stdout.isatty() or not sys.stdin.isatty():
        ui = PlainUI()
    else:
        from jarvis.hud import HudUI
        ui = HudUI({"model": args.model, "cwd": os.path.basename(args.cwd),
                    "voice": "muted" if args.mute else args.voice or
                    ("bm_george" if args.tts == "kokoro" else "Daniel")})
    ui.start()
    try:
        run(args, ui)
    finally:
        ui.stop()


def run(args, ui) -> None:
    ui.state("booting")
    ui.system("INITIALISING J.A.R.V.I.S.")
    voice = None
    if not args.mute:
        from jarvis.tts import KokoroVoice, SayVoice
        if args.tts == "kokoro":
            ui.system("LOADING VOICE SYNTHESIS ...")
            voice = KokoroVoice(args.voice or "bm_george", speed=args.speed)
        else:
            voice = SayVoice(args.voice or "Daniel", rate=args.rate)
        ui.system("VOICE SYNTHESIS ........ ONLINE")
    speaker = Speaker(voice, fx=args.fx)
    ui.level_source = speaker.level
    ui.speaking_source = speaker.is_speaking
    brain = Brain(cwd=args.cwd, model=args.model, permission_mode=args.permission_mode)

    transcriber = None
    if args.mode != "text":
        ui.system(f"LOADING SPEECH RECOGNITION ({args.whisper_model.upper()}) ...")
        from jarvis.stt import Transcriber
        transcriber = Transcriber(args.whisper_model)
        ui.system("SPEECH RECOGNITION ..... ONLINE")
    ui.system(f"UPLINK: CLAUDE CODE .... READY  ({os.path.basename(args.cwd) or args.cwd})")

    ui.state("standby")
    announce(speaker, ui, random.choice(GREETINGS))
    turns = 0

    while True:
        try:
            if args.mode == "text":
                ui.state("standby")
                text = ui.read_text().strip()
            else:
                text = listen(args, transcriber, ui)
                if args.mode == "handsfree" and args.wake_word:
                    if not WAKE_WORD.match(text):
                        continue
                    text = WAKE_WORD.sub("", text).strip() or "Yes?"
            if text:
                if args.mode != "text" or not isinstance(ui, PlainUI):
                    ui.user(text)
        except (KeyboardInterrupt, EOFError):
            announce(speaker, ui, random.choice(FAREWELLS))
            return
        if not text:
            continue
        handled = handle_command(text, brain, speaker, ui)
        if handled is False:
            return
        if handled is None:
            respond(brain, speaker, ui, text)
            turns += 1
            ui.info(turns=turns)

if __name__ == "__main__":
    sys.exit(main())
