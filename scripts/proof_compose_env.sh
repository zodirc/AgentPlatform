#!/usr/bin/env bash
# Shared by gate / smoke / ci_proof: keep compose proof runs startable when a
# developer .env sets APP_ENV=production while still using bootstrap secrets.
# Rebuilt runtime/api images reject that combination at startup (container exit 3).
# GitHub Actions uses .env.example (APP_ENV=development). Mirror that under CI=true.
#
# Override: PROOF_KEEP_APP_ENV=1 to honor .env APP_ENV during proof.
# Optional: PROOF_APP_ENV=development|production

proof_compose_env_apply() {
  if [[ "${PROOF_KEEP_APP_ENV:-0}" == "1" ]]; then
    return 0
  fi
  # Only normalize when running the CI/preflight proof path.
  if [[ "${CI:-}" != "true" && "${CI:-}" != "1" ]]; then
    return 0
  fi

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
}
