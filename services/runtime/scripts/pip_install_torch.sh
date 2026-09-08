#!/bin/sh
# Install or prefetch torch without consulting PyPI's default wheel.
# PyPI torch (e.g. 2.14 manylinux) pulls triton (~250MB) and is ~550MB;
# CPU wheels from TORCH_FIND_LINKS are ~180MB and have no triton.
# CUDA builds pass TORCH_INDEX_URL (cu128 etc.).
# Offline: /tmp/torch-wheels/*.whl (named context) or /tmp/torch-prefetched
# (torch-wheels BuildKit stage — download once, baker+deps install locally).
set -eu

timeout="${PIP_TIMEOUT:-300}"
retries="${PIP_RETRIES:-5}"
pin=/tmp/torch.pin
prefetch="${TORCH_PREFETCH_DIR:-/tmp/torch-prefetched}"

write_pin() {
  pip freeze | grep -i '^torch==' >"${pin}"
  test -s "${pin}"
}

install_runtime_deps() {
  python3 -c '
import subprocess, sys
from importlib.metadata import requires

skip_prefixes = ("nvidia-", "triton", "cuda-")
want = []
for raw in requires("torch") or []:
    base, _, marker = raw.partition(";")
    if "extra" in marker:
        continue
    req = base.strip()
    if not req:
        continue
    name = req.split("[")[0]
    for op in ("===", "==", "!=", "<=", ">=", "~=", "<", ">"):
        if op in name:
            name = name.split(op)[0]
            break
    name = name.strip().lower()
    if any(name.startswith(p) for p in skip_prefixes):
        continue
    want.append(req)
if want:
    subprocess.check_call(
        [
            sys.executable, "-m", "pip", "install",
            "--upgrade-strategy", "only-if-needed",
            "-c", "/tmp/torch.pin",
            *want,
        ]
    )
'
}

install_from_local() {
  dir="$1"
  echo "torch: local wheels in ${dir} ($(ls "${dir}"/*.whl | wc -l) files)"
  pip install --no-deps --no-index --find-links="${dir}" torch
  write_pin
  install_runtime_deps
}

download_to() {
  dl_dir="$1"
  mkdir -p "${dl_dir}"
  if [ -n "${TORCH_INDEX_URL:-}" ]; then
    echo "torch: download CUDA from ${TORCH_INDEX_URL} → ${dl_dir}"
    env -u PIP_INDEX_URL -u PIP_EXTRA_INDEX_URL \
      pip download --default-timeout="${timeout}" --retries="${retries}" \
        --no-deps --dest "${dl_dir}" torch --index-url "${TORCH_INDEX_URL}"
    return
  fi
  links="${TORCH_FIND_LINKS:-https://download.pytorch.org/whl/cpu}"
  echo "torch: download CPU from ${links} → ${dl_dir}"
  case "${links}" in
    */whl/*)
      env -u PIP_INDEX_URL -u PIP_EXTRA_INDEX_URL \
        pip download --default-timeout="${timeout}" --retries="${retries}" \
          --no-deps --dest "${dl_dir}" torch --index-url "${links}"
      ;;
    *)
      env -u PIP_INDEX_URL -u PIP_EXTRA_INDEX_URL \
        pip download --default-timeout="${timeout}" --retries="${retries}" \
          --no-deps --no-index --find-links="${links}" --dest "${dl_dir}" torch
      ;;
  esac
}

copy_whls() {
  from_dir="$1"
  to_dir="$2"
  mkdir -p "${to_dir}"
  for whl in "${from_dir}"/*.whl; do
    [ -f "${whl}" ] || continue
    base=$(basename "${whl}")
    # dash has no `local`; download_to must not reuse outer names.
    if [ -e "${to_dir}/${base}" ] && [ "${whl}" -ef "${to_dir}/${base}" ]; then
      continue
    fi
    cp "${whl}" "${to_dir}/"
  done
}

if [ "${1:-}" = "--download-only" ]; then
  out_dir="${TORCH_WHEEL_DEST:-/wheels}"
  cache_dir="${TORCH_WHEEL_CACHE_DIR:-}"
  mkdir -p "${out_dir}"
  if ls /tmp/torch-wheels/*.whl >/dev/null 2>&1; then
    echo "torch: prefetch from offline wheel cache"
    copy_whls /tmp/torch-wheels "${out_dir}"
    exit 0
  fi
  want="${TORCH_INDEX_URL:-cpu:${TORCH_FIND_LINKS:-https://download.pytorch.org/whl/cpu}}"
  if [ -n "${cache_dir}" ] && [ -f "${cache_dir}/.source" ] \
      && [ "$(cat "${cache_dir}/.source")" = "${want}" ] \
      && ls "${cache_dir}"/*.whl >/dev/null 2>&1; then
    echo "torch: prefetch from BuildKit cache mount"
    copy_whls "${cache_dir}" "${out_dir}"
    exit 0
  fi
  # Fetch into a unique dir first. dash functions share globals — naming the
  # download dest `dest` used to clobber TORCH_WHEEL_DEST=/wheels and make
  # `cp` fail with "are the same file".
  scratch=/tmp/torch-dl
  rm -rf "${scratch}"
  mkdir -p "${scratch}"
  download_to "${scratch}"
  copy_whls "${scratch}" "${out_dir}"
  if [ -n "${cache_dir}" ]; then
    mkdir -p "${cache_dir}"
    rm -f "${cache_dir}"/*.whl "${cache_dir}/.source"
    copy_whls "${scratch}" "${cache_dir}"
    printf '%s\n' "${want}" >"${cache_dir}/.source"
  fi
  exit 0
fi

if ls /tmp/torch-wheels/*.whl >/dev/null 2>&1; then
  install_from_local /tmp/torch-wheels
  exit 0
fi

if ls "${prefetch}"/*.whl >/dev/null 2>&1; then
  install_from_local "${prefetch}"
  exit 0
fi

if [ -n "${TORCH_INDEX_URL:-}" ]; then
  echo "torch: index ${TORCH_INDEX_URL} (PIP_INDEX_URL unset so PyPI cannot win)"
  env -u PIP_INDEX_URL -u PIP_EXTRA_INDEX_URL \
    pip install --default-timeout="${timeout}" --retries="${retries}" \
      torch --index-url "${TORCH_INDEX_URL}"
  write_pin
  exit 0
fi

links="${TORCH_FIND_LINKS:-https://download.pytorch.org/whl/cpu}"
echo "torch: CPU from ${links}"
case "${links}" in
  */whl/*)
    echo "torch: index ${links} (PIP_INDEX_URL unset so PyPI cannot win)"
    env -u PIP_INDEX_URL -u PIP_EXTRA_INDEX_URL \
      pip install --default-timeout="${timeout}" --retries="${retries}" \
        torch --index-url "${links}"
    write_pin
    ;;
  *)
    env -u PIP_INDEX_URL -u PIP_EXTRA_INDEX_URL \
      pip install --default-timeout="${timeout}" --retries="${retries}" \
        --no-deps --no-index --find-links="${links}" torch
    write_pin
    install_runtime_deps
    ;;
esac
