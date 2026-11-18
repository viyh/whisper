"""Gunicorn logger that keeps full secret IDs out of its logs.

Secret IDs are the random part of share links and appear in request paths and
the Referer header. This installs SecretIdRedactingFilter on gunicorn's error
and access log handlers. The Flask app logger shares those handlers (see
app.py), and whisper's module loggers propagate to it, so every line written
through them is redacted, tracebacks included.
"""

from gunicorn.glogging import Logger

from whisper.log_redaction import install_redaction


class RedactingLogger(Logger):
    def setup(self, cfg):
        super().setup(cfg)
        install_redaction(self.error_log, self.access_log)
