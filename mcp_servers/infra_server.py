"""
SentinelAI — InfraMCP Server (LIVE)
Exposes infrastructure action tools via MCP protocol backed by Docker.

Tools:
  1. restart_service       — Restart or start a container
  2. scale_service         — Scale service replicas with docker-compose
  3. get_deployment_history — Read-only container info (no real deploy history)
  4. get_container_status  — Container status and health
  5. flush_cache           — FLUSHALL on sentinel-redis

Run:
  python -m mcp_servers.infra_server
"""

import json
import logging
import subprocess
import time
from typing import Optional

import docker
import httpx
from mcp.server.fastmcp import FastMCP

from backend import prometheus_client

logger = logging.getLogger(__name__)

mcp = FastMCP("SentinelAI-Infra")

_docker_client: Optional[docker.DockerClient] = None

SERVICE_PORTS = {
    "user-service": 8001,
    "payment-service": 8002,
    "api-gateway": 8003,
}


def _get_client() -> docker.DockerClient:
    global _docker_client
    if _docker_client is None:
        _docker_client = docker.from_env()
    return _docker_client


@mcp.tool()
def restart_service(service: str, reason: str = "") -> str:
    """
    Restart a service container. If the container is stopped (status=exited),
    this will start it instead of calling restart() — important for kill_service.

    Risk level: RISKY — brief downtime while the container restarts.
    """
    logger.info("[INFRA_MCP] restart_service called: service=%s reason=%s", service, reason)
    client = _get_client()
    container_name = f"sentinel-{service}"
    try:
        container = client.containers.get(container_name)
    except docker.errors.NotFound:
        return json.dumps(
            {
                "tool": "restart_service",
                "error": f"Container '{container_name}' not found",
                "service": service,
            },
            indent=2,
        )

    start = time.time()
    status = container.status
    try:
        action = "start" if status == "exited" else "restart"
        logger.info("[INFRA_MCP] Container %s action=%s (start vs restart)", container_name, action)
        if status == "exited":
            container.start()
        else:
            container.restart(timeout=10)
    except Exception as e:
        return json.dumps(
            {
                "tool": "restart_service",
                "service": service,
                "status": "failed",
                "error": str(e),
            },
            indent=2,
        )

    # Wait for health endpoint where applicable
    port = SERVICE_PORTS.get(service)
    if port:
        url = f"http://{service}:{port}/health"
        for _ in range(30):
            try:
                resp = httpx.get(url, timeout=5.0)
                if resp.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(1)

    downtime = round(time.time() - start, 1)

    container.reload()
    return json.dumps(
        {
            "tool": "restart_service",
            "risk_level": "risky",
            "status": "success",
            "service": service,
            "downtime_seconds": downtime,
            "reason": reason,
            "container_status": container.status,
        },
        indent=2,
    )


@mcp.tool()
def scale_service(service: str, replicas: int, reason: str = "") -> str:
    """
    Scale a service to N replicas using docker-compose.

    Risk:
      - SAFE when scaling up
      - RISKY when scaling down
    """
    logger.info("[INFRA_MCP] scale_service called: service=%s replicas=%d reason=%s", service, replicas, reason)
    if replicas < 1:
        return json.dumps(
            {
                "tool": "scale_service",
                "error": "replicas must be >= 1",
                "service": service,
            },
            indent=2,
        )

    direction = "up" if replicas > 1 else "down"
    risk = "safe" if direction == "up" else "risky"

    try:
        subprocess.run(
            ["docker-compose", "up", "-d", "--scale", f"{service}={replicas}", "--no-recreate"],
            check=True,
        )
    except subprocess.CalledProcessError as e:
        return json.dumps(
            {
                "tool": "scale_service",
                "service": service,
                "status": "failed",
                "error": str(e),
            },
            indent=2,
        )

    return json.dumps(
        {
            "tool": "scale_service",
            "risk_level": risk,
            "status": "success",
            "service": service,
            "replicas": replicas,
            "reason": reason,
        },
        indent=2,
    )


@mcp.tool()
def get_deployment_history(service: str) -> str:
    """
    Read-only container info from Docker via backend.prometheus_client.get_deployment_info().

    Note: This infrastructure uses single-version containers.
    Restarts do NOT indicate code deployments; recent_deploy is always False.
    """
    try:
        info = prometheus_client.get_deployment_info(service)
    except Exception as e:
        return json.dumps(
            {
                "tool": "get_deployment_history",
                "service": service,
                "status": "failed",
                "error": str(e),
            },
            indent=2,
        )

    return json.dumps(
        {
            "tool": "get_deployment_history",
            "risk_level": "safe",
            "service": service,
            "deployment_info": info,
        },
        indent=2,
    )


@mcp.tool()
def get_container_status(service: str) -> str:
    """
    Return container status and basic health info for a service.
    Used by the Diagnostician to detect service_down vs healthy.
    """
    client = _get_client()
    container_name = f"sentinel-{service}"
    try:
        container = client.containers.get(container_name)
    except docker.errors.NotFound:
        return json.dumps(
            {
                "tool": "get_container_status",
                "service": service,
                "error": f"Container '{container_name}' not found",
            },
            indent=2,
        )

    state = container.attrs.get("State", {})
    health = state.get("Health", {}).get("Status", "unknown")
    return json.dumps(
        {
            "tool": "get_container_status",
            "service": service,
            "status": container.status,
            "health": health,
            "started_at": state.get("StartedAt"),
            "restart_count": state.get("RestartCount", 0),
            "image": (container.image.tags[0] if container.image.tags else "unknown"),
        },
        indent=2,
    )


@mcp.tool()
def flush_cache() -> str:
    """
    Flush all keys from Redis cache (sentinel-redis).

    Risk level: SAFE — clears cache but does not affect code or containers.
    """
    logger.info("[INFRA_MCP] flush_cache called on sentinel-redis")
    client = _get_client()
    try:
        redis_container = client.containers.get("sentinel-redis")
    except docker.errors.NotFound:
        return json.dumps(
            {
                "tool": "flush_cache",
                "status": "failed",
                "error": "sentinel-redis container not found",
            },
            indent=2,
        )

    result = redis_container.exec_run("redis-cli FLUSHALL")
    output = result.output.decode() if isinstance(result.output, (bytes, bytearray)) else str(result.output)

    return json.dumps(
        {
            "tool": "flush_cache",
            "risk_level": "safe",
            "status": "success",
            "action": "cache_flushed",
            "output": output.strip(),
        },
        indent=2,
    )


if __name__ == "__main__":
    mcp.run()