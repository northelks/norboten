---
title: A value is data; sed's replacement is code
topics: [bash, users-permissions]
minutes: 35
---

Filling placeholders in a template is the second thing every ops script learns to do, and `sed
s/@PLACEHOLDER@/$value/` is how almost everyone writes it. It works for a year, because the values
are host names and port numbers. Then a password comes out of the vault with a `/`, an `&` and a
backslash in it, and the render either fails or — worse — produces a configuration that is quietly
different from the value it was given.

The reason is not that sed is fragile. It is that `s/…/…/` is a small program, and pasting a value
into it makes the value part of that program. Exactly like SQL built by string concatenation, the
question is never "which characters do I escape", but "how do I keep data out of the code".

## What you should be able to do after this

- Name the characters that are special in sed's *replacement* text, and in its pattern and delimiter.
- Substitute a value into a template without letting the value become code, using bash's own
  `${var//pattern/replacement}`.
- Explain why `"$var"` inside `${t//@P@/"$var"}` matters.
- Make a file that holds a secret private from the moment it exists, with `umask` rather than a later
  `chmod`.
- Fail a render when a value is missing, with `${var:?message}`, and keep the previous file.
- Read a unit that fails in `ExecStartPre=`, and know why editing the rendered file by hand does not
  last.

## The mechanism

### What is special in a `s` command

`s/pattern/replacement/flags` has three layers of syntax, and each has its own special characters:

- the **delimiter** — `/` by default. Any `/` inside the pattern or the replacement ends the command
  early; the value `k3y/&Pa$$\1-vault` therefore turns into "unknown option to `s`". Another
  delimiter (`s|…|…|`) only moves the problem to whatever character you chose.
- the **replacement** — `&` stands for the whole matched text, `\1`…`\9` for capture groups, `\n`
  for a newline, and `\` escapes any of those. `a&b` renders as `a@P@b`, silently: the placeholder
  is put back in place of the ampersand.
- the **pattern** — a basic regular expression, where `.`, `*`, `[`, `^` and `$` are meta-characters.
  Placeholders such as `@DB_PASSWORD@` contain none of these, which is why the pattern side is not
  the part that breaks here.

The shell adds a layer of its own before sed sees anything: `"s/@P@/$p/"` is expanded by bash, so a
`$` or a backslash in the value has already been through the shell's quoting rules.

### Substituting without a language in between

Bash can replace text in a variable directly:

```bash
text=$(<"$TEMPLATE")
text=${text//@DB_PASSWORD@/"$password"}
```

`${var//pattern/replacement}` replaces every occurrence. The pattern is a *glob* pattern, not a
regular expression — a placeholder such as `@DB_PASSWORD@` has no glob characters, so it matches
literally. The replacement is **not** a pattern at all; the only character that means anything there
is `\`, and quoting the expansion (`"$password"`) makes even that literal. No delimiter, no `&`, no
`\1`: the value stays data.

`printf '%s\n' "$text" > file` then writes the result — `printf` with a `%s` format, never
`printf "$text"`, which would interpret `%` sequences in the data.

Other tools that keep data separate from code: `envsubst` (from gettext) for `$VAR` templates, `jq
--arg` for JSON, Python's `string.Template.substitute`, and any templating engine. The common shape
is: the value is passed as a value, not spliced into a program.

### A secret is private from its first byte

A new file's permissions are `0666` (or `0777` for programs) minus the process's `umask`. On this
machine the default is `0002`, so a shell redirection creates `0664` — readable by everyone. A
`chmod 600` afterwards closes the door, but the secret was already on disk and readable for the
moment in between, and any reader that opened it in that moment keeps its descriptor.

`umask 077` before the file is created means it is never readable by anyone else. Setting the mode
explicitly as well (`chmod 600`) covers the case where the file already existed. Writing to a
temporary file in the same directory and renaming it over the target keeps the previous
configuration when the render fails, and gives readers an atomic switch.

### Failing on a missing value

`. "$VALUES"` reads assignments from a file; if a name is not in it, the variable simply stays unset,
and under `set -u` it is an error only when it is *used* — by which time the output may already have
been truncated. `${DB_HOST:?DB_HOST is not set in $VALUES}` checks and reports in one step: with `set
-e`, a non-interactive shell exits, printing that message to standard error. Unsetting the names
before sourcing matters too, or a value inherited from the environment silently stands in for a
missing one.

### A unit that renders before it starts

`myapp.service` has `ExecStartPre=/usr/local/bin/render-config` and `ExecStart=/usr/local/bin/myapp-login`.
systemd runs the `ExecStartPre=` commands first and fails the unit if one of them fails. Here the
render *succeeded* — it exited 0 after sed's error — and the login failed, which is why the status
shows `ExecStartPre` green and `ExecStart` red. It also means that editing `/etc/myapp/app.conf` by
hand is pointless: the next start overwrites it.

## A failure, walked through

Run on the lab's own machine: `ubuntu-26.04-devops`, GNU bash 5.3.9, GNU sed 4.9, before any change.

```console
$ systemctl status myapp.service --no-pager -n 6 | head -12
× myapp.service - myapp, with its configuration rendered at start
     Loaded: loaded (/etc/systemd/system/myapp.service; enabled; preset: enabled)
     Active: failed (Result: exit-code) since Wed 2026-09-16 16:54:05 UTC; 114ms ago
    Process: 1176 ExecStartPre=/usr/local/bin/render-config (code=exited, status=0/SUCCESS)
    Process: 1179 ExecStart=/usr/local/bin/myapp-login (code=exited, status=1/FAILURE)
```

The render reported success and left an empty file, because the redirection truncated `app.conf`
before sed failed:

```console
$ sudo cat /etc/myapp/secrets.env; ls -l /etc/myapp/
DB_HOST=db.internal
DB_PASSWORD='k3y/&Pa$$\1-vault'
total 8
-rw-r--r-- 1 root root   0 Sep 16 16:54 app.conf
-rw-r--r-- 1 root root 151 Sep 16 16:54 app.conf.tmpl
-rw------- 1 root root  52 Sep 16 16:54 secrets.env
```

Two things to notice: `app.conf` is empty, and its mode is `0644` — the secrets file beside it is
`0600`. Running the substitution by hand shows what sed received:

```console
$ p='k3y/&Pa$$\1-vault'; printf 'password = @DB_PASSWORD@\n' | sed -e "s/@DB_PASSWORD@/$p/" ; echo "sed status: $?"
sed: -e expression #1, char 21: unknown option to `s'
sed status: 1
```

The `/` in the value ended the `s` command, and what followed was read as flags. A value with only
an `&` is worse, because it does not fail at all:

```console
$ p='a&b'; printf 'x = @P@\n' | sed -e "s/@P@/$p/"
x = a@P@b
```

The ampersand was replaced by the matched text, so the placeholder is back in the output and nobody
notices until the application uses it. The shell's own substitution has none of these layers:

```console
$ t='x = @P@'; p='k3y/&Pa$$\1-vault'; echo "${t//@P@/"$p"}"
x = k3y/&Pa$$\1-vault
$ umask
0002
```

That `umask` is why a redirected file is world-readable. After the fix — `${text//…}` in place of
sed, `${var:?}` for each value, `umask 077` with an explicit `chmod 600`, and a temporary file
renamed into place:

```console
$ sudo systemctl restart myapp.service; systemctl is-active myapp.service; sudo journalctl -u myapp.service -b --no-pager -o cat | tail -2
active
myapp: logged in to db.internal
Finished myapp.service - myapp, with its configuration rendered at start.
$ sudo ls -l /etc/myapp/app.conf; sudo cat /etc/myapp/app.conf
-rw------- 1 root root 157 Sep 16 16:54 /etc/myapp/app.conf
# myapp — rendered by render-config from app.conf.tmpl; edits here are overwritten
[database]
host = db.internal
user = myapp
password = k3y/&Pa$$\1-vault
$ sudo sh -c 'RENDER_VALUES=/dev/null RENDER_OUT=/tmp/out.conf render-config'; echo "status: $?"
/usr/local/bin/render-config: line 11: DB_HOST: DB_HOST is not set in /dev/null
status: 1
```

The password is in the file exactly as it is in the vault, the file is `0600`, and a values file
without `DB_HOST` fails by name.

## Common wrong turns

- **Escaping the value for sed.** `${value//\//\\/}` and friends: a new escape for every special
  character, in a specific order, and a bug the first time a value contains one you forgot. Do not
  build an escaper; stop generating code.
- **Changing the delimiter.** `s|@P@|$value|` moves the failure from `/` to `|`. Any delimiter can
  appear in a password.
- **Rotating the password to something "safe".** The brief says the password stays as it is, and so
  does reality: the value comes from a vault, and the next one will be worse.
- **`chmod 600` after writing.** The secret is world-readable while it is written. Set `umask 077`
  first.
- **Editing `/etc/myapp/app.conf`.** `ExecStartPre=` renders it again on the next start.
- **`set -u` alone for missing values.** It errors when the variable is used, after the output has
  been truncated, and says nothing about which file should have contained it.
- **`printf "$text"`.** A `%` in the data becomes a format directive. `printf '%s\n' "$text"`.

## Cheat sheet

```bash
text=$(<"$TEMPLATE")                       # read a file into a variable
text=${text//@DB_HOST@/"$DB_HOST"}         # literal replacement, no escaping needed
printf '%s\n' "$text" > "$tmp"             # never printf "$text"

unset DB_HOST DB_PASSWORD; . "$VALUES"     # no leftovers from the environment
: "${DB_HOST:?DB_HOST is not set in $VALUES}"

umask 077                                  # before creating anything that holds a secret
tmp=$(mktemp "$OUT.XXXXXX"); trap 'rm -f -- "$tmp"' EXIT
chmod 600 "$tmp"; mv -f -- "$tmp" "$OUT"

# sed's replacement: & = whole match, \1..\9 = groups, \ escapes, delimiter ends the command
systemctl status unit          # ExecStartPre= failures are shown separately from ExecStart=
```

## Going deeper

- `man 1 sed`, *The s Command*, for `&`, `\1` and the delimiter.
- `man 1 bash`, *Parameter Expansion*, for `${var//pattern/replacement}` and `${var:?word}`.
- `man 2 umask`, and `man 1 envsubst` for `$VAR` templates.
- `man 5 systemd.service`, `ExecStartPre=`.

## Review

1. Which three characters are special in sed's replacement text, and what does each mean?

   > `&` (the whole matched text), `\` (escape, and `\1`…`\9` for capture groups) and the delimiter
   > itself, which ends the replacement early.

2. Why does a value containing `&` produce wrong output rather than an error?

   > `&` is replaced by the text that matched — the placeholder — so the render succeeds and the
   > result silently contains the placeholder instead of the value.

3. Why is `${text//@P@/"$password"}` safe where sed is not?

   > The replacement side of that expansion is not a pattern; quoting the expansion makes even a
   > backslash literal, so the value cannot become syntax.

4. Why is `chmod 600` after writing a secret not enough?

   > The file exists with the umask's permissions while it is being written, so anyone can read it in
   > that window, and a reader that opened it keeps access.

5. What does `: "${DB_HOST:?DB_HOST is not set}"` do when `DB_HOST` is unset?

   > It writes the message to standard error and exits a non-interactive shell with a non-zero
   > status, before anything is written.

6. The unit's status shows `ExecStartPre` as success and `ExecStart` as failure. What does that tell
   you, and why is editing `app.conf` by hand useless?

   > The render exited 0 but produced a configuration the application rejects; and `ExecStartPre=`
   > runs on every start, so the rendered file is overwritten each time.
