# syntax=docker/dockerfile:1
ARG PYTHON_VERSION=3.13
FROM public.ecr.aws/lambda/python:${PYTHON_VERSION} AS builder

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONIOENCODING=UTF-8
ENV PIP_NO_CACHE_DIR=off
ENV PIP_DISABLE_PIP_VERSION_CHECK=on

SHELL ["/bin/bash", "-euo", "pipefail", "-c"]

# hadolint ignore=DL3040
RUN \
      --mount=type=cache,target=/var/cache/yum,sharing=locked \
      --mount=type=cache,target=/var/cache/dnf,sharing=locked \
      --mount=type=cache,target=/var/lib/yum,sharing=locked \
      --mount=type=cache,target=/var/lib/dnf,sharing=locked \
      dnf -y upgrade \
      && dnf -y install ca-certificates

RUN \
      --mount=type=cache,target=/root/.cache/pip \
      --mount=type=bind,source=.,target=/mnt/host \
      /var/lang/bin/python -m pip install -U awslambdaric pip poetry poetry-plugin-export \
      && /var/lang/bin/python -m poetry --directory=/mnt/host export \
        --format=requirements.txt --output=/tmp/requirements.txt \
      && /var/lang/bin/python -m pip uninstall -y poetry poetry-plugin-export \
      && /var/lang/bin/python -m pip install -U -r /tmp/requirements.txt


FROM public.ecr.aws/lambda/python:${PYTHON_VERSION} AS app

ARG USER_UID=1001
ARG USER_GID=1001
ARG USER_NAME=lambda

COPY --from=builder /var/lang /var/lang

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONIOENCODING=UTF-8
ENV PIP_NO_CACHE_DIR=off
ENV PIP_DISABLE_PIP_VERSION_CHECK=on

SHELL ["/bin/bash", "-euo", "pipefail", "-c"]

# hadolint ignore=DL3040,DL3041
RUN \
      --mount=type=cache,target=/var/cache/yum,sharing=locked \
      --mount=type=cache,target=/var/cache/dnf,sharing=locked \
      --mount=type=cache,target=/var/lib/yum,sharing=locked \
      --mount=type=cache,target=/var/lib/dnf,sharing=locked \
      dnf -y upgrade \
      && dnf -y install shadow-utils

RUN \
      /sbin/groupadd --gid "${USER_GID}" "${USER_NAME}" \
      && /sbin/useradd --uid "${USER_UID}" --gid "${USER_GID}" --shell /bin/bash --create-home "${USER_NAME}"

# ENV LAMBDA_TASK_ROOT=/var/task

RUN \
      --mount=type=bind,source=.,target=/mnt/host \
      cp -a /mnt/host/src/* "${LAMBDA_TASK_ROOT}/"

HEALTHCHECK NONE

USER "${USER_NAME}"

# ENTRYPOINT ["/var/lang/bin/python", "-m", "awslambdaric"]
CMD ["webhook.main.lambda_handler"]
