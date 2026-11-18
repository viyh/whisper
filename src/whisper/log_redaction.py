"""Keep full secret IDs out of every log line.

A secret ID is the random part of a share link. Call sites already log
short_id(...), but IDs also reach logs through paths no call site controls:
request paths in Flask's and gunicorn's error and access logs, exception
messages and tracebacks (file paths, object keys), and third-party libraries.

SecretIdRedactingFilter is attached to the log *handlers*, so it sees every
record those handlers write, whichever logger it came from, and shortens any
secret ID in the message, traceback, and stack info.
"""

import logging

from whisper import redact_secret_ids


class SecretIdRedactingFilter(logging.Filter):
    def filter(self, record):
        try:
            message = record.getMessage()
        except (TypeError, ValueError, KeyError):  # bad format args: keep what we can
            message = f"{record.msg} {record.args!r}"
        record.msg = redact_secret_ids(str(message))
        record.args = None

        if record.exc_info and not record.exc_text:
            # Render the traceback now so the formatter reuses this redacted
            # text instead of rendering the original.
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact_secret_ids(record.exc_text)
        if record.stack_info:
            record.stack_info = redact_secret_ids(record.stack_info)
        return True


def install_redaction(*loggers):
    """Attach the redacting filter to every handler of the given loggers."""
    for logger in loggers:
        for handler in logger.handlers:
            if not any(isinstance(f, SecretIdRedactingFilter) for f in handler.filters):
                handler.addFilter(SecretIdRedactingFilter())
