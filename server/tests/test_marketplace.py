import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_marketplace_nodes(client: AsyncClient):
    response = await client.get("/api/v1/marketplace/nodes")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_marketplace_pricing(client: AsyncClient):
    response = await client.get("/api/v1/marketplace/pricing")
    assert response.status_code == 200
