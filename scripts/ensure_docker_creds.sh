#!/usr/bin/env bash
# Fix Docker Hub pulls under Linux/WSL when Docker Desktop wrote a Windows
# credential helper into ~/.docker/config.json:
#   "credsStore": "desktop.exe"
# → BuildKit: fork/exec docker-credential-desktop.exe: exec format error
#
# Idempotent. Opt out: DOCKER_FIX_WSL_CREDS=0 (Makefile / env).
# Does not touch "auths" or other keys.
set -euo pipefail

if [[ "${DOCKER_FIX_WSL_CREDS:-1}" != "1" ]]; then
  exit 0
fi

# Only relevant when the broken Windows helper is configured for a Linux docker CLI.
case "$(uname -s)" in
  Linux) ;;
  *) exit 0 ;;
esac

CFG="${DOCKER_CONFIG:-${HOME}/.docker}/config.json"
if [[ ! -f "$CFG" ]]; then
  exit 0
fi

python3 - "$CFG" <<'PY'
import json, os, sys

path = sys.argv[1]
try:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
except (OSError, json.JSONDecodeError) as e:
    print(f"==> docker creds: skip ({path}: {e})", file=sys.stderr)
    sys.exit(0)

changed = False
for key in ("credsStore", "credStore"):
    val = data.get(key)
    if not isinstance(val, str):
        continue
    # Windows helper names end with .exe; Linux cannot exec them in WSL.
    if val.endswith(".exe") or val == "desktop.exe":
        data.pop(key, None)
        changed = True
        print(f"==> docker creds: removed {key}={val!r} from {path}")

if not changed:
    sys.exit(0)

tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
os.replace(tmp, path)
print("==> docker creds: public pulls no longer need desktop.exe (DOCKER_FIX_WSL_CREDS=0 to skip)")
PY
