"""Dynamic REST ↔ MCP Universal Adapter.

Translates standard OpenAPI 3.x and Swagger 2.0 specifications into MCP tool definitions
and proxies execution between MCP JSON-RPC protocol and upstream REST APIs.
"""

import json
import logging
import re
import time
from typing import Any
from urllib.parse import urljoin, quote

import httpx

from ..broker.discovery import DiscoveryError
from .http_security import bounded_client, validate_public_url as check_public_url

log = logging.getLogger("agent_market.concierge.rest_adapter")

HTTP_METHODS = {"get", "post", "put", "delete", "patch"}


class OpenApiAdapterError(Exception):
    """Base exception for OpenAPI adapter errors."""
    pass


def sanitize_tool_name(name: str) -> str:
    """Sanitizes operationId or path into a valid MCP tool name (alphanumeric + underscores)."""
    clean = re.sub(r"[^a-zA-Z0-9_]+", "_", name).strip("_")
    if clean and clean[0].isdigit():
        clean = f"tool_{clean}"
    return clean or "rest_tool"


def extract_base_url(spec: dict[str, Any], override_base_url: str | None = None) -> str:
    """Extracts the base API URL from OpenAPI 3.x or Swagger 2.0 specification."""
    if override_base_url:
        return override_base_url.rstrip("/")

    # OpenAPI 3.x servers
    servers = spec.get("servers")
    if isinstance(servers, list) and servers:
        first_url = servers[0].get("url")
        if first_url and not first_url.startswith(("/", "{")):
            return first_url.rstrip("/")

    # Swagger 2.0 host + basePath
    host = spec.get("host")
    if host:
        schemes = spec.get("schemes") or ["https"]
        scheme = schemes[0] if isinstance(schemes, list) and schemes else "https"
        base_path = spec.get("basePath") or ""
        return f"{scheme}://{host}{base_path}".rstrip("/")

    return ""


def parse_openapi_spec(spec: dict[str, Any], base_url: str | None = None) -> list[dict[str, Any]]:
    """Converts an OpenAPI 3.x or Swagger 2.0 spec into MCP Tool definitions."""
    tools: list[dict[str, Any]] = []
    resolved_base = extract_base_url(spec, base_url)
    paths = spec.get("paths") or {}
    if not isinstance(paths, dict):
        return tools

    for path_str, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue

        common_params = path_item.get("parameters") or []

        for method, op in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(op, dict):
                continue

            op_id = op.get("operationId")
            if op_id:
                tool_name = sanitize_tool_name(op_id)
            else:
                tool_name = sanitize_tool_name(f"{method}_{path_str}")

            summary = op.get("summary") or op.get("description") or f"{method.upper()} {path_str}"
            desc = f"{summary} [{method.upper()} {path_str}]".strip()

            properties: dict[str, Any] = {}
            required: list[str] = []
            param_locations: dict[str, str] = {}

            # Process parameters (common + operation-specific)
            all_params = list(common_params) + (op.get("parameters") or [])
            for p in all_params:
                if not isinstance(p, dict):
                    continue
                p_name = p.get("name")
                p_in = p.get("in")  # path, query, header, body
                if not p_name or not p_in:
                    continue

                param_locations[p_name] = p_in
                p_schema = p.get("schema") or {"type": p.get("type", "string")}
                p_type = p_schema.get("type", "string") if isinstance(p_schema, dict) else "string"
                p_desc = p.get("description") or ""

                properties[p_name] = {
                    "type": p_type,
                    "description": f"[{p_in}] {p_desc}".strip(),
                }
                if p.get("required") or p_in == "path":
                    if p_name not in required:
                        required.append(p_name)

                # Swagger 2.0 in: body
                if p_in == "body" and isinstance(p_schema, dict) and p_schema.get("properties"):
                    for bp_name, bp_schema in p_schema["properties"].items():
                        if bp_name not in properties:
                            properties[bp_name] = bp_schema
                            param_locations[bp_name] = "body"
                    if isinstance(p_schema.get("required"), list):
                        for req_prop in p_schema["required"]:
                            if req_prop not in required:
                                required.append(req_prop)

            # OpenAPI 3.x requestBody
            rb = op.get("requestBody")
            if isinstance(rb, dict):
                content = rb.get("content") or {}
                json_media = content.get("application/json") or {}
                json_schema = json_media.get("schema")
                if isinstance(json_schema, dict):
                    body_props = json_schema.get("properties") or {}
                    for bp_name, bp_schema in body_props.items():
                        if bp_name not in properties:
                            properties[bp_name] = bp_schema
                            param_locations[bp_name] = "body"
                    if isinstance(json_schema.get("required"), list):
                        for req_prop in json_schema["required"]:
                            if req_prop not in required:
                                required.append(req_prop)

            tool_def = {
                "name": tool_name,
                "description": desc,
                "inputSchema": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
                "_meta": {
                    "method": method.upper(),
                    "path": path_str,
                    "base_url": resolved_base,
                    "param_locations": param_locations,
                },
            }
            tools.append(tool_def)

    return tools


class OpenApiAdapter:
    """Manages OpenAPI specification parsing and dynamic MCP tool execution."""

    def __init__(self, spec: dict[str, Any], base_url: str | None = None,
                 allow_private: bool = False, http: httpx.Client | None = None):
        self.spec = spec
        self.base_url = extract_base_url(spec, base_url)
        self.allow_private = allow_private
        self._http = http
        self.tools = parse_openapi_spec(spec, self.base_url)
        self._tools_by_name = {t["name"]: t for t in self.tools}

    @classmethod
    def from_url(cls, spec_url: str, base_url: str | None = None,
                 allow_private: bool = False, http: httpx.Client | None = None) -> "OpenApiAdapter":
        """Fetches and builds an OpenApiAdapter from a remote spec URL."""
        client = bounded_client(http, allow_private=allow_private, timeout=15.0)
        if not allow_private:
            check_public_url(spec_url)
        try:
            resp = client.get(spec_url)
            resp.raise_for_status()
            spec_data = resp.json()
            if not isinstance(spec_data, dict):
                raise OpenApiAdapterError(f"Invalid OpenAPI specification from {spec_url}")
        finally:
            if http is None:
                client.close()
        return cls(spec_data, base_url=base_url or spec_url.rsplit("/", 1)[0],
                   allow_private=allow_private, http=http)

    def _client(self) -> httpx.Client:
        return bounded_client(self._http, allow_private=self.allow_private, timeout=15.0)

    def execute(self, tool_name: str, arguments: dict[str, Any] | None = None,
                headers: dict[str, str] | None = None) -> dict[str, Any]:
        """Executes a tool on the upstream REST API and translates the result into standard MCP format."""
        arguments = arguments or {}
        tool_spec = self._tools_by_name.get(tool_name)
        if not tool_spec:
            return {"ok": False, "error": f"Tool '{tool_name}' not found in OpenAPI specification."}

        meta = tool_spec.get("_meta") or {}
        method = meta.get("method", "GET").upper()
        raw_path = meta.get("path", "")
        param_locations = meta.get("param_locations") or {}
        base = meta.get("base_url") or self.base_url

        if not base:
            return {"ok": False, "error": "No base URL configured or discoverable for this REST API."}

        # 1. Path parameter substitution
        interpolated_path = raw_path
        used_args = set()
        for param_match in re.findall(r"\{([a-zA-Z0-9_]+)\}", raw_path):
            if param_match not in arguments:
                return {"ok": False, "error": f"Missing required path parameter: '{param_match}'"}
            val = str(arguments[param_match])
            interpolated_path = interpolated_path.replace(f"{{{param_match}}}", quote(val, safe=""))
            used_args.add(param_match)

        # 2. Build URL
        full_url = urljoin(f"{base}/", interpolated_path.lstrip("/"))

        if not self.allow_private:
            try:
                check_public_url(full_url)
            except DiscoveryError as exc:
                return {"ok": False, "error": f"SSRF Protection: {exc}"}

        # 3. Categorize remaining arguments into query, body, headers
        query_params: dict[str, Any] = {}
        body_params: dict[str, Any] = {}
        req_headers = dict(headers or {})

        for k, v in arguments.items():
            if k in used_args:
                continue
            loc = param_locations.get(k)
            if loc == "query":
                query_params[k] = v
            elif loc == "header":
                req_headers[k] = str(v)
            elif loc == "body":
                body_params[k] = v
            else:
                # Default heuristics based on HTTP method
                if method in ("GET", "DELETE"):
                    query_params[k] = v
                else:
                    body_params[k] = v

        client = self._client()
        started = time.monotonic()
        try:
            req_kwargs: dict[str, Any] = {"headers": req_headers, "timeout": httpx.Timeout(15.0, connect=5.0)}
            if query_params:
                req_kwargs["params"] = query_params
            if method in ("POST", "PUT", "PATCH") and body_params:
                req_kwargs["json"] = body_params

            from ..observability import provider_dispatch
            provider_dispatch()
            resp = client.request(method, full_url, **req_kwargs)
            elapsed_ms = int((time.monotonic() - started) * 1000)

            # Parse response
            content_type = resp.headers.get("content-type", "")
            if "application/json" in content_type:
                try:
                    result_data = resp.json()
                except Exception:
                    result_data = resp.text
            else:
                result_data = resp.text

            is_ok = resp.is_success
            sample_text = json.dumps(result_data, ensure_ascii=False) if isinstance(result_data, (dict, list)) else str(result_data)

            return {
                "ok": is_ok,
                "status_code": resp.status_code,
                "tool": tool_name,
                "url": full_url,
                "latency_ms": elapsed_ms,
                "result": result_data,
                "sample_output": sample_text[:500] if sample_text else "",
                "content": [{"type": "text", "text": sample_text[:2000]}],
                "isError": not is_ok,
            }

        except httpx.HTTPError as exc:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            return {
                "ok": False,
                "error": f"HTTP Error ({type(exc).__name__}): {exc}",
                "tool": tool_name,
                "url": full_url,
                "latency_ms": elapsed_ms,
            }
        finally:
            client.close()

    def close(self):
        if hasattr(self._http, "close") and hasattr(self._http, "owned"):
            self._http.close()
