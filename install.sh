#!/bin/sh
# Norboten installer.
#
#   curl -fsSL https://norboten.org/install.sh | sh
#
# What it does, in order, and nothing else:
#   1. checks this is macOS or Linux on x86_64 or arm64;
#   2. says what it is about to do and asks once;
#   3. installs uv (https://docs.astral.sh/uv/) into ~/.local/bin if it is not already on PATH;
#   4. installs norboten from PyPI as a uv tool, with its own Python 3.12 if the system has none;
#   5. opens norboten. Its setup screen checks the machine, installs QEMU with the system's package
#      manager after asking, and starts the first lab. Nothing here uses sudo.
#
# Everything norboten writes later lives in ~/.norboten. `norboten update` updates it and
# `norboten uninstall` removes it all.
#
# Environment:
#   NORBOTEN_VERSION=0.2.0    install that version instead of the newest
#   NORBOTEN_EXTRAS=pdf       install optional extras too (pdf: journal export, needs pango)
#   NORBOTEN_YES=1            do not ask (for unattended installs)
#   NORBOTEN_NO_LAUNCH=1      do not open norboten at the end
#   NORBOTEN_FIND_LINKS=DIR   also look for wheels in DIR (testing a release before it is published)

set -eu

# Everything is inside main, called on the last line: if the download is cut short, the shell has
# nothing half-defined to run.

if [ -t 2 ]; then
    BOLD=$(printf '\033[1m') GREEN=$(printf '\033[32m')
    RED=$(printf '\033[31m') DIM=$(printf '\033[2m') RESET=$(printf '\033[0m')
else
    BOLD='' GREEN='' RED='' DIM='' RESET=''
fi

say() { printf '%s[ norboten ]%s %s\n' "$GREEN" "$RESET" "$*" >&2; }
die() {
    printf '%s[ norboten ]%s %s%s%s\n' "$GREEN" "$RESET" "$RED" "$*" "$RESET" >&2
    exit 1
}
has() { command -v "$1" >/dev/null 2>&1; }

# A terminal to ask questions on. stdin is the script itself when piped from curl.
tty_available() { [ -r /dev/tty ] && [ -w /dev/tty ] && (: </dev/tty) 2>/dev/null; }

confirm() { # confirm "question" -> 0 for yes; with no terminal to ask on, yes
    if [ "${NORBOTEN_YES:-}" = "1" ] || ! tty_available; then
        return 0
    fi
    printf '%s[ norboten ]%s %s %s[Y/n]%s ' "$GREEN" "$RESET" "$1" "$DIM" "$RESET" >/dev/tty
    read -r answer </dev/tty || answer=n
    case "$answer" in
        "" | y | Y | yes | YES) return 0 ;;
        *) return 1 ;;
    esac
}

detect_platform() {
    OS=$(uname -s)
    ARCH=$(uname -m)
    case "$OS" in
        Darwin) OS=macos ;;
        Linux) OS=linux ;;
        MINGW* | MSYS* | CYGWIN*)
            die "Windows is not supported for local labs; run this inside a WSL2 distribution with nested virtualization."
            ;;
        *) die "unsupported operating system: $OS" ;;
    esac
    case "$ARCH" in
        x86_64 | amd64) ARCH=x86_64 ;;
        arm64 | aarch64) ARCH=aarch64 ;;
        *) die "unsupported CPU architecture: $ARCH (labs need x86_64 or arm64)" ;;
    esac
    say "platform: $OS on $ARCH"
}

ensure_uv() {
    if has uv; then
        say "uv: $(uv --version 2>/dev/null)"
        return
    fi
    for candidate in "${XDG_BIN_HOME:-}" "$HOME/.local/bin" "$HOME/.cargo/bin"; do
        if [ -n "$candidate" ] && [ -x "$candidate/uv" ]; then
            PATH="$candidate:$PATH"
            export PATH
            say "uv: $(uv --version 2>/dev/null) (in $candidate, not on PATH yet)"
            return
        fi
    done
    say "installing uv (astral.sh/uv) into ~/.local/bin"
    if has curl; then
        curl -LsSf https://astral.sh/uv/install.sh | sh >&2
    elif has wget; then
        wget -qO- https://astral.sh/uv/install.sh | sh >&2
    else
        die "neither curl nor wget is installed"
    fi
    PATH="${XDG_BIN_HOME:-$HOME/.local/bin}:$PATH"
    export PATH
    has uv || die "uv was installed but cannot be found; open a new terminal and run this again"
}

package_spec() {
    spec=norboten
    if [ -n "${NORBOTEN_EXTRAS:-}" ]; then
        spec="norboten[${NORBOTEN_EXTRAS}]"
    fi
    if [ -n "${NORBOTEN_VERSION:-}" ]; then
        spec="${spec}==${NORBOTEN_VERSION}"
    fi
    echo "$spec"
}

summary() {
    printf '\n%sThis will:%s\n' "$BOLD" "$RESET" >&2
    if has uv; then
        printf '  - use uv, already installed: %s\n' "$(command -v uv)" >&2
    else
        printf '  - install uv into %s (astral.sh/uv)\n' "${XDG_BIN_HOME:-$HOME/.local/bin}" >&2
    fi
    printf '  - install %s from PyPI as a uv tool, with its own Python 3.12\n' "$(package_spec)" >&2
    printf '  - open norboten: its setup screen checks this machine and offers to install QEMU\n' >&2
    printf '%s  Nothing outside your home directory changes without another question.%s\n\n' \
        "$DIM" "$RESET" >&2
    confirm "Proceed?" || die "cancelled; nothing was installed"
}

install_norboten() {
    spec=$(package_spec)
    say "installing $spec"
    if [ -n "${NORBOTEN_FIND_LINKS:-}" ]; then
        uv tool install --upgrade --python 3.12 --find-links "$NORBOTEN_FIND_LINKS" "$spec" >&2
    else
        uv tool install --upgrade --python 3.12 "$spec" >&2
    fi
    # NO_COLOR: a shell with FORCE_COLOR set makes uv paint even a captured path, and the escapes
    # would end up inside BIN_DIR.
    BIN_DIR=$(NO_COLOR=1 uv tool dir --bin)
    NORBOTEN="$BIN_DIR/norboten"
    [ -x "$NORBOTEN" ] || die "norboten was installed but $NORBOTEN is missing"
    say "$("$NORBOTEN" --version) in $BIN_DIR"
    case ":$PATH:" in
        *":$BIN_DIR:"*) ;;
        *)
            uv tool update-shell >/dev/null 2>&1 || true
            PATH_HINT=1
            ;;
    esac
}

main() {
    detect_platform
    summary
    ensure_uv
    PATH_HINT=0
    install_norboten

    if [ "$PATH_HINT" = 1 ]; then
        say "added $BIN_DIR to your shell's PATH; new terminals will find ${BOLD}norboten${RESET}"
    fi
    if [ "${NORBOTEN_NO_LAUNCH:-}" = "1" ] || ! tty_available; then
        say "done. Run ${BOLD}norboten${RESET} to start."
        return
    fi
    say "done. Opening norboten — its setup screen takes it from here."
    exec "$NORBOTEN" </dev/tty >/dev/tty 2>&1
}

main "$@"
