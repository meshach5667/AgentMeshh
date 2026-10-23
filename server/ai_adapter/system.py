"""What this machine has and how busy it is. Linux /proc and /sys only; nothing is assumed about the CPU,
memory, disk, or GPU."""

import os
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Gemma 4 variants that fit a CPU-only laptop, with download sizes verified against the Ollama registry
# manifests (2026-10-21). Memory needed is the weights plus about 1.5 GB for a 4096-token context and the
# runtime; treat it as an estimate and confirm with `python -m ai_adapter check`.
GEMMA4_CHOICES = [
    # tag, download bytes, estimated RAM needed (MB)
    ("gemma4:e2b-it-qat", 4_336_357_640, 6_000),
    ("gemma4:e4b-it-qat", 6_146_501_256, 8_000),
]
DISK_MARGIN = 1.2  # free space wanted relative to the download


@dataclass
class Hardware:
    cpu_model: str | None
    logical_cpus: int
    cpu_flags: list[str]
    mem_total_mb: int
    mem_available_mb: int
    swap_free_mb: int
    disk_free_mb: int
    models_dir: str
    accelerators: list[str] = field(default_factory=list)  # "nvidia", "amd-rocm"; empty means CPU inference
    integrated_gpu: str | None = None  # present but not used by Ollama for acceleration by default

    def as_dict(self) -> dict:
        return asdict(self)


def _meminfo() -> dict[str, int]:
    out = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            out[key] = int(rest.split()[0]) // 1024  # kB -> MB
    except (OSError, ValueError, IndexError):
        pass
    return out


def _cpuinfo() -> tuple[str | None, list[str]]:
    model: str | None = None
    flags: list[str] = []
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name") and model is None:
                model = line.split(":", 1)[1].strip()
            elif line.startswith("flags") and not flags:
                wanted = {"avx", "avx2", "avx512f", "avx512_vnni", "f16c", "fma"}
                flags = sorted(wanted & set(line.split(":", 1)[1].split()))
    except OSError:
        pass
    return model, flags


def models_dir() -> Path:
    """Where Ollama stores models: OLLAMA_MODELS, the system service's home, or the user's."""
    if os.environ.get("OLLAMA_MODELS"):
        return Path(os.environ["OLLAMA_MODELS"])
    # The system service's directory is usually unreadable to other users; its parent tells us the disk.
    if Path("/usr/share/ollama").exists():
        return Path("/usr/share/ollama/.ollama/models")
    return Path.home() / ".ollama" / "models"


def _free_mb(path: Path) -> int:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        return shutil.disk_usage(probe).free // (1024 * 1024)
    except OSError:
        return 0


def _accelerators() -> tuple[list[str], str | None]:
    found = []
    # A GPU device, not just installed tools: nvidia-smi and /dev/nvidiactl can exist without any GPU.
    if Path("/dev/nvidia0").exists() or any(Path("/proc/driver/nvidia/gpus").glob("*")):
        found.append("nvidia")
    if Path("/dev/kfd").exists():
        found.append("amd-rocm")
    igpu = None
    for vendor in Path("/sys/class/drm").glob("card*/device/vendor"):
        try:
            if vendor.read_text().strip() == "0x8086":
                igpu = "intel"
        except OSError:
            pass
    return found, igpu


def hardware() -> Hardware:
    mem = _meminfo()
    model, flags = _cpuinfo()
    accel, igpu = _accelerators()
    mdir = models_dir()
    return Hardware(
        cpu_model=model,
        logical_cpus=os.cpu_count() or 1,
        cpu_flags=flags,
        mem_total_mb=mem.get("MemTotal", 0),
        mem_available_mb=mem.get("MemAvailable", 0),
        swap_free_mb=mem.get("SwapFree", 0),
        disk_free_mb=_free_mb(mdir),
        models_dir=str(mdir),
        accelerators=accel,
        integrated_gpu=igpu,
    )


@dataclass
class Recommendation:
    tag: str | None
    reason: str
    download_mb: int = 0
    ram_needed_mb: int = 0


def recommend(hw: Hardware) -> Recommendation:
    """Largest verified Gemma 4 variant that fits in total RAM with room left for the rest of the machine."""
    if "avx2" not in hw.cpu_flags and not hw.accelerators:
        return Recommendation(None, "the CPU lacks AVX2; CPU inference would be very slow")
    budget = hw.mem_total_mb * 0.6  # leave 40% for the desktop, browser, and other applications
    fitting = [c for c in GEMMA4_CHOICES if c[2] <= budget]
    if not fitting:
        return Recommendation(None, f"{hw.mem_total_mb} MB RAM is not enough for any verified Gemma 4 variant")
    # On CPU-only machines prefer the smallest: e4b is roughly twice as slow per token.
    tag, size, ram = fitting[0] if not hw.accelerators else fitting[-1]
    return Recommendation(tag, "CPU inference" if not hw.accelerators else "GPU available", size // 2**20, ram)


def pull_problems(hw: Hardware, tag: str) -> list[str]:
    """Reasons not to download ``tag`` now. Unknown tags are refused rather than guessed."""
    match = next((c for c in GEMMA4_CHOICES if c[0] == tag), None)
    if match is None:
        return [f"{tag} is not a verified variant for this adapter ({', '.join(c[0] for c in GEMMA4_CHOICES)})"]
    _, size, ram = match
    problems = []
    need_disk = int(size * DISK_MARGIN) // 2**20
    if hw.disk_free_mb < need_disk:
        problems.append(f"needs {need_disk} MB free disk in {hw.models_dir}, {hw.disk_free_mb} MB available")
    if hw.mem_total_mb < ram:
        problems.append(f"needs about {ram} MB RAM, the machine has {hw.mem_total_mb} MB")
    return problems


class LoadMonitor:
    """CPU and memory pressure, sampled from /proc between calls."""

    def __init__(self) -> None:
        self._last: tuple[int, int] | None = None

    @staticmethod
    def _cpu_times() -> tuple[int, int] | None:
        try:
            parts = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
            values = [int(v) for v in parts]
            idle = values[3] + (values[4] if len(values) > 4 else 0)
            return sum(values), idle
        except (OSError, ValueError, IndexError):
            return None

    def sample(self) -> dict:
        mem = _meminfo()
        try:
            load1 = os.getloadavg()[0]
        except OSError:
            load1 = 0.0
        cpu_percent = None
        now = self._cpu_times()
        if now and self._last:
            total, idle = now[0] - self._last[0], now[1] - self._last[1]
            if total > 0:
                cpu_percent = round(100.0 * (total - idle) / total, 1)
        self._last = now
        return {
            "cpu_percent": cpu_percent,
            "load_per_cpu": round(load1 / (os.cpu_count() or 1), 2),
            "mem_available_mb": mem.get("MemAvailable"),
            "mem_total_mb": mem.get("MemTotal"),
            "sampled_at": time.time(),
        }
