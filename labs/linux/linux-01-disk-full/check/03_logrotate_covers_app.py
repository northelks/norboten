import glob
import re

# A path inside /var/log/app, and not a file whose name merely starts with it: Ubuntu ships
# /etc/logrotate.d/apport for /var/log/apport.log, which sorts before any rule a learner writes.
LEDGER_PATH = re.compile(r"/var/log/app(?:/|\s|$)")


def _stanza(text):
    # the { ... } block whose header names a /var/log/app path
    for m in re.finditer(r"([^{}]*?)\{([^}]*)\}", text, re.S):
        if LEDGER_PATH.search(m.group(1)):
            return m.group(2)
    return None


def check(ctx):
    for conf in ["/etc/logrotate.conf", *sorted(glob.glob("/etc/logrotate.d/*"))]:
        text = ctx.read(conf) or ""
        body = _stanza(text)
        if body is None:
            continue
        evidence = f"{conf}:\n{text[:1500]}"
        if not re.search(r"^\s*(size|maxsize|daily|weekly|hourly|monthly)\b", body, re.M):
            return ctx.failed(
                "The rotation rule for the ledger log has no size or time limit.", evidence
            )
        if not re.search(r"^\s*(copytruncate|postrotate)\b", body, re.M):
            return ctx.failed(
                "After rotation, ledger would keep writing to the old, rotated file.", evidence
            )
        dry = ctx.run(["logrotate", "-d", conf])
        if dry.code != 0 or "ledger.log" not in dry.text:
            return ctx.failed("logrotate rejects the rule for the ledger log.", dry.text[-2000:])
        return ctx.passed(f"{conf} rotates the ledger log.", evidence)
    return ctx.failed("No logrotate rule covers the ledger log.")
