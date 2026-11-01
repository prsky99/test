"""Tests for Dynamic REST ↔ MCP Universal Adapter."""

import httpx
import pytest
from agent_market.concierge.rest_adapter import (
    OpenApiAdapter,
    parse_openapi_spec,
    sanitize_tool_name,
)

SAMPLE_OPENAPI_3 = {
    "openapi": "3.0.0",
    "info": {"title": "Weather & Orders API", "version": "1.0.0"},
    "servers": [{"url": "https://api.example.com/v1"}],
    "paths": {
        "/weather/{city}": {
            "get": {
                "operationId": "get_weather_forecast",
                "summary": "Get weather forecast for a city",
                "parameters": [
                    {"name": "city", "in": "path", "required": True, "schema": {"type": "string"}, "description": "City name"},
                    {"name": "days", "in": "query", "required": False, "schema": {"type": "integer"}, "description": "Number of days"},
                ],
            }
        },
        "/orders": {
            "post": {
                "operationId": "create_new_order",
                "summary": "Create a new purchase order",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "item": {"type": "string", "description": "Item name"},
                                    "quantity": {"type": "integer", "description": "Quantity"},
                                },
                                "required": ["item"],
                            }
                        }
                    },
                },
            }
        },
    },
}

SAMPLE_SWAGGER_2 = {
    "swagger": "2.0",
    "info": {"title": "Swagger Petstore", "version": "1.0.0"},
    "host": "petstore.example.com",
    "basePath": "/api",
    "schemes": ["https"],
    "paths": {
        "/pets": {
            "get": {
                "operationId": "findPets",
                "summary": "Finds Pets",
                "parameters": [
                    {"name": "status", "in": "query", "type": "string", "required": False}
                ],
            }
        }
    },
}


def test_sanitize_tool_name():
    assert sanitize_tool_name("getWeather_123") == "getWeather_123"
    assert sanitize_tool_name("get /v1/weather/{city}") == "get_v1_weather_city"
    assert sanitize_tool_name("123_tool") == "tool_123_tool"


def test_parse_openapi_spec():
    tools = parse_openapi_spec(SAMPLE_OPENAPI_3)
    assert len(tools) == 2
    by_name = {t["name"]: t for t in tools}

    weather_tool = by_name["get_weather_forecast"]
    assert "Get weather forecast" in weather_tool["description"]
    schema = weather_tool["inputSchema"]
    assert schema["type"] == "object"
    assert "city" in schema["properties"]
    assert "days" in schema["properties"]
    assert schema["required"] == ["city"]

    order_tool = by_name["create_new_order"]
    assert "item" in order_tool["inputSchema"]["properties"]
    assert "quantity" in order_tool["inputSchema"]["properties"]
    assert "item" in order_tool["inputSchema"]["required"]


def test_parse_swagger_2():
    tools = parse_openapi_spec(SAMPLE_SWAGGER_2)
    assert len(tools) == 1
    t = tools[0]
    assert t["name"] == "findPets"
    assert t["_meta"]["base_url"] == "https://petstore.example.com/api"


def test_execute_get_with_path_and_query():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.example.com/v1/weather/Tokyo?days=3"
        return httpx.Response(200, json={"city": "Tokyo", "temp_c": 18, "condition": "Sunny"})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)

    adapter = OpenApiAdapter(SAMPLE_OPENAPI_3, allow_private=True, http=client)
    res = adapter.execute("get_weather_forecast", {"city": "Tokyo", "days": 3})

    assert res["ok"] is True
    assert res["status_code"] == 200
    assert res["result"]["temp_c"] == 18
    assert "Tokyo" in res["sample_output"]
    assert res["isError"] is False


def test_execute_post_with_json_body():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.example.com/v1/orders"
        body = request.content.decode("utf-8")
        assert "Laptop" in body
        return httpx.Response(201, json={"order_id": "ord_999", "status": "created"})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)

    adapter = OpenApiAdapter(SAMPLE_OPENAPI_3, allow_private=True, http=client)
    res = adapter.execute("create_new_order", {"item": "Laptop", "quantity": 1})

    assert res["ok"] is True
    assert res["status_code"] == 201
    assert res["result"]["order_id"] == "ord_999"


def test_execute_missing_path_param():
    adapter = OpenApiAdapter(SAMPLE_OPENAPI_3, allow_private=True)
    res = adapter.execute("get_weather_forecast", {"days": 3})
    assert res["ok"] is False
    assert "Missing required path parameter" in res["error"]


def test_ssrf_protection():
    spec_private = {
        "openapi": "3.0.0",
        "servers": [{"url": "http://127.0.0.1:8080"}],
        "paths": {"/status": {"get": {"operationId": "get_status"}}},
    }
    adapter = OpenApiAdapter(spec_private, allow_private=False)
    res = adapter.execute("get_status")
    assert res["ok"] is False
    assert "SSRF Protection" in res["error"]
