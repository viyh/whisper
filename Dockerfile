FROM python:3.10-alpine

ENV WEB_PORT=8000
ENV LOG_LEVEL=INFO

RUN mkdir -p /usr/src/app \
    && apk add --update --no-cache \
        py-setuptools==59.4.0-r0 \
        nginx==1.22.0-r1 \
        bash==5.1.16-r2 \
        gettext==0.21-r2 \
        libseccomp==2.5.2-r1 \
        libffi-dev==3.4.2-r1 \
        gcc==11.2.1_git20220219-r2 \
        musl-dev==1.2.3-r0 \
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

CMD ["sh", "/run.sh"]
