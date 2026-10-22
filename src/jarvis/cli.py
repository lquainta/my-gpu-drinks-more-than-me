"""Jarvis: talk to Claude Code out loud."""

import argparse
import os
import random
import re
import sys

from jarvis.brain import Brain
from jarvis.tts import SentenceStream, Speaker

DIM, CYAN, YELLOW, RED, RESET = "\033[2m", "\033[36m", "\033[33m", "\033[31m", "\033[0m"

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


def respond(brain: Brain, speaker: Speaker, prompt: str) -> None:
    """Stream Claude's reply to the terminal and the speaker at the same time."""
    sentences = SentenceStream(speaker)
    print(f"{CYAN}Jarvis:{RESET} ", end="", flush=True)
    try:
        for event in brain.ask(prompt):
            if event.kind == "text":
                print(event.value, end="", flush=True)
                sentences.feed(event.value)
            elif event.kind == "tool":
                print(f"{DIM}[{event.value}]{RESET} ", end="", flush=True)
            elif event.kind == "error":
                print(f"\n{RED}{event.value}{RESET}")
                speaker.say("I'm afraid something went wrong, sir. Details are on screen.")
        sentences.flush()
        print()
        speaker.wait()
    except KeyboardInterrupt:
        brain.cancel()
        speaker.stop()
        print(f"\n{DIM}(interrupted){RESET}")


def announce(speaker: Speaker, line: str) -> None:
    print(f"{CYAN}Jarvis:{RESET} {line}")
    speaker.say(line)
    speaker.wait()


def handle_command(text: str, brain: Brain, speaker: Speaker) -> bool | None:
    """Handle built-in phrases. Returns False to quit, True if handled, None otherwise."""
    if EXIT_PHRASES.search(text) and len(text.split()) <= 6:
        announce(speaker, random.choice(FAREWELLS))
        return False
    if RESET_PHRASES.search(text):
        brain.reset()
        announce(speaker, "Conversation cleared, sir. Starting afresh.")
        return True
    return None


def listen(args, transcriber) -> str:
    from jarvis import audio

    if args.mode == "ptt":
        input(f"{DIM}Press Enter to speak...{RESET}")
        print(f"{YELLOW}Listening... (Enter to finish){RESET}")
        samples = audio.record_push_to_talk()
    else:
        print(f"{DIM}Listening{' for \"Jarvis\"' if args.wake_word else ''}...{RESET}")
        samples = audio.record_utterance(silence_seconds=args.silence)
    if len(samples) < 16_000 * 0.3:
        return ""
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
    parser.add_argument("--no-fx", dest="fx", action="store_false",
                        help="turn off the subtle reverb and doubling on the voice")
    parser.add_argument("--mute", action="store_true", help="print replies without speaking")
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

    voice = None
    if not args.mute:
        from jarvis.tts import KokoroVoice, SayVoice
        if args.tts == "kokoro":
            print(f"{DIM}Loading voice...{RESET}")
            voice = KokoroVoice(args.voice or "bm_george", speed=args.speed)
        else:
            voice = SayVoice(args.voice or "Daniel", rate=args.rate)
    speaker = Speaker(voice, fx=args.fx)
    brain = Brain(cwd=args.cwd, model=args.model, permission_mode=args.permission_mode)

    transcriber = None
    if args.mode != "text":
        print(f"{DIM}Loading speech recognition ({args.whisper_model})...{RESET}")
        from jarvis.stt import Transcriber
        transcriber = Transcriber(args.whisper_model)

    announce(speaker, random.choice(GREETINGS))

    while True:
        try:
            if args.mode == "text":
                text = input(f"{YELLOW}You:{RESET} ").strip()
            else:
                text = listen(args, transcriber)
                if args.mode == "handsfree" and args.wake_word:
                    if not WAKE_WORD.match(text):
                        continue
                    text = WAKE_WORD.sub("", text).strip() or "Yes?"
                if text:
                    print(f"{YELLOW}You:{RESET} {text}")
        except (KeyboardInterrupt, EOFError):
            print()
            announce(speaker, random.choice(FAREWELLS))
            return
        if not text:
            continue
        handled = handle_command(text, brain, speaker)
        if handled is False:
            return
        if handled is None:
            respond(brain, speaker, text)


if __name__ == "__main__":
    sys.exit(main())
