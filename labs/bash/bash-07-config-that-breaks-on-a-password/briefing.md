# The Config That Breaks on a Password

`myapp.service` renders its configuration before it starts: `render-config` fills the placeholders
`@DB_HOST@` and `@DB_PASSWORD@` in `/etc/myapp/app.conf.tmpl` from the shell assignments in
`/etc/myapp/secrets.env`, and writes `/etc/myapp/app.conf`. Then `myapp-login` logs in to the
database with that password.

The password was rotated this morning — the new one came from the password manager and contains a
`/`, an `&`, a `$` and a backslash. Since then `myapp` does not start. Someone fixed `app.conf` by
hand; it worked until the next restart. The security team also noticed that `app.conf` can be read
by every user on the machine.

What is expected, and graded — the grader runs `render-config` itself, through the
`RENDER_TEMPLATE`, `RENDER_VALUES` and `RENDER_OUT` variables the script already reads:

1. Every placeholder is replaced by its value exactly, whatever characters the value contains.
2. The rendered file can be read and written by its owner only.
3. When a value is missing from the values file, the script exits non-zero, names the missing value
   on standard error, and leaves the previous configuration exactly as it was.
4. `myapp.service` starts and logs in with the rotated password — and still does after a reboot.

You have root through `sudo`. The password itself stays as it is.
