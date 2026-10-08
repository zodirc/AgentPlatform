"""内核包签名校验。私钥只在发布流水线，公钥由宿主持有。"""

from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# 发布流水线的公钥。私钥不在仓库里；测试验包时传入本次生成的公钥。
PUBLIC_KEY_HEX = "0fdd9d8c82efe5178f1481f75bc67f363d98982f732b67c786bca03524d8baa8"


def public_key() -> Ed25519PublicKey | None:
    if not PUBLIC_KEY_HEX:
        return None
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUBLIC_KEY_HEX))


def verify_package(
    package: Path,
    *,
    public: Ed25519PublicKey,
    signature: Path | None = None,
    expected_protocol_major: int = 1,
    expected_python: str = "3.11",
) -> dict:
    """校验清单签名、文件哈希和协议主版本。失败抛出 ValueError。"""
    package = Path(package)
    signature_path = signature or (package.parent / "manifest.json.sig")
    signature_bytes = signature_path.read_bytes()
    with zipfile.ZipFile(package) as archive:
        manifest_bytes = archive.read("manifest.json")
        public.verify(signature_bytes, manifest_bytes)
        manifest = json.loads(manifest_bytes)
        protocol = str(manifest.get("protocol_version") or "")
        major = int(protocol.split(".", 1)[0] or "0")
        if major != expected_protocol_major:
            raise ValueError(f"protocol major {major} != {expected_protocol_major}")
        python_version = str(manifest.get("python") or "")
        if expected_python and not python_version.startswith(expected_python):
            raise ValueError(f"python {python_version} != {expected_python}")
        requires = manifest.get("host_requires") or {}
        for name in ("pydantic", "pydantic-settings", "httpx", "pyyaml"):
            if name not in requires:
                raise ValueError(f"host_requires missing {name}")
        for name, digest in (manifest.get("files") or {}).items():
            actual = hashlib.sha256(archive.read(name)).hexdigest()
            if actual != digest:
                raise ValueError(f"hash mismatch {name}")
    return manifest
