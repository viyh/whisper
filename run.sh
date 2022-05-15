
#!/bin/bash
envsubst "\$WEB_PORT" < /tmp/nginx.template.conf > /tmp/nginx.conf && \
/usr/sbin/nginx -c /tmp/nginx.conf -p /tmp -e nginx.error.log && \
gunicorn \
    --log-level $LOG_LEVEL \
    --error-logfile - \
    --access-logfile - \
    --bind unix:/tmp/gunicorn.sock \
    app:app
