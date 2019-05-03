FROM python:3.7-alpine

ENV WEB_PORT 8000

RUN mkdir -p /usr/src/app \
    && apk add --update --no-cache py-setuptools nginx bash gettext \
    && rm -rf /etc/nginx/*.default \
    && rm -rf /var/cache/apk/* \
    && rm -rf /tmp/* \
    && rm -rf /var/www/*

WORKDIR /usr/src/app

ADD ./app /usr/src/app/
ADD ./nginx.conf /tmp/nginx.conf

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE $WEB_PORT

CMD sh -c "gunicorn -m 4 --error-logfile /tmp/gunicorn.error.log --access-logfile /tmp/gunicorn.access.log -D -b unix:/tmp/gunicorn.sock app:app" && envsubst "\$WEB_PORT" < /tmp/nginx.conf > /etc/nginx/nginx.conf && /usr/sbin/nginx -c /etc/nginx/nginx.conf && tail -F /tmp/gunicorn.error.log /tmp/nginx.error.log /tmp/nginx.access.log
