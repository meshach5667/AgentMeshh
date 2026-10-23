from node_agent.hardware.discovery import discover_all, discover_cpu_ram_storage


def test_discover_cpu_ram_storage():
    hw = discover_cpu_ram_storage()
    assert hw.cpu_cores > 0
    assert hw.ram_gb >= 0


def test_discover_all():
    hw_all = discover_all()
    assert "cpu_model" in hw_all
    assert "gpu_model" in hw_all
