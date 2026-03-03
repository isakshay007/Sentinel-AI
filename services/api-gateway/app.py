import asyncio
import json
import logging
import os
import random
import subprocess
import time
from typing import Dict, List, Optional

import psutil
import redis
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    CollectorRegistry,
    generate_latest,
)

SERVICE = "api-gateway"

app = FastAPI(title="Sentinel API Gateway", version="0.1.0")

_registry = CollectorRegistry()

CPU_GAUGE = Gauge(
    "service_cpu_percent",
    "CPU usage percent",
    ["service"],
    registry=_registry,
)
MEM_GAUGE = Gauge(
    "service_memory_percent",
    "Memory usage percent",
    ["service"],
    registry=_registry,
)
GC_GAUGE = Gauge(
    "service_gc_pause_ms",
    "Simulated GC pause time in ms",
    ["service"],
    registry=_registry,
)
DB_CONN_ACTIVE = Gauge(
    "service_db_connections_active",
    "Simulated active DB connections",
    ["service"],
    registry=_registry,
)
DB_CONN_MAX = Gauge(
    "service_db_connections_max",
    "Simulated max DB connections",
    ["service"],
    registry=_registry,
)

REQ_DURATION = Histogram(
    "http_request_duration_seconds",
    "Request latency",
    ["service", "method", "endpoint", "status"],
    registry=_registry,
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)
REQ_COUNTER = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["service", "method", "status"],
    registry=_registry,
)

GATEWAY_CACHE_HITS = Counter(
    "gateway_cache_hits_total",
    "Gateway cache hits",
    ["service"],
    registry=_registry,
)
GATEWAY_CACHE_MISSES = Counter(
    "gateway_cache_misses_total",
    "Gateway cache misses",
    ["service"],
    registry=_registry,
)

UPSTREAM_LATENCY = Histogram(
    "gateway_upstream_latency_seconds",
    "Upstream latency per service",
    ["service", "upstream"],
    registry=_registry,
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
_redis_client: Optional[redis.Redis] = None


def get_redis() -> Optional[redis.Redis]:
    global _redis_client
    try:
        if _redis_client is not None:
            _redis_client.ping()
            return _redis_client
    except Exception:
        _redis_client = None
    try:
        _redis_client = redis.Redis.from_url(REDIS_URL, socket_timeout=2, socket_connect_timeout=2)
        _redis_client.ping()
        return _redis_client
    except Exception:
        _redis_client = None
        return None


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "service": SERVICE,
            "message": record.getMessage(),
        }
        return json.dumps(payload)


logger = logging.getLogger(SERVICE)
logger.setLevel(logging.INFO)
_handler = logging.StreamHandler()
_handler.setFormatter(JSONFormatter())
logger.addHandler(_handler)


_chaos_active = False
_memory_chaos = False
_LEAK_BUFFER: List[bytes] = []


async def _controlled_memory_leak(target_percent: int, duration: int) -> None:
    """
    Inflate memory gauge gradually and allocate capped real memory.
    Does NOT use stress-ng for memory — avoids OOM-killing the container.
    """
    global _LEAK_BUFFER, _chaos_active, _memory_chaos
    _LEAK_BUFFER = []

    max_chunks = 20
    chunk_size = 5 * 1024 * 1024
    chunks_allocated = 0
    base_mem = psutil.virtual_memory().percent
    start = time.time()

    logger.info("Controlled memory leak starting: target=%d%% duration=%ds base=%.1f%%",
                target_percent, duration, base_mem)

    while _chaos_active and _memory_chaos and (time.time() - start) < duration:
        elapsed_ratio = min((time.time() - start) / 30.0, 1.0)
        simulated_mem = base_mem + (target_percent - base_mem) * elapsed_ratio
        MEM_GAUGE.labels(service=SERVICE).set(simulated_mem)

        if chunks_allocated < max_chunks:
            try:
                _LEAK_BUFFER.append(bytearray(chunk_size))
                chunks_allocated += 1
            except MemoryError:
                pass

        if simulated_mem > 70:
            DB_CONN_ACTIVE.labels(service=SERVICE).set(min(50, int(simulated_mem * 0.5)))
            GC_GAUGE.labels(service=SERVICE).set(min(1000, simulated_mem * 7))

        await asyncio.sleep(2)

    _LEAK_BUFFER = []
    _memory_chaos = False
    MEM_GAUGE.labels(service=SERVICE).set(psutil.virtual_memory().percent)
    DB_CONN_ACTIVE.labels(service=SERVICE).set(0)
    GC_GAUGE.labels(service=SERVICE).set(0)
    logger.info("Controlled memory leak finished after %.0fs", time.time() - start)


async def metrics_loop() -> None:
    DB_CONN_MAX.labels(service=SERVICE).set(50)
    while True:
        cpu = psutil.cpu_percent(interval=None)
        CPU_GAUGE.labels(service=SERVICE).set(cpu)
        if not _memory_chaos:
            mem = psutil.virtual_memory().percent
            MEM_GAUGE.labels(service=SERVICE).set(mem)
        await asyncio.sleep(5)


async def simulate_gateway_workload() -> None:
    """Background workload: route to upstreams, cache in Redis, rate-limit."""
    await asyncio.sleep(5)
    while True:
        start = time.time()
        status = "200"
        try:
            op = random.choice(["route_user", "route_payment", "cache_check", "rate_limit"])
            r = get_redis()

            if op == "route_user":
                try:
                    async with httpx.AsyncClient(timeout=2.0) as client:
                        resp = await client.get("http://user-service:8001/users")
                        if resp.status_code != 200:
                            status = str(resp.status_code)
                except (httpx.ConnectError, httpx.TimeoutException):
                    status = "504"
                    logger.error("GatewayError: upstream user-service timeout")
            elif op == "route_payment":
                try:
                    async with httpx.AsyncClient(timeout=2.0) as client:
                        resp = await client.get("http://payment-service:8002/payments/1")
                        if resp.status_code >= 500:
                            status = str(resp.status_code)
                except (httpx.ConnectError, httpx.TimeoutException):
                    status = "504"
                    logger.error("GatewayError: upstream payment-service timeout")
            elif op == "cache_check":
                if r is None:
                    raise redis.ConnectionError("Redis unavailable")
                cache_key = f"gw:cache:{random.randint(1, 50)}"
                cached = r.get(cache_key)
                if cached is None:
                    r.setex(cache_key, 30, json.dumps({"data": "cached_response"}))
                    GATEWAY_CACHE_MISSES.labels(service=SERVICE).inc()
                else:
                    GATEWAY_CACHE_HITS.labels(service=SERVICE).inc()
            else:
                if r is None:
                    raise redis.ConnectionError("Redis unavailable")
                rl_key = f"gw:ratelimit:{random.randint(1,20)}"
                r.incr(rl_key)
                r.expire(rl_key, 10)
        except (redis.ConnectionError, redis.TimeoutError):
            status = "500"
            logger.error("GatewayError: Redis cache unavailable — adding fallback delay")
            await asyncio.sleep(random.uniform(0.2, 0.5))
        except Exception as e:
            status = "500"
            logger.error("GatewayWorkloadError: %s", e)
        finally:
            duration = time.time() - start
            REQ_DURATION.labels(service=SERVICE, method="GET", endpoint="/internal/workload", status=status).observe(duration)
            REQ_COUNTER.labels(service=SERVICE, method="GET", status=status).inc()
        await asyncio.sleep(random.uniform(0.05, 0.15))


@app.on_event("startup")
async def startup_event() -> None:
    asyncio.create_task(metrics_loop())
    asyncio.create_task(simulate_gateway_workload())


@app.get("/health")
async def health():
    return {"status": "healthy", "service": SERVICE}


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    data = generate_latest(_registry)
    return PlainTextResponse(data, media_type=CONTENT_TYPE_LATEST)


async def fetch_with_cache(
    client: httpx.AsyncClient,
    cache_key: str,
    method: str,
    url: str,
) -> Dict:
    """Simple Redis-backed cache around upstream calls."""
    try:
        r = get_redis()
        if r:
            cached = r.get(cache_key)
            if cached:
                GATEWAY_CACHE_HITS.labels(service=SERVICE).inc()
                return json.loads(cached.decode("utf-8"))
    except Exception:
        logger.error("CacheConnectionError: unable to connect to Redis at redis:6379")

    # Miss → call upstream
    GATEWAY_CACHE_MISSES.labels(service=SERVICE).inc()
    resp = await client.request(method, url, timeout=5.0)
    resp.raise_for_status()
    data = resp.json()

    try:
        r = get_redis()
        if r:
            r.set(cache_key, json.dumps(data), ex=60)
    except Exception:
        logger.error("CacheConnectionError: unable to connect to Redis at redis:6379")

    return data


@app.get("/api/users")
async def get_users():
    endpoint = "/api/users"
    status_label = "200"
    with REQ_DURATION.labels(service=SERVICE, method="GET", endpoint=endpoint, status=status_label).time():
        async with httpx.AsyncClient() as client:
            with UPSTREAM_LATENCY.labels(service=SERVICE, upstream="user-service").time():
                try:
                    data = await fetch_with_cache(
                        client,
                        cache_key="users:list",
                        method="GET",
                        url="http://user-service:8001/users",
                    )
                except httpx.RequestError:
                    logger.error(
                        "UpstreamTimeout: user-service did not respond within 2000ms",
                    )
                    raise HTTPException(status_code=504, detail="UpstreamTimeout: user-service did not respond within 2000ms")

        REQ_COUNTER.labels(service=SERVICE, method="GET", status=status_label).inc()
        return data


@app.get("/api/users/{user_id}")
async def get_user(user_id: str):
    endpoint = "/api/users/{id}"
    status_label = "200"
    with REQ_DURATION.labels(service=SERVICE, method="GET", endpoint=endpoint, status=status_label).time():
        async with httpx.AsyncClient() as client:
            with UPSTREAM_LATENCY.labels(service=SERVICE, upstream="user-service").time():
                try:
                    data = await fetch_with_cache(
                        client,
                        cache_key=f"user:{user_id}",
                        method="GET",
                        url=f"http://user-service:8001/users/{user_id}",
                    )
                except httpx.RequestError:
                    logger.error(
                        "UpstreamTimeout: user-service did not respond within 2000ms",
                    )
                    raise HTTPException(status_code=504, detail="UpstreamTimeout: user-service did not respond within 2000ms")

        REQ_COUNTER.labels(service=SERVICE, method="GET", status=status_label).inc()
        return data


@app.post("/api/payments")
async def create_payment(body: Dict):
    endpoint = "/api/payments"
    status_label = "200"
    with REQ_DURATION.labels(service=SERVICE, method="POST", endpoint=endpoint, status=status_label).time():
        async with httpx.AsyncClient() as client:
            with UPSTREAM_LATENCY.labels(service=SERVICE, upstream="payment-service").time():
                try:
                    resp = await client.post("http://payment-service:8002/payments", json=body, timeout=5.0)
                    resp.raise_for_status()
                    data = resp.json()
                except httpx.RequestError:
                    logger.error(
                        "UpstreamTimeout: payment-service did not respond within 2000ms",
                    )
                    raise HTTPException(status_code=504, detail="UpstreamTimeout: payment-service did not respond within 2000ms")

        REQ_COUNTER.labels(service=SERVICE, method="POST", status=status_label).inc()
        return data


@app.get("/api/payments/{payment_id}")
async def get_payment(payment_id: str):
    endpoint = "/api/payments/{id}"
    status_label = "200"
    with REQ_DURATION.labels(service=SERVICE, method="GET", endpoint=endpoint, status=status_label).time():
        async with httpx.AsyncClient() as client:
            with UPSTREAM_LATENCY.labels(service=SERVICE, upstream="payment-service").time():
                try:
                    data = await fetch_with_cache(
                        client,
                        cache_key=f"payment:{payment_id}",
                        method="GET",
                        url=f"http://payment-service:8002/payments/{payment_id}",
                    )
                except httpx.RequestError:
                    logger.error(
                        "UpstreamTimeout: payment-service did not respond within 2000ms",
                    )
                    raise HTTPException(status_code=504, detail="UpstreamTimeout: payment-service did not respond within 2000ms")

        REQ_COUNTER.labels(service=SERVICE, method="GET", status=status_label).inc()
        return data


@app.post("/chaos/memory")
async def chaos_memory(percent: int = 90, duration: int = 120):
    """Controlled gauge inflation + capped Python allocation. No stress-ng --vm."""
    global _chaos_active, _memory_chaos
    _chaos_active = True
    _memory_chaos = True
    asyncio.create_task(_controlled_memory_leak(percent, duration))
    return {"status": "injecting", "fault": "memory_leak", "intensity": percent, "duration": duration}


@app.post("/chaos/cpu")
async def chaos_cpu(cores: int = 4, duration: int = 60):
    try:
        subprocess.Popen(
            ["stress-ng", "--cpu", str(cores), "--timeout", str(duration)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        logger.error("stress-ng not installed in container")
    logger.error("GatewayTimeout: API gateway under CPU stress")
    return {"status": "injecting", "fault": "cpu_spike", "cores": cores, "duration": duration}


_latency_chaos = False


async def _synthetic_latency_loop(delay_s: float, duration: int) -> None:
    """Background loop that injects synthetic high-latency observations into
    the Prometheus histogram so the watcher detects the anomaly quickly
    (tc netem alone is too slow to affect the 5-min rate window)."""
    global _latency_chaos
    start = time.time()
    while _latency_chaos and (time.time() - start) < duration:
        # Observe several high-latency requests per tick
        for _ in range(5):
            REQ_DURATION.labels(
                service=SERVICE, method="GET", endpoint="/internal/workload", status="200"
            ).observe(delay_s)
        REQ_COUNTER.labels(service=SERVICE, method="GET", status="504").inc(2)
        await asyncio.sleep(1)
    _latency_chaos = False


@app.post("/chaos/latency")
async def chaos_latency(intensity: int = 80, duration: int = 120):
    """Add artificial latency with tc netem + synthetic metric inflation.
    intensity 0-100 maps to real ms."""
    global _chaos_active, _latency_chaos
    delay_ms = max(500, int(intensity * 10))
    _chaos_active = True
    _latency_chaos = True

    # Real network delay via tc netem
    try:
        subprocess.run(
            ["tc", "qdisc", "add", "dev", "eth0", "root", "netem", "delay", f"{delay_ms}ms"],
            check=True,
        )
    except Exception as e:
        logger.error("Failed to add latency with tc: %s", e)

    # Synthetic metric inflation for faster Prometheus detection
    asyncio.create_task(_synthetic_latency_loop(delay_ms / 1000.0, duration))

    async def _remove():
        global _latency_chaos
        await asyncio.sleep(duration)
        _latency_chaos = False
        subprocess.run(["tc", "qdisc", "del", "dev", "eth0", "root", "netem"], check=False)

    asyncio.create_task(_remove())
    logger.error("TransactionTimeout: payment confirmation timed out")
    return {"status": "injecting", "fault": "network_latency", "intensity": intensity, "delay_ms": delay_ms, "duration": duration}


@app.post("/chaos/stop")
async def chaos_stop():
    global _chaos_active, _memory_chaos, _latency_chaos, _LEAK_BUFFER
    _chaos_active = False
    _memory_chaos = False
    _latency_chaos = False
    _LEAK_BUFFER = []
    DB_CONN_ACTIVE.labels(service=SERVICE).set(0)
    GC_GAUGE.labels(service=SERVICE).set(0)
    MEM_GAUGE.labels(service=SERVICE).set(psutil.virtual_memory().percent)
    try:
        subprocess.run(["pkill", "stress-ng"], check=False)
        subprocess.run(["tc", "qdisc", "del", "dev", "eth0", "root", "netem"], check=False)
    except Exception:
        pass
    return {"status": "stopped"}

