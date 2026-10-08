"""加载签名内核包。校验失败时保留当前内核，不切换目录。"""

from __future__ import annotations

import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.writing_host.trust import public_key, verify_package


@dataclass
class KernelLoad:
    accepted: bool
    reason: str
    root: Path | None
    core_version: str = ""


def load_kernel_package(
    package: Path,
    *,
    destination: Path,
    public: Ed25519PublicKey | None = None,
    signature: Path | None = None,
    current_root: Path | None = None,
) -> KernelLoad:
    """校验通过后解压到目标目录。失败时 ``root`` 仍是当前内核。"""
    key = public or public_key()
    if key is None:
        return KernelLoad(False, "宿主没有内置公钥", current_root)
    try:
        manifest = verify_package(package, public=key, signature=signature)
    except Exception as exc:
        return KernelLoad(False, str(exc), current_root)
    destination = Path(destination)
    staging = destination.parent / f".{destination.name}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        with zipfile.ZipFile(package) as archive:
            archive.extractall(staging)
        if destination.exists():
            shutil.rmtree(destination)
        staging.rename(destination)
    except Exception as exc:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        return KernelLoad(False, str(exc), current_root)
    return KernelLoad(
        True,
        "",
        destination,
        str(manifest.get("core_version") or ""),
    )
