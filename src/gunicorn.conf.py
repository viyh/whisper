"""Gunicorn settings for the container.

Whisper must run behind a TLS-terminating proxy (Cloud Run, a cloud load
balancer, Caddy, Traefik, ...), which also absorbs slow clients. Gunicorn
should not be exposed directly to the internet.
"""

import os

bind = f"0.0.0.0:{os.environ.get('WEB_PORT', '8000')}"

# One process: rate-limit state is kept in memory per process, so more
# workers would multiply the effective limit. Threads provide concurrency and
# keep one slow client from blocking everyone else. Each in-flight password
# hash uses argon2_memory_cost of RAM (128 MB by default), so size the
# container's memory for WEB_THREADS concurrent hashes plus ~100 MB. The
# default of 2 fits a 512 MB container.
workers = 1
worker_class = "gthread"
threads = int(os.environ.get("WEB_THREADS", "2"))

# Drop requests that take too long (slow clients, stuck backends)
timeout = 30
graceful_timeout = 10
keepalive = 5

# Request size limits are enforced by Flask (max_data_size_kb); these cap the
# request line and headers.
limit_request_line = 4096
limit_request_fields = 100
limit_request_field_size = 8190

loglevel = os.environ.get("LOG_LEVEL", "INFO").lower()
accesslog = "-"
errorlog = "-"

# The control socket (for gunicornc) defaults to $HOME, which doesn't exist
# for the nobody user; whisper doesn't use it.
control_socket_disable = True
