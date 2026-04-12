FROM python:3.13-slim

ENV WEB_PORT=8000
ENV LOG_LEVEL=INFO

RUN mkdir -p /usr/src/app \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        nginx \
        gettext-base \
    && rm -rf /var/lib/apt/lists/* \
    && rm -rf /etc/nginx/sites-enabled/default \
    && rm -rf /tmp/*

WORKDIR /usr/src/app

COPY --chmod=755 ./src /usr/src/app/
COPY --chmod=755 ./src/nginx.template.conf /tmp/nginx.template.conf
COPY --chmod=755 ./scripts/run.sh /run.sh

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE $WEB_PORT

USER nobody

CMD ["sh", "/run.sh"]
