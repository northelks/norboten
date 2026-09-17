"""Setup — the first screen after the installer: what this machine still needs, one key for each,
then the first lab.

    ✓ platform        macos on aarch64
    ✗ qemu            QEMU is not installed
                      i  brew install qemu
    · lima            Lima 2.2.0, ~35 MB           p downloads it
    · image           alpine, 105 MB               p downloads it
    · account         not signed in (optional)     a signs in

It opens by itself once, on the first run (`settings.setup_done`), and again from System (`s`).
Commands that need a password run with the terminal handed over, after a yes.
"""

from __future__ import annotations

import subprocess

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, ProgressBar, Static

from norboten import settings
from norboten.tui import data
from norboten.tui.lab import handed_over
from norboten.tui.theme import AMBER, BG, DIM, GREEN, RED, STATUS_MARK, TEXT
from norboten.tui.widgets import TopBar

FIRST_LAB = "hello"
TODO = ("·", AMBER)


def run_command(command: str) -> int:
    """Run a fix in the real terminal, and keep its output on screen until Enter."""
    print(f"\n$ {command}\n", flush=True)
    code = subprocess.call(command, shell=True)
    verdict = "done" if code == 0 else f"failed (exit {code})"
    input(f"\n{verdict}. Enter returns to norboten ")
    return code


class SetupScreen(Screen[None]):
    BINDINGS = [
        Binding("i", "fix", "Run the fix"),
        Binding("p", "download", "Download"),
        Binding("a", "account", "Sign in"),
        Binding("enter", "first_lab", "Start the first lab"),
        Binding("escape", "later", "Later"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.downloading = False
        self.image_id = self._first_image()
        self.image_size: int | None = None
        self.message = Text()

    def compose(self) -> ComposeResult:
        yield TopBar()
        with VerticalScroll(id="setup-body"):
            yield Static(Text("Set up this machine", style=f"bold {GREEN}"), classes="title")
            yield Static(
                Text(
                    "Labs run in QEMU virtual machines. Fix what is marked, download what the "
                    "first lab needs, and start it.",
                    style=DIM,
                ),
                classes="subtitle",
            )
            yield Static(Text("checking this machine…", style=DIM), id="setup-list")
            yield ProgressBar(id="setup-bar", show_eta=True)
            yield Static("", id="setup-message")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#setup-bar").display = False
        self.show(self.app.findings)
        self._probe()

    # -- state ---------------------------------------------------------------------------------

    @staticmethod
    def _first_image() -> str | None:
        from norboten.labs import store as lab_store

        try:
            return lab_store.find(FIRST_LAB).manifest.base_images[0]
        except Exception:
            return None

    @work(thread=True, exclusive=True, group="setup-probe")
    def _probe(self) -> None:
        """The image's download size, or None if there is nowhere to download it from yet."""
        from norboten.images import store

        if self.image_id is None:
            return
        try:
            size = store.remote_size(self.image_id)
        except Exception:
            size = None
        self.image_size = size
        self.app.call_from_thread(self.show, self.app.findings)

    def _fixable(self, findings: list | None):
        return next((f for f in findings or () if f.status == "fail" and f.command), None)

    def show(self, findings: list | None) -> None:
        """Redraw from doctor's findings; the app calls this whenever doctor finishes."""
        from norboten import doctor
        from norboten.images import store
        from norboten.lima import install
        from norboten.models import format_size

        if findings is None or not self.is_mounted:
            return
        fixable = self._fixable(findings)
        out = Text()

        def row(mark: tuple[str, str], name: str, detail: str, key: str = "") -> None:
            out.append(f"{mark[0]} ", style=f"bold {mark[1]}")
            out.append(f"{name:<16}", style=f"bold {TEXT}")
            out.append(detail, style=TEXT)
            if key:
                out.append(f"   {key}", style=GREEN)
            out.append("\n")

        for f in findings:
            if f.name == "lima":
                continue  # its own row below, with the download
            row(STATUS_MARK[f.status], f.name, f.detail)
            if f is fixable:
                out.append(f"{'':18}i  {f.command}\n", style=f"bold {GREEN}")
            elif f.status != "ok" and f.fix:
                out.append(f"{'':18}→ {f.fix}\n", style=DIM)

        if install.is_installed():
            row(STATUS_MARK["ok"], "lima", f"Lima {install.LIMA_VERSION}, downloaded")
        else:
            row(TODO, "lima", f"Lima {install.LIMA_VERSION}, ~35 MB", "p downloads it")
        if self.image_id:
            local = store.cached(self.image_id)
            if local:
                row(STATUS_MARK["ok"], "image", f"{self.image_id}, downloaded")
            elif self.image_size:
                size = format_size(self.image_size)
                row(TODO, "image", f"{self.image_id}, {size}", "p downloads it")
            else:
                row(TODO, "image", f"{self.image_id}, downloads when the lab starts")
        if data.signed_in():
            row(STATUS_MARK["ok"], "account", "signed in")
        else:
            row(TODO, "account", "not signed in — optional, for ratings", "a signs in")

        ready = doctor.ready(findings)
        out.append("\n")
        if ready:
            out.append(" READY ", style=f"bold {BG} on {GREEN}")
            out.append(f"  Enter starts {FIRST_LAB} · Esc goes to the menu", style=DIM)
        else:
            out.append(" NOT READY ", style=f"bold {BG} on {RED}")
            out.append("  fix the items marked ✗ · Esc goes to the menu", style=DIM)
        self.query_one("#setup-list", Static).update(out)

    def say(self, message: str, style: str = "") -> None:
        self.query_one("#setup-message", Static).update(Text(message, style=style or DIM))
        self.app.note(f"setup: {message}", style)

    def recheck(self) -> None:
        main = self.app._main()
        if main is not None:
            main.action_doctor()

    # -- actions -------------------------------------------------------------------------------

    def action_fix(self) -> None:
        from norboten.tui.modals import ConfirmScreen

        finding = self._fixable(self.app.findings)
        if finding is None:
            self.say("nothing here has a command to run")
            return
        command = finding.command

        def confirmed(yes: bool | None) -> None:
            if not yes:
                return
            try:
                with handed_over(self.app):
                    code = run_command(command)
            except Exception as e:
                self.say(f"{command} failed: {e}", RED)
                return
            if code != 0:
                self.say(f"{command} exited with {code}", RED)
            elif "usermod" in command:
                self.say("added to the kvm group — log out and back in, then run norboten", AMBER)
            else:
                self.say(f"✓ {command}", GREEN)
            self.recheck()

        self.app.push_screen(
            ConfirmScreen(
                f"Run {command}?",
                "norboten steps aside while it runs; it may ask for your password.",
                danger=False,
            ),
            confirmed,
        )

    def action_download(self) -> None:
        if self.downloading:
            return
        self.downloading = True
        bar = self.query_one("#setup-bar", ProgressBar)
        bar.update(total=None, progress=0)
        bar.display = True
        self._download()

    @work(thread=True, exclusive=True, group="setup-download")
    def _download(self) -> None:
        from norboten.images import store
        from norboten.lima import install

        bar = self.query_one("#setup-bar", ProgressBar)
        call = self.app.call_from_thread

        def advance(n: int, total: int) -> None:
            def update() -> None:
                if total and bar.total != total:
                    bar.update(total=total, progress=0)
                bar.advance(n)

            call(update)

        try:
            if not install.is_installed():
                call(self.say, f"downloading Lima {install.LIMA_VERSION}")
                install.install(progress=advance)
            if self.image_id and self.image_size and not store.cached(self.image_id):
                call(bar.update, total=None, progress=0)
                call(self.say, f"downloading {self.image_id}")
                store.pull(self.image_id, progress=advance)
            call(self.say, "✓ downloaded", GREEN)
        except Exception as e:
            call(self.say, f"download failed: {e}", RED)
        finally:
            self.downloading = False
            call(setattr, bar, "display", False)
            call(self.recheck)

    def action_account(self) -> None:
        from norboten.tui.modals import SignInScreen

        if data.signed_in():
            self.say("already signed in")
            return
        self.app.push_screen(SignInScreen(), self._signed_in)

    def _signed_in(self, ok: bool | None) -> None:
        if ok:
            self.app.refresh_account()
        self.show(self.app.findings)

    def action_first_lab(self) -> None:
        from norboten import doctor
        from norboten.labs import store as lab_store
        from norboten.tui.lab import LabScreen

        findings = self.app.findings
        if findings is None:
            self.say("doctor is still checking this machine")
            return
        if not doctor.ready(findings):
            self.say("not ready yet: fix the items marked ✗ first", RED)
            return
        settings.save(setup_done=True)
        self.app.pop_screen()
        lab = LabScreen(lab_store.find(FIRST_LAB))
        self.app.push_screen(lab)
        lab.call_after_refresh(lab.action_start)

    def action_later(self) -> None:
        settings.save(setup_done=True)
        self.app.pop_screen()
        self.app.note("setup: s on System (8) opens it again")
