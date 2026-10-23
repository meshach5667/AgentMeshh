import subprocess
from typing import Any

import psutil


class MetricsCollector:
    def collect_metrics(self) -> dict[str, Any]:
        metrics = {
            "cpu_percent": psutil.cpu_percent(interval=1),
            "ram_used_gb": psutil.virtual_memory().used / (1024**3),
            "ram_total_gb": psutil.virtual_memory().total / (1024**3),
            "disk_used_gb": psutil.disk_usage("/").used / (1024**3),
            "disk_total_gb": psutil.disk_usage("/").total / (1024**3),
        }

        net_io = psutil.net_io_counters()
        metrics["network_bytes_sent"] = net_io.bytes_sent
        metrics["network_bytes_recv"] = net_io.bytes_recv

        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used,temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            lines = result.stdout.strip().split("\n")
            if lines and lines[0]:
                parts = lines[0].split(",")
                metrics["gpu_utilization"] = float(parts[0].strip())
                metrics["gpu_memory_used_mb"] = float(parts[1].strip())
                metrics["gpu_temperature"] = float(parts[2].strip())
        except (subprocess.SubprocessError, FileNotFoundError, ValueError):
            pass

        return metrics

    def get_summary(self) -> dict[str, Any]:
        metrics = self.collect_metrics()
        summary = {
            "cpu_percent": metrics.get("cpu_percent", 0.0),
            "ram_percent": (metrics.get("ram_used_gb", 0) / metrics.get("ram_total_gb", 1)) * 100,
        }
        if "gpu_utilization" in metrics:
            summary["gpu_utilization"] = metrics["gpu_utilization"]
        return summary
