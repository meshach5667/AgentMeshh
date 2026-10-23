def recommend_price(gpu_model: str, vram: int, region: str) -> float:
    base_price = 0.5
    if "H100" in gpu_model:
        return base_price + 3.0
    elif "A100" in gpu_model:
        return base_price + 2.0
    elif "4090" in gpu_model:
        return base_price + 0.5
    return base_price


def calculate_deployment_cost(
    gpu_seconds: float, cpu_seconds: float, gpu_hour_price: float, cpu_hour_price: float
) -> float:
    gpu_cost = (gpu_seconds / 3600.0) * gpu_hour_price
    cpu_cost = (cpu_seconds / 3600.0) * cpu_hour_price
    return gpu_cost + cpu_cost
