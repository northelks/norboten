# Write the Report

Operations wants a quick way to see who is hammering the web server. Write
**`/usr/local/bin/top-talkers`**, a **Bash** script, to this specification. A sample log is in
`/srv/logs/access.log`.

```
top-talkers [-n N] FILE
```

- `FILE` is an access log in common log format: the first field of each line is the client
  address.
- Print the **N** busiest client addresses (default **5**), one per line, as `<count> <address>`
  — a single space between them.
- Order by count, highest first. When counts are equal, order by address as plain text
  (byte order: `10.0.0.10` before `10.0.0.9`).
- Ignore empty lines and lines that start with `#`.
- `-n` takes a positive whole number. Anything else: print `top-talkers: invalid count` to
  stderr and exit with status **2**.
- If `FILE` is missing or unreadable: print `top-talkers: cannot read FILE` (with the actual name)
  to stderr and exit with status **1**.
- An empty log, or one with only comments: print nothing, exit **0**.
- Bash and the standard tools only — no Python, Perl, Ruby, PHP or Node.

Your script is graded by running it against logs you have not seen, including every edge case
above.
