---
title: Text is bytes plus an encoding, and nobody else knows which one
topics: [python, linux-basics]
minutes: 35
---

A file on disk is bytes. "Text" is what you get when bytes are decoded with an encoding, and the
file does not carry that encoding anywhere: not in its bytes, not in its name, not in its metadata.
Somebody has to know. In this lab the somebody is a README and a naming convention — the old Windows
tool writes cp1252 and says so in the file name — and the program ignores both, so it decodes
everything with whatever the machine's locale happens to be.

That works for years, because most names are ASCII and ASCII is a subset of both. It stops working
the day a member called Ruiz Peña joins. The interesting part is what happens next: the quick fix
everyone reaches for, `errors="ignore"`, makes the crash go away and turns the name into *Ruiz Pea*.

## What you should be able to do after this

- Say what `open()` uses as an encoding when you do not give it one, and why that is a machine
  property rather than a file property.
- Read a UnicodeDecodeError: which codec, which byte, which position.
- Choose an encoding per file from what is actually known about it, and say why `errors="ignore"`
  and `errors="replace"` are data loss rather than error handling.
- State the encoding when writing, so that output does not depend on the caller's locale.
- Write the output file atomically, so a failed run leaves the previous summary in place.

## The mechanism

### `open()` has an encoding, whether or not you name one

`open(path)` in text mode decodes bytes with `locale.getpreferredencoding(False)` — the encoding of
the machine's locale at the time the process started. The same program on the same file gives
different results on a machine with `LANG=en_GB.UTF-8`, on one with `LC_ALL=C`, and on a Windows box
with cp1252. Nothing about the file is involved.

Modern Linux distributions make this look harmless: Ubuntu's default locale is UTF-8, and Python
even coerces the bare `C` locale to `C.UTF-8` (PEP 538) so that a service started by systemd without
`LANG` still gets UTF-8. Under `LC_ALL=C` with that coercion turned off, the encoding is ASCII and
*any* non-ASCII byte fails. `PYTHONUTF8=1` (UTF-8 mode) is the other direction: it ignores the locale
and uses UTF-8 everywhere.

The lesson is not "which default does my Python use", but that a default exists at all. A program
that reads files written by other systems states the encoding for each one.

### Reading the error

```
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xf1 in position 17: invalid continuation byte
```

Four facts: the codec that was used (`utf-8`), the byte it choked on (`0xf1`), where it is
(position 17 of that read), and why (in UTF-8, `0xf1` starts a four-byte sequence and what followed
was not a continuation byte). `0xf1` is `ñ` in cp1252 and in latin-1. `file` says the same thing
more loosely: `ISO-8859 text` for the old export, `Unicode text, UTF-8 text` for the new one.

### The `errors=` argument is a policy, not a fix

`open(..., errors=…)` decides what happens to bytes that do not decode:

- `strict` (the default) raises — the program stops and somebody finds out;
- `ignore` drops them — `Ruiz Peña` becomes `Ruiz Pea`, silently, for ever;
- `replace` substitutes U+FFFD — `Ruiz Pe�a`, equally silently;
- `surrogateescape` keeps the raw bytes in a lossless but non-text form, for round-tripping data you
  do not have to interpret (file names, for example).

None of them makes a wrongly decoded file right. They decide what to lose. The right question is
which encoding the file is in, and here the file name answers it.

### Writing has the same problem, in the other direction

`open(path, "w")` encodes with the locale's encoding too, and raises `UnicodeEncodeError` on a
character it cannot represent. So a summary written on a machine with a non-UTF-8 locale is either a
crash or a file in an encoding nobody expected — and this lab's grader checks exactly that, by
running the report with `LC_ALL=C`. `encoding="utf-8"` on the way out makes the output a property of
the program rather than of the machine.

`csv` needs one more thing: open the file with `newline=""`, so the module controls line endings.
(The summary here therefore ends up with the CSV standard's CRLF line terminators, which is what
`file` reports.)

### A failed run should not destroy the last good summary

`open(OUT, "w")` truncates before anything is written, so a run that fails half way leaves an empty
summary. Writing to a temporary file in the same directory and `os.replace()`-ing it over the target
is atomic, so readers see the old file or the new one and never a partial one — the same shape as
`mv` in a shell script.

## A failure, walked through

Run on the lab's own machine: `ubuntu-26.04-devops`, Python 3.14.4, before any change.

The unit's run, and the last lines of its traceback:

```console
$ sudo systemctl start members-report.service; sudo journalctl -u members-report.service -b --no-pager -o cat | tail -5
  File "<frozen codecs>", line 325, in decode
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xf1 in position 17: invalid continuation byte
members-report.service: Main process exited, code=exited, status=1/FAILURE
members-report.service: Failed with result 'exit-code'.
Failed to start members-report.service - Members per city, for the membership office.
```

What the directory says about itself, and what `file` sees:

```console
$ ls /srv/members; cat /srv/members/README
README
legacy-2026-09.cp1252.csv
new-2026-09.csv
Exports in this directory
-------------------------
*.cp1252.csv  the old Windows tool (code page 1252)
*.csv         everything else: UTF-8
$ file /srv/members/*.csv
/srv/members/legacy-2026-09.cp1252.csv: ISO-8859 text
/srv/members/new-2026-09.csv:           Unicode text, UTF-8 text
```

The same file, read four ways — the default, the right encoding, and the two lenient ones:

```console
$ python3 -c "print(open('/srv/members/legacy-2026-09.cp1252.csv', encoding='utf-8').read())" 2>&1 | tail -2
  File "<frozen codecs>", line 325, in decode
UnicodeDecodeError: 'utf-8' codec can't decode byte 0xf1 in position 17: invalid continuation byte
$ python3 -c "print(open('/srv/members/legacy-2026-09.cp1252.csv', encoding='cp1252').read())"
name,city
Ruiz Peña,Málaga
Anaïs Fabre,Nîmes
$ python3 -c "print(open('/srv/members/legacy-2026-09.cp1252.csv', encoding='utf-8', errors='ignore').read())"
name,city
Ruiz Pea,Mlaga
Anas Fabre,Nmes
$ python3 -c "print(open('/srv/members/legacy-2026-09.cp1252.csv', encoding='utf-8', errors='replace').read())"
name,city
Ruiz Pe�a,M�laga
Ana�s Fabre,N�mes
```

That third output is the "fix" that shipped once: no error, and every accented letter gone. The
locale that decides the default is visible from Python, and a service gets the same one here:

```console
$ python3 -c "import locale,sys; print(locale.getpreferredencoding(False), sys.getdefaultencoding())"
UTF-8 utf-8
$ sudo systemd-run --wait --pipe -q python3 -c "import locale; print('service locale encoding:', locale.getpreferredencoding(False))"
service locale encoding: UTF-8
```

Take the locale away and the same program on the same UTF-8 file fails, in both directions:

```console
$ LC_ALL=C PYTHONCOERCECLOCALE=0 PYTHONUTF8=0 python3 /tmp/show.py /srv/members/new-2026-09.csv 2>&1 | tail -3
    return codecs.ascii_decode(input, self.errors)[0]
           ~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^
UnicodeDecodeError: 'ascii' codec can't decode byte 0xc3 in position 28: ordinal not in range(128)
$ LC_ALL=C PYTHONCOERCECLOCALE=0 PYTHONUTF8=0 python3 /tmp/write.py /tmp/out.txt 2>&1 | tail -2
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^
UnicodeEncodeError: 'ascii' codec can't encode character '\xfc' in position 1: ordinal not in range(128)
```

(`/tmp/show.py` prints a line of the file it is given; `/tmp/write.py` writes `München` to a file.)

After the fix — an encoding chosen per file from its name, `encoding="utf-8"` on the output, and the
summary written through a temporary file — both exports are read and every name survives:

```console
$ sudo systemctl start members-report.service; sudo cat /var/lib/members/summary.csv
city,members
Kraków,1
Málaga,1
München,1
Nîmes,1
names,Ruiz Peña Anaïs Fabre Anna Kowalska Jonas Müller
$ sudo file /var/lib/members/summary.csv
/var/lib/members/summary.csv: Unicode text, UTF-8 text, with CRLF line terminators
```

## Common wrong turns

- **`errors="ignore"` or `errors="replace"`.** The crash goes away and the data is wrong forever.
  The lab's second check exists to catch exactly this.
- **Decoding everything as latin-1 "because it never fails".** True and useless: latin-1 maps every
  byte to a character, so a UTF-8 file silently becomes mojibake (`MÃ¼nchen`).
- **Setting `LANG`/`LC_ALL` in the unit.** It hides the problem on this machine and moves it to the
  next one; the program still has no idea what its inputs are.
- **`PYTHONUTF8=1` as the fix.** It makes the *default* UTF-8, which is right for the new exports and
  still wrong for the cp1252 one.
- **Guessing with `chardet` and friends.** Reasonable when nothing is known; here the encoding is
  documented in the README and in the file name.
- **Forgetting the output.** A run that reads correctly and writes in the locale's encoding just
  moves the problem downstream.

## Cheat sheet

```python
open(path, encoding="utf-8")            # say it, every time, in and out
open(path, encoding="cp1252")           # what the old Windows tool writes
open(path, "w", encoding="utf-8", newline="")   # csv: let the module choose line endings
# errors=: strict (raise) · ignore (drop) · replace (U+FFFD) · surrogateescape (round-trip bytes)

import locale; locale.getpreferredencoding(False)   # the default open() would use
python3 -X utf8 …        # or PYTHONUTF8=1: ignore the locale, use UTF-8

# replace the output in one step
fd, tmp = tempfile.mkstemp(dir=os.path.dirname(out))
… ; os.replace(tmp, out)
```

```console
file export.csv                  # a first guess at the encoding
```

## Going deeper

- The Python documentation on [`open()`](https://docs.python.org/3/library/functions.html#open) and
  [error handlers](https://docs.python.org/3/library/codecs.html#error-handlers).
- PEP 538 (C locale coercion) and PEP 540 (UTF-8 mode), for what happens when a service starts with
  no locale.
- `man 1 file`, `man 7 charsets`.
- Joel Spolsky, *The Absolute Minimum Every Software Developer Absolutely, Positively Must Know
  About Unicode and Character Sets*.

## Review

1. Where does `open(path)` get its encoding from?

   > From the process's locale (`locale.getpreferredencoding(False)`), not from the file. The same
   > file gives different text on machines with different locales.

2. What do the four parts of `UnicodeDecodeError: 'utf-8' codec can't decode byte 0xf1 in position
   17: invalid continuation byte` tell you?

   > The codec that was used, the offending byte, where it was, and why it is invalid for that codec
   > — here a cp1252 `ñ` in a file being read as UTF-8.

3. Why is `errors="ignore"` the wrong answer to that error?

   > It drops every byte that does not decode, so the data is silently changed — `Ruiz Peña` becomes
   > `Ruiz Pea` — and no one finds out.

4. Why does reading everything as latin-1 never raise, and why is that not a solution?

   > latin-1 maps all 256 byte values to characters, so any byte decodes; a UTF-8 file then decodes
   > into the wrong characters, which is worse than an error.

5. What breaks when a program that writes UTF-8 text runs with `LC_ALL=C` and no encoding given?

   > Writing uses the locale's encoding — ASCII — so any non-ASCII character raises
   > `UnicodeEncodeError`, or, on a machine with another locale, the file is written in an encoding
   > readers do not expect.

6. Why write the summary to a temporary file and `os.replace()` it?

   > The direct `open(out, "w")` truncates the previous summary before the new one is written, so a
   > failure destroys it; the replace is atomic and keeps the last good file.
