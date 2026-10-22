"""The plain, scrolling terminal interface. See hud.py for the full-screen one.

Both interfaces offer the same methods, so the main loop doesn't care which is in use.
"""

import threading

DIM, CYAN, YELLOW, RED, RESET = "\033[2m", "\033[36m", "\033[33m", "\033[31m", "\033[0m"


class PlainUI:
    def __init__(self):
        self.on_interrupt = None  # Ctrl-C is the only interrupt here
        self.level_source = None
        self.speaking_source = None

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def state(self, name: str) -> None:
        pass

    def info(self, **values) -> None:
        pass

    def mic_level(self, rms: float) -> None:
        pass

    def system(self, text: str) -> None:
        print(f"{DIM}{text}{RESET}")

    def jarvis(self, text: str) -> None:
        print(f"{CYAN}Jarvis:{RESET} {text}")

    def user(self, text: str) -> None:
        print(f"{YELLOW}You:{RESET} {text}")

    def reply_begin(self) -> None:
        print(f"{CYAN}Jarvis:{RESET} ", end="", flush=True)

    def reply_delta(self, text: str) -> None:
        print(text, end="", flush=True)

    def reply_end(self) -> None:
        print()

    def tool(self, name: str) -> None:
        print(f"{DIM}[{name}]{RESET} ", end="", flush=True)

    def error(self, text: str) -> None:
        print(f"\n{RED}{text}{RESET}")

    def notice(self, text: str) -> None:
        print(f"\n{DIM}({text}){RESET}")

    def read_text(self) -> str:
        return input(f"{YELLOW}You:{RESET} ")

    def wait_to_talk(self) -> None:
        input(f"{DIM}Press Enter to speak...{RESET}")
        print(f"{YELLOW}Listening... (Enter to finish){RESET}")

    def talk_finished(self) -> threading.Event:
        done = threading.Event()
        threading.Thread(target=lambda: (input(), done.set()), daemon=True).start()
        return done
