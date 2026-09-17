#!/bin/sh
# Runs as root. NORBOTEN_LEARNER names the learner account.
set -eu
chmod o+r /srv/hello/message.txt
home=$(getent passwd "$NORBOTEN_LEARNER" | cut -d: -f6)
sed -n 's/^The secret word is: //p' /srv/hello/message.txt > "$home/reply.txt"
chown "$NORBOTEN_LEARNER" "$home/reply.txt"
