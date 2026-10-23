import json
from unittest.mock import patch

from node_agent.hardware import gpu


def _fake(outputs):
    def run(argv):
        return outputs.get(argv[0])

    return run


def test_nvidia_reports_each_gpu():
    out = "NVIDIA GeForce RTX 4090, 24564\nNVIDIA GeForce RTX 3090, 24576\n"
    with patch.object(gpu, "_run", _fake({"nvidia-smi": out})):
        assert gpu.detect_nvidia() == [
            {"vendor": "NVIDIA", "model": "NVIDIA GeForce RTX 4090", "vram_mb": 24564},
            {"vendor": "NVIDIA", "model": "NVIDIA GeForce RTX 3090", "vram_mb": 24576},
        ]


def test_amd_rocm_smi_json():
    out = json.dumps(
        {
            "card0": {"Card series": "Radeon RX 7900 XTX", "VRAM Total Memory (B)": str(24 * 1024**3)},
            "card1": {"Card series": "Radeon Pro W7800", "VRAM Total Memory (B)": "not-a-number"},
            "system": {"Driver version": "6.x"},
        }
    )
    with patch.object(gpu, "_run", _fake({"rocm-smi": out})):
        assert gpu.detect_amd() == [{"vendor": "AMD", "model": "Radeon RX 7900 XTX", "vram_mb": 24576}]


def test_apple_silicon_unified_memory_estimate():
    out = json.dumps({"SPDisplaysDataType": [{"sppci_model": "Apple M2 Pro"}]})
    with (
        patch.object(gpu.platform, "system", return_value="Darwin"),
        patch.object(gpu.platform, "machine", return_value="arm64"),
        patch.object(gpu, "_run", _fake({"system_profiler": out, "sysctl": str(32 * 1024**3)})),
    ):
        assert gpu.detect_apple() == [{"vendor": "Apple", "model": "Apple M2 Pro", "vram_mb": 21845, "shared": True}]


def test_no_tools_means_no_gpus_and_no_crash():
    with patch.object(gpu, "_run", lambda argv: None):
        assert gpu.detect_all() == []
        assert gpu.detect_gpus().count == 0


def test_garbage_output_is_ignored():
    with patch.object(gpu, "_run", _fake({"nvidia-smi": "error: driver mismatch\n", "rocm-smi": "{not json"})):
        assert gpu.detect_all() == []
