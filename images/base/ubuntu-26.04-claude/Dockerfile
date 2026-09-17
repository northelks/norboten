# The claude track's base image: the Ubuntu 26.04 container baseline plus Claude Code, pinned.
#
# Built on the learner's machine the first time a claude lab starts (docs/lab-spec.md §3), with
# this directory as the build context. Claude Code is the native binary of one release, checked
# against the sha256 its release manifest publishes; `claude` on the PATH is `claude-offline`,
# which points it at a scripted model on 127.0.0.1 (fake_anthropic.py, a copy of
# automation/stand_ins/fake_anthropic.py that a test keeps identical). No lab needs a token or
# the network once the image is built.
#
# Keep the baseline in step with images/base/ubuntu-26.04-container/Dockerfile.
FROM ubuntu:26.04

ARG CLAUDE_VERSION=2.1.270
ARG CLAUDE_SHA256_ARM64=7bf9f33acc124df9abccf6f2366397a82a740378d535fa12d426fa77fdbc9946
ARG CLAUDE_SHA256_X64=3a624a5a7cd79bbad4d32bd7db36f1197ecf458bc5bf1e2aed81834a01ad3ef0

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      acl bash-completion ca-certificates cron curl file git iproute2 jq less lsof man-db nano \
      nginx procps psmisc python3 python3-yaml ripgrep rsync sudo vim-tiny xz-utils \
 && rm -f /etc/nginx/sites-enabled/default \
 && rm -rf /var/lib/apt/lists/*

RUN case "$(uname -m)" in \
      aarch64|arm64) platform=linux-arm64; sum="$CLAUDE_SHA256_ARM64" ;; \
      x86_64|amd64) platform=linux-x64; sum="$CLAUDE_SHA256_X64" ;; \
      *) echo "no Claude Code build for $(uname -m)" >&2; exit 1 ;; \
    esac \
 && mkdir -p /opt/claude \
 && curl -fsSL --retry 3 -o /opt/claude/claude \
      "https://downloads.claude.ai/claude-code-releases/${CLAUDE_VERSION}/${platform}/claude" \
 && echo "${sum}  /opt/claude/claude" | sha256sum -c - \
 && chmod 755 /opt/claude/claude

COPY fake_anthropic.py claude_lab.py /usr/local/lib/norboten/
COPY claude-offline /usr/local/bin/claude

RUN chmod 755 /usr/local/bin/claude \
 && mkdir -p /etc/norboten /var/lib/norboten \
 && chmod 700 /var/lib/norboten \
 && printf '%s\n' "{\"id\": \"ubuntu-26.04-claude\", \"distro\": \"Ubuntu 26.04 LTS + Claude Code ${CLAUDE_VERSION}, container\", \"init\": \"none\", \"pkg\": \"apt\", \"mac\": \"none\", \"version\": \"1\"}" \
      > /etc/norboten/base.json \
 && printf '%s\n' \
      '# Norboten: append shell history after every command, so the tutor can see what was tried.' \
      'if [ -n "${BASH_VERSION:-}" ] && [ -z "${NORBOTEN_HISTORY:-}" ]; then' \
      '    NORBOTEN_HISTORY=1' \
      '    shopt -s histappend' \
      '    HISTSIZE=10000' \
      '    HISTFILESIZE=20000' \
      '    HISTTIMEFORMAT="%F %T "' \
      '    PROMPT_COMMAND="history -a${PROMPT_COMMAND:+; $PROMPT_COMMAND}"' \
      'fi' > /etc/profile.d/norboten-history.sh \
 && echo '[ -r /etc/profile.d/norboten-history.sh ] && . /etc/profile.d/norboten-history.sh' >> /etc/bash.bashrc \
 && echo 'root:norboten' | chpasswd

# The learner: a login shell and passwordless sudo, as the VM images give the Lima user. The
# image's own `ubuntu` account goes first: a lab VM has none, and the learner gets its uid 1000.
RUN userdel --remove ubuntu 2>/dev/null; useradd --create-home --shell /bin/bash learner \
 && printf 'learner ALL=(ALL) NOPASSWD: ALL\n' > /etc/sudoers.d/10-learner \
 && chmod 440 /etc/sudoers.d/10-learner \
 && git config --system user.name learner \
 && git config --system user.email learner@lab.norboten.org \
 && git config --system init.defaultBranch main

WORKDIR /home/learner
# PID 1 does nothing but wait: every shell, break, check and solution arrives through `exec`.
CMD ["sleep", "infinity"]
