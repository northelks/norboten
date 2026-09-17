#!/bin/sh
# Reference solution: the group, the existing files, what is created later, the outsider.
set -eu
usermod -aG reports carol

chgrp -R reports /srv/reports
chmod -R g+rwX,o-rwx /srv/reports
# new files inherit the directory's group
find /srv/reports -type d -exec chmod g+s {} +
# and the group keeps read/write on them whatever the author's umask (077 here)
setfacl -R -m g:reports:rwX /srv/reports
setfacl -R -d -m g:reports:rwX /srv/reports
