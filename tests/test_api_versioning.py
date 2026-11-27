"""Tests for API Versioning (v1 vs v2) across the API Gateway."""

from __future__ import annotations

import pytest

from tests.conftest import ZeptoTestMesh


@pytest.mark.anyio
async def test_catalogues_api_v1_and_v2(zepto_mesh: ZeptoTestMesh):
    async with zepto_mesh.gateway_client() as client:
        v1 = await client.get("/api/v1/catalogues/products")
        assert v1.status_code == 200
        assert v1.headers.get("X-API-Version") == "v1"
        assert v1.headers.get("Deprecation") == "true"
        v1_body = v1.json()
        assert v1_body["api_version"] == "v1"
        assert "price_inr" in v1_body["items"][0]
        assert "pricing" not in v1_body["items"][0]

        v2 = await client.get("/api/v2/catalogues/products?category=Dairy%20%26%20Bread")
        assert v2.status_code == 200
        assert v2.headers.get("X-API-Version") == "v2"
        v2_body = v2.json()
        assert v2_body["api_version"] == "v2"
        assert v2_body["pagination"]["total"] == 4
        assert v2_body["items"][0]["fulfillment"]["promise"].endswith("mins")
        assert "selling_inr" in v2_body["items"][0]["pricing"]
