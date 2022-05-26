FROM python:3.10-alpine

ENV WEB_PORT=8000
ENV LOG_LEVEL=INFO

RUN mkdir -p /usr/src/app \
    && apk add --update --no-cache py-setuptools nginx bash gettext libseccomp libffi-dev gcc musl-dev \
    && rm -rf /etc/nginx/*.default \
    && rm -rf /var/cache/apk/* \
    && rm -rf /tmp/* \
    && rm -rf /var/www/*

WORKDIR /usr/src/app

COPY --chmod=755 ./src /usr/src/app/
COPY --chmod=755 ./src/nginx.template.conf /tmp/nginx.template.conf
COPY --chmod=755 ./scripts/run.sh /run.sh

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE $WEB_PORT

USER nobody

CMD sh /run.sh
