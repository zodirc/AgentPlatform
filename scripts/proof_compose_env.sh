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

proof_compose_env_apply() {
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

  if [[ "${PROOF_KEEP_MIRRORS:-0}" == "1" ]]; then
    return 0
  fi
  if [[ "${CI:-}" != "true" && "${CI:-}" != "1" ]]; then
    return 0
  fi

  # Public registries for GitHub Actions (and CI=true local proof).
  # APT_MIRROR empty → Dockerfiles skip sed rewrite (Debian defaults).
  # Use ${VAR-default} in compose so an explicit empty APT_MIRROR is preserved.
  export PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.org/simple}"
  export PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST:-pypi.org}"
  export NPM_CONFIG_REGISTRY="${NPM_CONFIG_REGISTRY:-https://registry.npmjs.org}"
  export TORCH_FIND_LINKS="${TORCH_FIND_LINKS:-https://download.pytorch.org/whl/cpu}"
  export HF_ENDPOINT="${HF_ENDPOINT:-https://huggingface.co}"
  if [[ -z "${APT_MIRROR+x}" ]]; then
    export APT_MIRROR=""
  fi
  echo "==> proof: CI build registries → pip=${PIP_INDEX_URL} npm=${NPM_CONFIG_REGISTRY} apt_mirror=${APT_MIRROR:-(debian default)}"
  echo "    (PROOF_KEEP_MIRRORS=1 to keep Dockerfile China defaults)"
}
