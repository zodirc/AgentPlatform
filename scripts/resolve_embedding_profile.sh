#!/usr/bin/env bash
# Resolve embed profile for make up / up-runtime / up-bench.
# Writes deploy/embedding.auto.env (gitignored). Compose loads it after .env.
# Also writes deploy/compose/gpu.auto.yml when NVIDIA GPU is usable.
#
# Policy (shared multilingual embedder; HNSW graphs split by corpus, not by model):
#   EMBEDDING_PROFILE=auto|small|large|m3   (default auto)
#   CUDA path (VRAM ≥ EMBEDDING_GPU_MIN_MIB or RUNTIME_GPU=1)
#     → BAAI/bge-m3 @1024 + CUDA torch (cu128) + compose GPU overlay
#       (one model for product seed + Ops BEIR + Ops C-MTEB)
#   otherwise → thenlper/gte-small @384 + CPU torch
#   bge-m3 is never the auto/large default without CUDA (RUNTIME_GPU=0 → small).
# MiniLM / gte-large are no longer production defaults (FORCE_MODEL still works).
#
# Overrides:
#   RUNTIME_GPU=0          force CPU torch / no GPU overlay (even with nvidia-smi)
#   RUNTIME_GPU=1          force GPU overlay when a device is visible
#   TORCH_INDEX_URL=...    override CUDA wheel index (default cu128 for RTX 50xx)
#   EMBEDDING_DEVICE=cpu|cuda|auto
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${EMBEDDING_AUTO_ENV:-$ROOT/deploy/embedding.auto.env}"
GPU_OUT="${GPU_AUTO_COMPOSE:-$ROOT/deploy/compose/gpu.auto.yml}"
MIN_MIB="${EMBEDDING_GPU_MIN_MIB:-8192}"
# Blackwell (sm_120 / RTX 5080) needs cu128+; older cards still work with cu128 wheels.
DEFAULT_TORCH_INDEX_URL="${TORCH_INDEX_URL_DEFAULT:-https://download.pytorch.org/whl/cu128}"

# Load .env keys we care about (do not export secrets broadly).
if [[ -f "$ROOT/.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
      EMBEDDING_PROFILE=*|EMBEDDING_MODEL=*|EMBEDDING_DIMENSIONS=*|EMBEDDING_BACKEND=*|EMBEDDING_GPU_MIN_MIB=*|EMBEDDING_FORCE_MODEL=*|EMBEDDING_DEVICE=*|RUNTIME_GPU=*|TORCH_INDEX_URL=*)
        eval "export $line" 2>/dev/null || true
        ;;
    esac
  done <"$ROOT/.env"
  set +a
fi

PROFILE="$(echo "${EMBEDDING_PROFILE:-auto}" | tr '[:upper:]' '[:lower:]')"
FORCE_MODEL="${EMBEDDING_FORCE_MODEL:-}"
RUNTIME_GPU_FLAG="$(echo "${RUNTIME_GPU:-auto}" | tr '[:upper:]' '[:lower:]')"

gpu_vram_mib() {
  if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo 0
    return
  fi
  local raw
  raw="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 || true)"
  raw="$(echo "$raw" | tr -cd '0-9')"
  if [[ -z "$raw" ]]; then
    echo 0
  else
    echo "$raw"
  fi
}

vram="$(gpu_vram_mib)"
vram="${vram:-0}"

# Decide CUDA before model pick so auto never selects bge-m3 under RUNTIME_GPU=0.
use_cuda=0
cuda_reason=""
case "$RUNTIME_GPU_FLAG" in
  0|false|no|off|cpu)
    use_cuda=0
    cuda_reason="RUNTIME_GPU=$RUNTIME_GPU_FLAG"
    ;;
  1|true|yes|on|cuda|gpu)
    use_cuda=1
    cuda_reason="RUNTIME_GPU=$RUNTIME_GPU_FLAG (vram=${vram}MiB)"
    ;;
  auto|"")
    if [[ "$vram" =~ ^[0-9]+$ ]] && (( vram >= MIN_MIB )); then
      use_cuda=1
      cuda_reason="auto: nvidia VRAM ${vram}MiB ≥ ${MIN_MIB}MiB"
    else
      use_cuda=0
      cuda_reason="auto: CPU torch (vram=${vram}MiB, need≥${MIN_MIB})"
    fi
    ;;
  *)
    echo "resolve_embedding_profile: unknown RUNTIME_GPU=$RUNTIME_GPU_FLAG (use auto|0|1)" >&2
    exit 2
    ;;
esac

pick_gpu_m3=0
reason=""
case "$PROFILE" in
  large|m3|bge-m3|l|gte-large)
    if (( use_cuda )); then
      pick_gpu_m3=1
      reason="EMBEDDING_PROFILE=$PROFILE (GPU)"
    else
      pick_gpu_m3=0
      reason="EMBEDDING_PROFILE=$PROFILE but no CUDA → gte-small (bge-m3 is GPU-only)"
    fi
    ;;
  small|gte-small|s)
    pick_gpu_m3=0
    reason="EMBEDDING_PROFILE=$PROFILE"
    ;;
  auto|"")
    if (( use_cuda )); then
      pick_gpu_m3=1
      reason="auto: GPU → bge-m3 (${cuda_reason})"
    else
      pick_gpu_m3=0
      reason="auto: no CUDA → gte-small (${cuda_reason})"
    fi
    ;;
  *)
    echo "resolve_embedding_profile: unknown EMBEDDING_PROFILE=$PROFILE (use auto|small|large|m3)" >&2
    exit 2
    ;;
esac

if [[ -n "$FORCE_MODEL" ]]; then
  MODEL="$FORCE_MODEL"
  if echo "$MODEL" | grep -qi 'bge-m3'; then
    DIMS=1024
    # 13: dense truncate max_seq=512 + token-aligned chunker (was INDEX 12).
    INDEX_VER=13
    pick_gpu_m3=1
  elif echo "$MODEL" | grep -qi 'gte-large'; then
    DIMS=1024
    INDEX_VER=10
    pick_gpu_m3=1
  elif echo "$MODEL" | grep -qi 'gte-small'; then
    DIMS=384
    INDEX_VER=9
    pick_gpu_m3=0
  else
    DIMS="${EMBEDDING_DIMENSIONS:-384}"
    INDEX_VER=9
  fi
  reason="EMBEDDING_FORCE_MODEL=$FORCE_MODEL ($reason)"
elif (( pick_gpu_m3 )); then
  MODEL="BAAI/bge-m3"
  DIMS=1024
  # 13: dense truncate max_seq=512 + token-aligned chunker (was INDEX 12).
  INDEX_VER=13
else
  MODEL="thenlper/gte-small"
  DIMS=384
  INDEX_VER=9
fi

BACKEND="${EMBEDDING_BACKEND:-sentence_transformers}"
if (( pick_gpu_m3 )); then
  RESOLVED=m3
  # Short-passage truncate + larger batch: hub default 8192 thrashs 16GiB at batch 64.
  MAX_SEQ="${EMBEDDING_MAX_SEQ_LENGTH:-512}"
  BATCH_DEFAULT=128
else
  RESOLVED=small
  MAX_SEQ="${EMBEDDING_MAX_SEQ_LENGTH:-0}"
  BATCH_DEFAULT=64
fi

TORCH_INDEX_URL_VAL=""
EMBEDDING_DEVICE_VAL="${EMBEDDING_DEVICE:-auto}"
if (( use_cuda )); then
  TORCH_INDEX_URL_VAL="${TORCH_INDEX_URL:-$DEFAULT_TORCH_INDEX_URL}"
  if [[ -z "${EMBEDDING_DEVICE:-}" || "${EMBEDDING_DEVICE}" == "auto" ]]; then
    EMBEDDING_DEVICE_VAL="cuda"
  fi
else
  TORCH_INDEX_URL_VAL=""
  if [[ -z "${EMBEDDING_DEVICE:-}" || "${EMBEDDING_DEVICE}" == "auto" ]]; then
    EMBEDDING_DEVICE_VAL="auto"
  fi
fi

mkdir -p "$(dirname "$OUT")" "$(dirname "$GPU_OUT")"
cat >"$OUT" <<EOF
# Generated by scripts/resolve_embedding_profile.sh — do not edit by hand.
# Regenerated on every make up / up-runtime / up-bench.
# Reason: ${reason}
# CUDA: ${cuda_reason}
EMBEDDING_BACKEND=${BACKEND}
EMBEDDING_MODEL=${MODEL}
EMBEDDING_DIMENSIONS=${DIMS}
EMBEDDING_INDEX_VERSION=${INDEX_VER}
EMBEDDING_PROFILE_RESOLVED=${RESOLVED}
EMBEDDING_DEVICE=${EMBEDDING_DEVICE_VAL}
EMBEDDING_MAX_SEQ_LENGTH=${MAX_SEQ}
EMBEDDING_BATCH_SIZE=${EMBEDDING_BATCH_SIZE:-$BATCH_DEFAULT}
RUNTIME_GPU=$( (( use_cuda )) && echo 1 || echo 0 )
TORCH_INDEX_URL=${TORCH_INDEX_URL_VAL}
EOF

if (( use_cuda )); then
  cat >"$GPU_OUT" <<EOF
# Generated by scripts/resolve_embedding_profile.sh — do not edit by hand.
# NVIDIA GPU detected → pass through device + prefer CUDA torch wheels.
services:
  runtime:
    gpus: all
    mem_limit: 12g
    environment:
      NVIDIA_VISIBLE_DEVICES: all
      NVIDIA_DRIVER_CAPABILITIES: compute,utility
      EMBEDDING_DEVICE: ${EMBEDDING_DEVICE_VAL}
      EMBEDDING_BATCH_SIZE: \${EMBEDDING_BATCH_SIZE:-${BATCH_DEFAULT}}
      EMBEDDING_MAX_SEQ_LENGTH: \${EMBEDDING_MAX_SEQ_LENGTH:-${MAX_SEQ}}
    build:
      args:
        TORCH_INDEX_URL: ${TORCH_INDEX_URL_VAL}
  bench:
    gpus: all
    mem_limit: 12g
    environment:
      NVIDIA_VISIBLE_DEVICES: all
      NVIDIA_DRIVER_CAPABILITIES: compute,utility
      EMBEDDING_DEVICE: ${EMBEDDING_DEVICE_VAL}
      EMBEDDING_MAX_SEQ_LENGTH: \${EMBEDDING_MAX_SEQ_LENGTH:-${MAX_SEQ}}
    build:
      args:
        TORCH_INDEX_URL: ${TORCH_INDEX_URL_VAL}
EOF
else
  cat >"$GPU_OUT" <<'EOF'
# Generated by scripts/resolve_embedding_profile.sh — do not edit by hand.
# No usable NVIDIA GPU (or RUNTIME_GPU=0) → CPU torch path.
services: {}
EOF
fi

echo "==> embedding profile: ${MODEL} @${DIMS}d (index≈${INDEX_VER}) — ${reason}"
if (( use_cuda )); then
  echo "==> CUDA: ON — torch ${TORCH_INDEX_URL_VAL} · device=${EMBEDDING_DEVICE_VAL} · max_seq=${MAX_SEQ} · batch≈${EMBEDDING_BATCH_SIZE:-$BATCH_DEFAULT} — ${cuda_reason}"
else
  echo "==> CUDA: OFF — CPU torch — ${cuda_reason}"
fi
echo "    wrote ${OUT}"
echo "    wrote ${GPU_OUT}"
