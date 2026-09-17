# The Service That Won't Stay Up

**notes** is a small internal web app on port **8080**. When someone starts it by hand it
sometimes comes up — and a few minutes later it is gone again. After a reboot it never comes back
at all. Colleagues opening `http://<server>:8080/` get an old page that says the service was
retired, or nothing.

The app runs as the `notes` user. Its notes live in `/srv/notes`. The server runs AppArmor, and
security wants it to stay that way.

What is expected, and graded:

1. notes is running, and starts at boot on its own.
2. If notes crashes, the system brings it back.
3. Port 8080 answers with the notes service, listing its notes.
4. notes can read its notes because AppArmor allows it — not because AppArmor was switched off.

You have root through `sudo`. Everything must still hold after a reboot.
