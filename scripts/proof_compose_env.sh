#!/usr/bin/env bash
# Shared by gate / smoke / ci_proof: keep compose proof runs startable when a
# developer .env sets APP_ENV=production while still using bootstrap secrets.
# Rebuilt runtime/api images reject that combination at startup (container exit 3).
# GitHub Actions uses .env.example (APP_ENV=development). Mirror that under CI=true.
#
# Also: Dockerfiles default to China mirrors (aliyun / npmmirror / hf-mirror).
# On GitHub-hosted runners those endpoints often stall until the 2h job timeout.
# When CI=true, point builds at public registries unless PROOF_KEEP_MIRRORS=1.
#
# Override: PROOF_KEEP_APP_ENV=1 to honor .env APP_ENV during proof.
# Optional: PROOF_APP_ENV=development|production
# Optional: PROOF_KEEP_MIRRORS=1 to keep China mirrors even under CI=true.
# Optional: PROOF_KEEP_DOCKERHUB=1 to pull library images from Docker Hub (no gcr mirror).
# Optional: PROOF_WITH_BENCH=1 / SMOKE_WITH_BENCH=1 to keep compose profile "bench".

# Docker Hub library short name → content-addressed pull via Google's Hub mirror.
# Same sha256 as deploy/base-images.env; avoids registry-1.docker.io 502 on GHA.
proof_dockerhub_library_mirror() {
  local ref="${1:-}"
  local prefix="${DOCKERHUB_LIBRARY_MIRROR:-mirror.gcr.io/library}"
  if [[ -z "${ref}" ]]; then
    echo ""
    return 0
  fi
  case "${ref}" in
    */*) echo "${ref}" ;;
    *) echo "${prefix}/${ref}" ;;
  esac
}

proof_pin_ci_base_images() {
  if [[ "${PROOF_KEEP_DOCKERHUB:-0}" == "1" ]]; then
    return 0
  fi
  local envf root saved_py saved_node saved_nginx
  root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  envf="${root}/deploy/base-images.env"
  saved_py="${PYTHON_BASE-}"
  saved_node="${NODE_BASE-}"
  saved_nginx="${NGINX_BASE-}"
  if [[ -f "${envf}" ]]; then
    # shellcheck disable=SC1090
    set -a
    # shellcheck source=deploy/base-images.env
    source "${envf}"
    set +a
  fi
  [[ -n "${saved_py}" ]] && PYTHON_BASE="${saved_py}"
  [[ -n "${saved_node}" ]] && NODE_BASE="${saved_node}"
  [[ -n "${saved_nginx}" ]] && NGINX_BASE="${saved_nginx}"
  PYTHON_BASE="$(proof_dockerhub_library_mirror "${PYTHON_BASE:-}")"
  NODE_BASE="$(proof_dockerhub_library_mirror "${NODE_BASE:-}")"
  NGINX_BASE="$(proof_dockerhub_library_mirror "${NGINX_BASE:-}")"
  export PYTHON_BASE NODE_BASE NGINX_BASE
  echo "==> proof: CI base images → node=${NODE_BASE}"
  echo "    (PROOF_KEEP_DOCKERHUB=1 to keep Docker Hub library names)"
}

# Hub / registry blips that are worth retrying compose --build.
proof_is_registry_transient() {
  local log="${1:-}"
  [[ -n "${log}" && -f "${log}" ]] || return 1
  grep -Eiq \
    '502 Bad Gateway|504 Gateway|429 Too Many|TOOMANYREQUESTS|failed to copy: httpReadSeeker|error from registry|net/http: TLS handshake timeout|connection reset by peer' \
    "${log}"
}

# Retry a compose/build command when the log looks like a Hub 502.
proof_retry_transient_registry() {
  local attempt=1
  local max="${DOCKER_BUILD_RETRIES:-4}"
  local delay="${DOCKER_BUILD_RETRY_DELAY:-8}"
  local log rc
  log="$(mktemp)"
  while true; do
    set +e
    set +o pipefail
    "$@" 2>&1 | tee "${log}"
    rc=${PIPESTATUS[0]}
    set -o pipefail
    set -e
    if [[ "${rc}" -eq 0 ]]; then
      rm -f "${log}"
      return 0
    fi
    if ((attempt >= max)) || ! proof_is_registry_transient "${log}"; then
      rm -f "${log}"
      return "${rc}"
    fi
    echo "==> proof: registry transient (attempt ${attempt}/${max}); retry in ${delay}s"
    attempt=$((attempt + 1))
    sleep "${delay}"
    delay=$((delay * 2))
    if ((delay > 40)); then
      delay=40
    fi
  done
}

# Remove a single name from COMPOSE_PROFILES (comma-separated).
_proof_strip_compose_profile() {
  local name="$1"
  local cur="${COMPOSE_PROFILES:-}"
  local out=""
  local part
  if [[ -z "${cur}" ]]; then
    export COMPOSE_PROFILES=""
    return 0
  fi
  local _parts
  IFS=',' read -r -a _parts <<<"${cur}"
  for part in "${_parts[@]}"; do
    part="${part//[[:space:]]/}"
    [[ -z "${part}" || "${part}" == "${name}" ]] && continue
    if [[ -n "${out}" ]]; then
      out="${out},${part}"
    else
      out="${part}"
    fi
  done
  export COMPOSE_PROFILES="${out}"
}

proof_compose_env_apply() {
  # Ops bench is unrelated to smoke/golden. Under CI, omit profile so
  # `compose up --build` does not build the ST bench worker.
  if [[ "${CI:-}" == "true" || "${CI:-}" == "1" ]]; then
    if [[ "${PROOF_WITH_BENCH:-0}" != "1" && "${SMOKE_WITH_BENCH:-0}" != "1" ]]; then
      _proof_strip_compose_profile bench
      echo "==> proof: compose profile 'bench' disabled (PROOF_WITH_BENCH=1 / SMOKE_WITH_BENCH=1 to keep)"
    fi
  fi

  if [[ "${PROOF_KEEP_APP_ENV:-0}" != "1" ]]; then
    # Only normalize when running the CI/preflight proof path.
    if [[ "${CI:-}" == "true" || "${CI:-}" == "1" ]]; then
      local env_app=""
      if [[ -f .env ]]; then
        env_app="$(
          python3 - <<'PY'
from pathlib import Path
for line in Path(".env").read_text(errors="replace").splitlines():
    line = line.strip().strip("\r")
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    if k.strip() != "APP_ENV":
        continue
    v = v.strip().strip("\r")
    if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0]:
        v = v[1:-1]
    if "#" in v:
        v = v.split("#", 1)[0].rstrip()
    print(v.strip().lower(), end="")
    break
PY
        )"
      fi
      local target="${PROOF_APP_ENV:-development}"
      if [[ "${env_app}" == "production" || "${env_app}" == "prod" ]]; then
        echo "==> proof: .env has APP_ENV=${env_app} — exporting APP_ENV=${target} for compose"
        echo "    (bootstrap secrets are rejected when APP_ENV=production; matches CI .env.example)"
        echo "    Keep production locally only with strong APP_SECRET_KEY / INTERNAL_SERVICE_TOKEN,"
        echo "    or set APP_ENV=development in .env. PROOF_KEEP_APP_ENV=1 to skip this override."
      fi
      export APP_ENV="${target}"
    fi
  fi

  if [[ "${CI:-}" == "true" || "${CI:-}" == "1" ]]; then
    if [[ "${PROOF_KEEP_MIRRORS:-0}" != "1" ]]; then
      # Public registries for GitHub Actions (and CI=true local proof).
      # APT_MIRROR empty → Dockerfiles skip sed rewrite (Debian defaults).
      # Use ${VAR-default} in compose so an explicit empty APT_MIRROR is preserved.
      export PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple}"
      export PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST:-pypi.org}"
      export NPM_CONFIG_REGISTRY="${NPM_CONFIG_REGISTRY:-https://registry.npmjs.org}"
      export TORCH_FIND_LINKS="${TORCH_FIND_LINKS:-https://download.pytorch.org/whl/cpu}"
      # CI runners have no GPU — force CPU torch even if a local shell exported cu128.
      export TORCH_INDEX_URL="${TORCH_INDEX_URL:-}"
      export RUNTIME_GPU="${RUNTIME_GPU:-0}"
      export HF_ENDPOINT="${HF_ENDPOINT:-https://huggingface.co}"
      if [[ -z "${APT_MIRROR+x}" ]]; then
        export APT_MIRROR=""
      fi
      echo "==> proof: CI build registries → pip=${PIP_INDEX_URL} npm=${NPM_CONFIG_REGISTRY} apt_mirror=${APT_MIRROR:-(debian default)}"
      echo "    (PROOF_KEEP_MIRRORS=1 to keep Dockerfile China defaults)"
    fi
    proof_pin_ci_base_images
  fi
}
