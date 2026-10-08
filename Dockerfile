# syntax=docker/dockerfile:1

# Build stage: wheels for everything in requirements.txt. git is needed only
# here, to fetch wall-scan from its release tag.
FROM python:3.13-slim AS build
RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r /tmp/requirements.txt


FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# nmap with raw-socket capabilities, so `wall-scan --privileged` works for the
# non-root user below. The container must also be granted NET_RAW and NET_ADMIN
# (see compose.yaml) for the capabilities to take effect.
RUN apt-get update \
 && apt-get install -y --no-install-recommends nmap libcap2-bin \
 && setcap cap_net_raw,cap_net_admin,cap_net_bind_service+eip /usr/bin/nmap \
 && rm -rf /var/lib/apt/lists/*

COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir --no-index /wheels/* \
 && rm -rf /wheels

# The code belongs to root and the app runs as an unprivileged user, so the
# running app cannot modify itself.
RUN useradd --create-home --uid 1000 wall
WORKDIR /app
COPY . .
RUN DJANGO_SECRET_KEY=collectstatic-only python manage.py collectstatic --noinput

USER wall
EXPOSE 8000
CMD ["gunicorn", "wallhub.wsgi", "--bind", "0.0.0.0:8000", "--workers", "2", "--access-logfile", "-"]
