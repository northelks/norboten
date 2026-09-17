#!/bin/sh
set -eu
usermod -G devops kmorris
chmod 2770 /srv/project
home=$(getent passwd kmorris | cut -d: -f6)
sed -i 's/^umask 077$/umask 002/' "$home/.bash_profile"
sed -i 's/^%ops /%devops /' /etc/sudoers.d/devops
visudo -cf /etc/sudoers.d/devops
