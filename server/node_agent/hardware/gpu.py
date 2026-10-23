"""GPU detection. Each detector is best effort, has a timeout, and only reads vendor tools' output.

* NVIDIA: ``nvidia-smi`` (one entry per GPU)
* AMD: ``rocm-smi --json``
* Apple Silicon: ``system_profiler`` on macOS. The GPU shares system memory, so the usable "VRAM" reported is
  an estimate (two thirds of RAM, close to what Metal lets one process use) and is flagged ``shared``.

Reported values are untrusted by the control plane; they bound what a provider can allocate.
"""

import json
import platform
import subprocess
from dataclasses import dataclass

TIMEOUT_SECONDS = 5


@dataclass
class GPUInfo:
    model: str
    count: int
    vram_gb: int
    vendor: str


def _run(argv: list[str]) -> str | None:
    try:
        result = subprocess.run(argv, capture_output=True, text=True, check=True, timeout=TIMEOUT_SECONDS)
        return result.stdout
    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return None


def detect_nvidia() -> list[dict]:
    out = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
    gpus = []
    for line in (out or "").strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 2 and parts[1].isdigit():
            gpus.append({"vendor": "NVIDIA", "model": parts[0][:200], "vram_mb": int(parts[1])})
    return gpus


def detect_amd() -> list[dict]:
    out = _run(["rocm-smi", "--showproductname", "--showmeminfo", "vram", "--json"])
    if not out:
        return []
    try:
        data = json.loads(out)
    except ValueError:
        return []
    gpus = []
    for key, card in sorted(data.items()):
        if not key.startswith("card") or not isinstance(card, dict):
            continue
        total = card.get("VRAM Total Memory (B)") or card.get("vram Total Memory (B)")
        try:
            vram_mb = int(int(total) // (1024 * 1024))
        except (TypeError, ValueError):
            continue
        model = card.get("Card series") or card.get("Card SKU") or card.get("Card model") or "AMD GPU"
        gpus.append({"vendor": "AMD", "model": str(model)[:200], "vram_mb": vram_mb})
    return gpus


def detect_apple() -> list[dict]:
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return []
    out = _run(["system_profiler", "SPDisplaysDataType", "-json"])
    mem = _run(["sysctl", "-n", "hw.memsize"])
    try:
        displays = json.loads(out or "{}").get("SPDisplaysDataType", [])
        ram_mb = int((mem or "0").strip()) // (1024 * 1024)
    except (ValueError, AttributeError):
        return []
    model = next((d.get("sppci_model") for d in displays if d.get("sppci_model")), "Apple GPU")
    if not ram_mb:
        return []
    return [{"vendor": "Apple", "model": str(model)[:200], "vram_mb": ram_mb * 2 // 3, "shared": True}]


def detect_all() -> list[dict]:
    """All GPUs found by any detector."""
    return detect_nvidia() + detect_amd() + detect_apple()


def detect_gpus() -> GPUInfo:
    """Summary of the first vendor found (kept for the legacy hardware fields)."""
    gpus = detect_all()
    if not gpus:
        return GPUInfo(model="No GPU detected", count=0, vram_gb=0, vendor="None")
    first = gpus[0]
    same = [g for g in gpus if g["vendor"] == first["vendor"]]
    return GPUInfo(model=first["model"], count=len(same), vram_gb=first["vram_mb"] // 1024, vendor=first["vendor"])
