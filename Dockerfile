# Docker Hardened Images (https://dhi.io) are free but need a Docker account:
#   docker login dhi.io

# Build stage: the -dev variant has a shell and pip for installing packages.
FROM dhi.io/python:3.14-debian13-dev AS build

WORKDIR /usr/src/app

COPY src/requirements.txt ./
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt \
    && /opt/venv/bin/pip uninstall -y pip

COPY src/ ./
RUN rm -rf tests requirements*.txt config.yaml \
    && python3 -m compileall -q /usr/src/app

# Runtime stage: no shell or package manager. Same Python path as the build
# stage (/usr/bin/python3), so the virtualenv works as-is.
FROM dhi.io/python:3.14-debian13

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WEB_PORT=8000 \
    LOG_LEVEL=INFO

COPY --from=build /opt/venv /opt/venv
COPY --from=build /usr/src/app /usr/src/app

WORKDIR /usr/src/app

EXPOSE 8000

# nobody, as in previous releases, so existing volume permissions keep working
USER 65534:65534

CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:app"]
