import os
import platform
from dataclasses import dataclass
from typing import Any

import psutil

from .gpu import detect_all, detect_gpus


@dataclass
class HardwareInfo:
    cpu_model: str
    cpu_cores: int
    ram_gb: int
    storage_gb: int
    os_info: str


def discover_cpu_ram_storage(path: str = "/") -> HardwareInfo:
    cpu_model = platform.processor() or platform.machine() or "Unknown CPU"
    cpu_cores = psutil.cpu_count(logical=True) or 1
    ram_gb = psutil.virtual_memory().total // (1024**3)
    storage_gb = psutil.disk_usage(path).total // (1024**3)
    os_info = platform.platform()
    return HardwareInfo(cpu_model=cpu_model, cpu_cores=cpu_cores, ram_gb=ram_gb, storage_gb=storage_gb, os_info=os_info)


def _cpu_model() -> str:
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()[:200]
    except OSError:
        pass
    return (platform.processor() or platform.machine() or "unknown")[:200]


def hardware_report(data_dir: str) -> dict[str, Any]:
    """Hardware summary sent to the control plane. Only capacity facts; no hostnames, users, or files."""
    os.makedirs(data_dir, exist_ok=True)
    # The protocol carries vendor/model/vram only; the "shared" (unified memory) hint stays local.
    gpus = [{"vendor": g["vendor"][:50], "model": g["model"][:200], "vram_mb": g["vram_mb"]} for g in detect_all()]
    return {
        "os": platform.system()[:100],
        "arch": platform.machine()[:50],
        "cpu_model": _cpu_model(),
        "cpu_cores": psutil.cpu_count(logical=True) or 1,
        "ram_mb": psutil.virtual_memory().total // (1024**2),
        "disk_free_mb": psutil.disk_usage(data_dir).free // (1024**2),
        "gpus": gpus,
    }


def default_allocation(hw: dict[str, Any], settings) -> dict[str, int]:
    """Resources offered to AgentMesh: explicit provider limits, else conservative defaults."""
    total_vram = sum(g["vram_mb"] for g in hw["gpus"])
    cpu = settings.MAX_CPU_CORES if settings.MAX_CPU_CORES is not None else max(1, hw["cpu_cores"] // 2)
    ram = settings.MAX_RAM_MB if settings.MAX_RAM_MB is not None else hw["ram_mb"] // 2
    disk = settings.MAX_DISK_MB if settings.MAX_DISK_MB is not None else min(20 * 1024, hw["disk_free_mb"] // 2)
    vram = 0
    if settings.ALLOW_GPU:
        vram = settings.MAX_VRAM_MB if settings.MAX_VRAM_MB is not None else total_vram
    return {
        "cpu_cores": max(0, min(cpu, hw["cpu_cores"])),
        "ram_mb": max(0, min(ram, hw["ram_mb"])),
        "disk_mb": max(0, min(disk, hw["disk_free_mb"])),
        "vram_mb": max(0, min(vram, total_vram)),
    }


def discover_all() -> dict[str, Any]:
    hw = discover_cpu_ram_storage()
    gpu = detect_gpus()
    return {
        "cpu_model": hw.cpu_model,
        "cpu_cores": hw.cpu_cores,
        "ram_gb": hw.ram_gb,
        "storage_gb": hw.storage_gb,
        "os_info": hw.os_info,
        "gpu_model": gpu.model,
        "gpu_count": gpu.count,
        "gpu_vram_gb": gpu.vram_gb,
        "capabilities": ["cpu", "gpu"] if gpu.count > 0 else ["cpu"],
    }
