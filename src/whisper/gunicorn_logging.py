"""Gunicorn logger that keeps full secret IDs out of its logs.

Secret IDs are the random part of share links. They appear in request paths
(and potentially the Referer header), which gunicorn writes to the access log
and, at DEBUG level, to the error log.
"""

from gunicorn.glogging import Logger

from whisper import redact_secret_ids


def _redact_message(msg, args):
    if args:
        try:
            msg = msg % args
        except (TypeError, ValueError):
            msg = f"{msg} {args}"
    return redact_secret_ids(str(msg))


class RedactingLogger(Logger):
    def atoms(self, resp, req, environ, request_time):
        atoms = super().atoms(resp, req, environ, request_time)
        return {
            key: redact_secret_ids(value) if isinstance(value, str) else value
            for key, value in atoms.items()
        }

    def debug(self, msg, *args, **kwargs):
        super().debug(_redact_message(msg, args), **kwargs)

    def info(self, msg, *args, **kwargs):
        super().info(_redact_message(msg, args), **kwargs)

    def warning(self, msg, *args, **kwargs):
        super().warning(_redact_message(msg, args), **kwargs)

    def error(self, msg, *args, **kwargs):
        super().error(_redact_message(msg, args), **kwargs)

    def exception(self, msg, *args, **kwargs):
        super().exception(_redact_message(msg, args), **kwargs)
