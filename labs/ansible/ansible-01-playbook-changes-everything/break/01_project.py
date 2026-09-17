"""A shell-task playbook with a play-level port override, already run twice."""

import os
import shutil


def apply(ctx):
    src = os.path.join(ctx.lab_dir, "files", "project")
    if not os.path.exists("/srv/ansible/site.yml"):
        shutil.copytree(src, "/srv/ansible", dirs_exist_ok=True)
        for _ in range(2):  # it has been run before, more than once
            ctx.run(
                "cd /srv/ansible && ansible-playbook site.yml",
                check=True,
                timeout=55,
                env={
                    "ANSIBLE_NOCOLOR": "1",
                    "LC_ALL": "C.UTF-8",
                },  # Ansible refuses a non-UTF-8 locale
            )
