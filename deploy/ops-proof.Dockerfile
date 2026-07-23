# Ops / CI proof runner image (docs/29 suite=ci).
# Repo is bind-mounted at runtime at the same host path (not COPYed).
FROM docker:27-cli AS dockercli

FROM python:3.11-bookworm

COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=dockercli /usr/local/libexec/docker/cli-plugins /usr/local/libexec/docker/cli-plugins

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends make curl ca-certificates git; \
    rm -rf /var/lib/apt/lists/*; \
    docker --version; \
    docker compose version

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1

WORKDIR /work
CMD ["bash", "scripts/ci_proof.sh"]
