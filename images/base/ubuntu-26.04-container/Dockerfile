# The container base image: the Ubuntu 26.04 lab baseline without a kernel, a boot or an init system.
#
# Built on the learner's machine the first time a container lab starts (docs/lab-spec.md §3), from
# this file alone — no build context — so it works from the copy an installed norboten carries.
# Keep it in step with images/base/ubuntu-26.04/vars.yml and ansible/roles/lab_baseline: the same
# tools, the same base.json facts (init "none"), the same shell history for the tutor.
FROM ubuntu:26.04

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      acl bash-completion ca-certificates cron curl file git less logrotate lsof man-db nano \
      procps psmisc python3 rsync sudo vim-tiny xz-utils \
 && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /etc/norboten /var/lib/norboten \
 && chmod 700 /var/lib/norboten \
 && printf '%s\n' '{"id": "ubuntu-26.04-container", "distro": "Ubuntu 26.04 LTS, container", "init": "none", "pkg": "apt", "mac": "none", "version": "1"}' \
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
 && chmod 440 /etc/sudoers.d/10-learner

WORKDIR /home/learner
# PID 1 does nothing but wait: every shell, break, check and solution arrives through `exec`.
CMD ["sleep", "infinity"]
