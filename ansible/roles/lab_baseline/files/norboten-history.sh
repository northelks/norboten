# Norboten: append shell history after every command, so the tutor can see what was tried.
if [ -n "${BASH_VERSION:-}" ] && [ -z "${NORBOTEN_HISTORY:-}" ]; then
    NORBOTEN_HISTORY=1
    shopt -s histappend
    HISTSIZE=10000
    HISTFILESIZE=20000
    HISTTIMEFORMAT="%F %T "
    PROMPT_COMMAND="history -a${PROMPT_COMMAND:+; $PROMPT_COMMAND}"
fi
