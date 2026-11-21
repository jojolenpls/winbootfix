"""User interaction: plain console, whiptail (ISO menu) or non-interactive."""

from __future__ import annotations

import getpass
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap

from winbootfix.core.i18n import Translator


class Cancelled(Exception):
    """The user cancelled a question (Esc / Ctrl-C / empty choice)."""


class NeedsChoice(Exception):
    """Non-interactive mode cannot choose between several options."""


class UI:
    interactive = True

    def __init__(self, t: Translator, assume_yes: bool = False):
        self.t = t
        self.assume_yes = assume_yes

    # output -------------------------------------------------------------
    def title(self, text: str) -> None:
        raise NotImplementedError

    def info(self, text: str) -> None:
        raise NotImplementedError

    def warn(self, text: str) -> None:
        raise NotImplementedError

    def error(self, text: str) -> None:
        raise NotImplementedError

    def success(self, text: str) -> None:
        self.info(text)

    def show_text(self, title: str, text: str) -> None:
        self.title(title)
        self.info(text)

    # input --------------------------------------------------------------
    def confirm(self, question: str, default: bool = False) -> bool:
        raise NotImplementedError

    def choose(self, question: str, options: list[tuple[str, str]], default: str | None = None) -> str:
        raise NotImplementedError

    def ask_secret(self, prompt: str) -> str:
        raise NotImplementedError


def _supports_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None and os.environ.get("TERM") != "dumb"


class ConsoleUI(UI):
    def __init__(self, t: Translator, assume_yes: bool = False, color: bool | None = None):
        super().__init__(t, assume_yes)
        self.color = _supports_color() if color is None else color
        self.width = min(shutil.get_terminal_size((100, 24)).columns, 100)

    def _c(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.color else text

    def _wrap(self, text: str, indent: str = "") -> str:
        out = []
        for para in text.split("\n"):
            out.append(textwrap.fill(para, self.width, initial_indent=indent, subsequent_indent=indent)
                       if para.strip() else "")
        return "\n".join(out)

    def title(self, text: str) -> None:
        print()
        print(self._c("1;36", text))
        print(self._c("36", "=" * min(len(text), self.width)))

    def info(self, text: str) -> None:
        print(self._wrap(text))

    def warn(self, text: str) -> None:
        print(self._c("1;33", self._wrap(f"! {text}")))

    def error(self, text: str) -> None:
        print(self._c("1;31", self._wrap(f"x {text}")), file=sys.stderr if not sys.stdout.isatty() else sys.stdout)

    def success(self, text: str) -> None:
        print(self._c("1;32", self._wrap(f"v {text}")))

    def confirm(self, question: str, default: bool = False) -> bool:
        if self.assume_yes:
            self.info(f"{question} -> {self.t('ui.yes')} (--yes)")
            return True
        yes_letters = self.t("ui.yes_letters").lower()
        hint = self.t("ui.yes_no_hint_default_yes") if default else self.t("ui.yes_no_hint_default_no")
        while True:
            try:
                answer = input(self._wrap(f"{question} {hint} ")).strip().lower()
            except EOFError:
                return default
            except KeyboardInterrupt:
                print()
                raise Cancelled() from None
            if not answer:
                return default
            if answer[0] in yes_letters:
                return True
            if answer[0] in self.t("ui.no_letters").lower():
                return False

    def choose(self, question: str, options: list[tuple[str, str]], default: str | None = None) -> str:
        if not options:
            raise Cancelled()
        if len(options) == 1:
            return options[0][0]
        if self.assume_yes and default is not None:
            return default
        print(self._wrap(question))
        for i, (_key, label) in enumerate(options, 1):
            print(self._wrap(f"  {i}) {label}", ""))
        keys = [k for k, _ in options]
        default_idx = keys.index(default) + 1 if default in keys else None
        prompt = self.t("ui.choice_prompt", max=len(options))
        if default_idx:
            prompt += f" [{default_idx}]"
        while True:
            try:
                answer = input(prompt + " ").strip()
            except EOFError:
                if default_idx:
                    return default  # type: ignore[return-value]
                raise Cancelled() from None
            except KeyboardInterrupt:
                print()
                raise Cancelled() from None
            if not answer and default_idx:
                return default  # type: ignore[return-value]
            if answer.isdigit() and 1 <= int(answer) <= len(options):
                return keys[int(answer) - 1]

    def ask_secret(self, prompt: str) -> str:
        try:
            return getpass.getpass(prompt + " ")
        except (EOFError, KeyboardInterrupt):
            raise Cancelled() from None


class NonInteractiveUI(ConsoleUI):
    """Used when stdin is not a terminal: never blocks on input."""

    interactive = False

    def confirm(self, question: str, default: bool = False) -> bool:
        decision = True if self.assume_yes else False
        self.info(f"{question} -> {self.t('ui.yes') if decision else self.t('ui.no')}")
        return decision

    def choose(self, question: str, options: list[tuple[str, str]], default: str | None = None) -> str:
        if len(options) == 1:
            return options[0][0]
        if default is not None:
            return default
        raise NeedsChoice(question)

    def ask_secret(self, prompt: str) -> str:
        raise NeedsChoice(prompt)


class WhiptailUI(ConsoleUI):
    """Dialog boxes for the bootable ISO. Falls back to console text output for plain messages."""

    def __init__(self, t: Translator, assume_yes: bool = False):
        super().__init__(t, assume_yes, color=True)
        self.binary = shutil.which("whiptail") or "whiptail"
        self.backtitle = "winbootfix"

    def _size(self, text: str, extra: int = 8) -> tuple[int, int]:
        cols, lines = shutil.get_terminal_size((80, 25))
        width = max(50, min(cols - 4, 78))
        wrapped = sum(max(1, len(textwrap.wrap(p, width - 4)) if p else 1) for p in text.split("\n"))
        height = max(8, min(lines - 2, wrapped + extra))
        return height, width

    def _run(self, args: list[str]) -> tuple[int, str]:
        cmd = [self.binary, "--backtitle", self.backtitle] + args
        proc = subprocess.run(cmd, stderr=subprocess.PIPE, text=True, check=False)
        return proc.returncode, proc.stderr.strip()

    def show_text(self, title: str, text: str) -> None:
        h, w = self._size(text, 6)
        cols, lines = shutil.get_terminal_size((80, 25))
        if h >= lines - 2:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as fh:
                fh.write(text)
                name = fh.name
            try:
                self._run(["--title", title, "--ok-button", self.t("ui.ok"), "--scrolltext",
                           "--textbox", name, str(lines - 2), str(w)])
            finally:
                os.unlink(name)
        else:
            self._run(["--title", title, "--ok-button", self.t("ui.ok"), "--msgbox", text, str(h), str(w)])

    def confirm(self, question: str, default: bool = False) -> bool:
        if self.assume_yes:
            return True
        h, w = self._size(question)
        args = ["--title", self.t("ui.confirm_title"), "--yes-button", self.t("ui.yes"),
                "--no-button", self.t("ui.no")]
        if not default:
            args.append("--defaultno")
        code, _ = self._run(args + ["--yesno", question, str(h), str(w)])
        if code == 255:
            raise Cancelled()
        return code == 0

    def choose(self, question: str, options: list[tuple[str, str]], default: str | None = None) -> str:
        if len(options) == 1:
            return options[0][0]
        h, w = self._size(question, 8 + len(options))
        listh = min(len(options), max(3, h - 8))
        args = ["--title", self.t("ui.choose_title"), "--ok-button", self.t("ui.ok"),
                "--cancel-button", self.t("ui.back"), "--notags"]
        if default:
            args += ["--default-item", default]
        args += ["--menu", question, str(h), str(w), str(listh)]
        for key, label in options:
            args += [key, label]
        code, out = self._run(args)
        if code != 0 or not out:
            raise Cancelled()
        return out

    def ask_secret(self, prompt: str) -> str:
        h, w = self._size(prompt)
        code, out = self._run(["--title", self.t("ui.secret_title"), "--ok-button", self.t("ui.ok"),
                               "--cancel-button", self.t("ui.back"), "--passwordbox", prompt, str(h), str(w)])
        if code != 0:
            raise Cancelled()
        return out


def make_ui(t: Translator, assume_yes: bool, mode: str = "auto", color: bool | None = None) -> UI:
    if mode == "whiptail" and shutil.which("whiptail") and sys.stdin.isatty():
        return WhiptailUI(t, assume_yes)
    if not sys.stdin.isatty():
        return NonInteractiveUI(t, assume_yes, color=color)
    return ConsoleUI(t, assume_yes, color=color)
