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

SERVICE = "payment-service"

app = FastAPI(title="Sentinel Payment Service", version="0.1.0")

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

PAYMENTS: Dict[str, Dict] = {}

_chaos_active = False
_memory_chaos = False
_cpu_chaos = False
_LEAK_BUFFER: List[bytes] = []

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


async def metrics_loop() -> None:
    DB_CONN_MAX.labels(service=SERVICE).set(50)
    while True:
        cpu = psutil.cpu_percent(interval=None)
        CPU_GAUGE.labels(service=SERVICE).set(cpu)
        if not _memory_chaos:
            mem = psutil.virtual_memory().percent
            MEM_GAUGE.labels(service=SERVICE).set(mem)
        await asyncio.sleep(5)


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


async def simulate_payment_workload() -> None:
    """Background workload using Redis for rate-limiting and caching."""
    await asyncio.sleep(5)
    while True:
        start = time.time()
        status = "200"
        try:
            r = get_redis()
            op = random.choice(["process", "balance", "fraud"])
            if r is None:
                raise redis.ConnectionError("Redis unavailable")
            if op == "process":
                tx_id = f"tx:{random.randint(1, 10000)}"
                r.setex(tx_id, 120, json.dumps({"amount": random.randint(10, 500), "status": "confirmed"}))
            elif op == "balance":
                r.get(f"balance:user:{random.randint(1, 100)}")
            else:
                key = f"fraud:check:{random.randint(1,50)}"
                r.incr(key)
                r.expire(key, 60)
        except (redis.ConnectionError, redis.TimeoutError):
            status = "500"
            logger.error("PaymentProcessingError: Redis unavailable for payment operation")
        except Exception as e:
            status = "500"
            logger.error("PaymentWorkloadError: %s", e)
        finally:
            duration = time.time() - start
            REQ_DURATION.labels(service=SERVICE, method="POST", endpoint="/internal/workload", status=status).observe(duration)
            REQ_COUNTER.labels(service=SERVICE, method="POST", status=status).inc()
        await asyncio.sleep(random.uniform(0.05, 0.15))


@app.on_event("startup")
async def startup_event() -> None:
    asyncio.create_task(metrics_loop())
    asyncio.create_task(simulate_payment_workload())


@app.get("/health")
async def health():
    return {"status": "healthy", "service": SERVICE}


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics():
    data = generate_latest(_registry)
    return PlainTextResponse(data, media_type=CONTENT_TYPE_LATEST)


@app.post("/payments")
async def create_payment(body: Dict):
    import uuid

    payment_id = body.get("id") or "1"
    amount = body.get("amount", 0)
    currency = body.get("currency", "USD")

    # Under chaos, sometimes fail with payment-specific errors
    failing = _memory_chaos and random.random() < 0.4
    cpu_overloaded = _cpu_chaos and random.random() < 0.3

    status_label = "200"
    endpoint = "/payments"

    with REQ_DURATION.labels(service=SERVICE, method="POST", endpoint=endpoint, status=status_label).time():
        if failing:
            status_label = "500"
            REQ_COUNTER.labels(service=SERVICE, method="POST", status="500").inc()
            logger.error(
                "PaymentProcessingError: unable to allocate transaction buffer",
            )
            raise HTTPException(status_code=500, detail="PaymentProcessingError: unable to allocate transaction buffer")

        if cpu_overloaded:
            status_label = "504"
            REQ_COUNTER.labels(service=SERVICE, method="POST", status="504").inc()
            logger.error(
                "PaymentGatewayTimeout: Stripe API response delayed",
            )
            raise HTTPException(status_code=504, detail="PaymentGatewayTimeout: Stripe API response delayed")

        payment = {
            "id": payment_id or str(uuid.uuid4()),
            "amount": amount,
            "currency": currency,
            "status": "confirmed",
        }
        PAYMENTS[payment["id"]] = payment

        try:
            r = get_redis()
            if r:
                r.set(f"payment:{payment['id']}:status", payment["status"], ex=300)
        except Exception:
            logger.error("PaymentProcessingError: failed to write status to Redis cache")

        REQ_COUNTER.labels(service=SERVICE, method="POST", status="200").inc()
        return payment


@app.get("/payments/{payment_id}")
async def get_payment(payment_id: str):
    endpoint = "/payments/{id}"
    status_label = "200"

    with REQ_DURATION.labels(service=SERVICE, method="GET", endpoint=endpoint, status=status_label).time():
        try:
            r = get_redis()
            if r:
                cached = r.get(f"payment:{payment_id}:status")
                if cached:
                    status = cached.decode("utf-8")
                    REQ_COUNTER.labels(service=SERVICE, method="GET", status="200").inc()
                    return {"id": payment_id, "status": status, "source": "cache"}
        except Exception:
            logger.error("PaymentProcessingError: failed to read from Redis cache")

        payment = PAYMENTS.get(payment_id)
        if not payment:
            raise HTTPException(status_code=404, detail="Payment not found")

        REQ_COUNTER.labels(service=SERVICE, method="GET", status="200").inc()
        return payment


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
    global _chaos_active, _cpu_chaos
    _chaos_active = True
    _cpu_chaos = True
    try:
        subprocess.Popen(
            ["stress-ng", "--cpu", str(cores), "--timeout", str(duration)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        logger.error("stress-ng not installed in container")
    return {"status": "injecting", "fault": "cpu_spike", "cores": cores, "duration": duration}


@app.post("/chaos/latency")
async def chaos_latency(intensity: int = 80, duration: int = 120):
    """Add artificial latency with tc netem.  intensity 0-100 maps to real ms."""
    delay_ms = max(500, int(intensity * 10))
    try:
        subprocess.run(
            ["tc", "qdisc", "add", "dev", "eth0", "root", "netem", "delay", f"{delay_ms}ms"],
            check=True,
        )
    except Exception as e:
        logger.error("Failed to add latency with tc: %s", e)

    async def _remove():
        await asyncio.sleep(duration)
        subprocess.run(["tc", "qdisc", "del", "dev", "eth0", "root", "netem"], check=False)

    asyncio.create_task(_remove())
    return {"status": "injecting", "fault": "network_latency", "intensity": intensity, "delay_ms": delay_ms, "duration": duration}


@app.post("/chaos/stop")
async def chaos_stop():
    global _chaos_active, _memory_chaos, _cpu_chaos, _LEAK_BUFFER
    _chaos_active = False
    _memory_chaos = False
    _cpu_chaos = False
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

