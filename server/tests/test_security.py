import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_invalid_token(client: AsyncClient):
    headers = {"Authorization": "Bearer invalid_token"}
    response = await client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_unauthenticated_nodes_access(client: AsyncClient):
    response = await client.get("/api/v1/nodes")
    assert response.status_code == 401
