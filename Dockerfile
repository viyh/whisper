FROM python:3.4-alpine

ENV WEB_PORT 8000
RUN mkdir -p /usr/src/app && apk add --update --no-cache py-setuptools

WORKDIR /usr/src/app

ADD ./app /usr/src/app/

RUN pip install --no-cache-dir -r requirements.txt

EXPOSE ${WEB_PORT}

CMD [ "gunicorn", "-m 4", "-b 0.0.0.0:${WEB_PORT}", "app:app" ]
