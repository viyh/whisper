# Docker Hardened Images (https://dhi.io) are free but need a Docker account:
#   docker login dhi.io

# Build stage: the -dev variant has a shell for installing packages.
FROM dhi.io/python:3.14-debian13-dev AS build

# uv installs the packages, much faster than pip. Astral's own image, pinned
# by digest as well so the tag can't be moved. It stays in this stage.
COPY --from=ghcr.io/astral-sh/uv:0.13.9@sha256:d3b601f0c7b118bc1753febf7c41cc80981df678445e0254284eecf84db79a7d /uv /usr/local/bin/uv

# Compile bytecode at install time, as pip does: the runtime stage can't
# write it. The cache is a build cache mount, so it isn't in the image, and
# packages are copied out of it rather than linked.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_CACHE_DIR=/root/.cache/uv

WORKDIR /usr/src/app

# The image's own Python, so the virtualenv works as-is in the runtime stage.
# uv doesn't put pip in the virtualenv.
COPY src/requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv venv /opt/venv --python /usr/bin/python3 \
    && uv pip install --python /opt/venv/bin/python3 -r requirements.txt

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

# Remove the base image's system pip, setuptools and wheel: whisper's virtualenv
# doesn't use them, and scanners flag pip's vendored setuptools metadata. The
# runtime image has no shell, so this runs Python directly (exec-form RUN).
# (numeric uid: the image has no "root" entry in /etc/passwd)
USER 0
RUN ["python3", "-c", "import glob, os, shutil\nd = '/usr/lib/python3/dist-packages/'\nnames = ('pip', 'pip-*.dist-info', 'setuptools', 'setuptools-*.dist-info', 'wheel', 'wheel-*.dist-info', '_distutils_hack', 'distutils-precedence.pth')\npaths = [p for n in names for p in glob.glob(d + n)] + [p for p in ('/usr/bin/pip', '/usr/bin/pip3') if os.path.lexists(p)]\nfor p in paths:\n    shutil.rmtree(p) if os.path.isdir(p) and not os.path.islink(p) else os.remove(p)\nprint('removed:', *sorted(paths))"]

# The local backend's default storage directory, owned by whisper's user with
# mode 700. Docker gives a new volume mounted here the same owner and mode;
# without this it's owned by root and whisper can't write to it.
RUN ["python3", "-c", "import os\nos.makedirs('/tmp/whisper', 0o700)\nos.chmod('/tmp/whisper', 0o700)\nos.chown('/tmp/whisper', 65534, 65534)"]

COPY --from=build /opt/venv /opt/venv
COPY --from=build /usr/src/app /usr/src/app

WORKDIR /usr/src/app

EXPOSE 8000

# nobody, as in previous releases, so existing volume permissions keep working
USER 65534:65534

CMD ["gunicorn", "--config", "gunicorn.conf.py", "app:app"]
