from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "services" / "runtime" / "scripts" / "pip_install_torch.sh"
DOCKERFILES = (
    ROOT / "services" / "runtime" / "Dockerfile.retrieval",
    ROOT / "services" / "bench" / "Dockerfile",
)


def test_cpu_torch_install_is_isolated_from_pypi() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "PIP_INDEX_URL unset so PyPI cannot win" in text or "-u PIP_INDEX_URL" in text
    assert "--no-index" in text
    assert "triton" in text
    # dash has no local: `dest="$1"` inside download_to clobbered /wheels.
    assert 'dl_dir="$1"' in text
    assert "are the same file" in text or "clobber TORCH_WHEEL_DEST" in text


def test_dockerfiles_prefetch_torch_once() -> None:
    for path in DOCKERFILES:
        text = path.read_text(encoding="utf-8")
        assert "AS torch-wheels" in text, path
        assert "from=torch-wheels" in text, path
        assert "models already seeded, skip torch/ST" in text, path
        assert "--download-only" in text, path


def test_dockerfiles_do_not_mix_find_links_with_pypi_torch() -> None:
    for path in DOCKERFILES:
        text = path.read_text(encoding="utf-8")
        run_lines = [
            ln
            for ln in text.splitlines()
            if ln.lstrip().startswith("RUN") or ln.lstrip().startswith("&&")
        ]
        joined = "\n".join(run_lines)
        assert "pip install torch -f" not in joined, path
        assert "pip_install_torch.sh" in text, path
        assert "-c /tmp/torch.pin" in text, path
