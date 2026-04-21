"""E2E test: Client adapter + real Kafka happy path.

This test starts a real uvicorn server, sends real HTTP requests,
and verifies messages are written to and readable from a real Kafka broker.

Prerequisites:
    - Kafka broker reachable at kafka01.ndev.jereh.cn:9092
    - Port 19999 available on localhost

Run:
    pytest tests/e2e/test_adapter_kafka_e2e.py -v -s

Skip if Kafka is unreachable:
    pytest tests/e2e/test_adapter_kafka_e2e.py -v -s -m kafka
"""
import asyncio
import json
import os
import uuid
from typing import Optional

import httpx
import pytest

KAFKA_BROKERS = os.environ.get(
    "KAFKA_BROKERS", "kafka01.ndev.jereh.cn:9092"
)
KAFKA_TOPIC = f"test_e2e_{uuid.uuid4().hex[:8]}"  # unique topic per run to avoid collisions
TEST_PORT = 19999
BASE_URL = f"http://127.0.0.1:{TEST_PORT}"


def _kafka_available() -> bool:
    """Quick check if Kafka broker is reachable."""
    import socket
    host, port_str = KAFKA_BROKERS.split(",")[0].split(":")
    try:
        with socket.create_connection((host, int(port_str)), timeout=3):
            return True
    except (OSError, ValueError):
        return False


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not _kafka_available(), reason="Kafka broker not reachable"),
]


@pytest.fixture(scope="module")
def event_loop():
    """Create a module-scoped event loop for the server."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
async def server(event_loop):
    """Start a real uvicorn server with Kafka enabled."""
    import uvicorn
    from app.api.main import create_app
    from app.config import AppConfig

    # Create app with test config
    app = create_app()
    app._app_config = AppConfig(
        db_path=f"test_e2e_{uuid.uuid4().hex[:8]}.db",
        kafka_brokers=KAFKA_BROKERS.split(","),
        kafka_topic=KAFKA_TOPIC,
        host="127.0.0.1",
        port=TEST_PORT,
    )

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=TEST_PORT,
        log_level="warning",
    )
    server = uvicorn.Server(config)

    # Start server in background
    task = asyncio.create_task(server.serve())

    # Wait for server to be ready
    for _ in range(50):
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{BASE_URL}/health")
                if r.status_code == 200:
                    break
        except httpx.ConnectError:
            pass
        await asyncio.sleep(0.1)

    yield server

    # Shutdown
    server.should_exit = True
    await task

    # Clean up test database
    db_path = app._app_config.db_path
    import pathlib
    pathlib.Path(db_path).unlink(missing_ok=True)


@pytest.fixture(scope="module")
async def kafka_consumer():
    """Create a Kafka consumer for reading test messages."""
    from aiokafka import AIOKafkaConsumer

    consumer = AIOKafkaConsumer(
        KAFKA_TOPIC,
        bootstrap_servers=KAFKA_BROKERS,
        group_id=f"test-e2e-{uuid.uuid4().hex[:8]}",
        auto_offset_reset="latest",
        value_deserializer=lambda m: json.loads(m.decode("utf-8")),
        consumer_timeout_ms=15000,
    )
    await consumer.start()

    # Wait a moment for consumer to join group
    await asyncio.sleep(2)

    yield consumer

    await consumer.stop()


async def consume_until(consumer, predicate, timeout=15.0) -> Optional[dict]:
    """Consume messages until predicate matches or timeout."""
    import time
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            msg = await asyncio.wait_for(consumer.__anext__(), timeout=2.0)
            if predicate(msg.value):
                return msg.value
        except (asyncio.TimeoutError, StopAsyncIteration):
            continue
    return None


@pytest.mark.asyncio(scope="module")
async def test_inquiry_happy_path_with_kafka(server, kafka_consumer):
    """Full E2E: create inquiry → Kafka awaiting → decide new_round → Kafka awaiting → decide award → Kafka completed.

    4 HTTP calls, 3 Kafka messages.
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:

        # ── Step 1: Create task via adapter ──
        response = await client.post(
            "/financial/audit",
            data={
                "session_id": "e2e_test_session",
                "workflow_type": "inquiry",
            },
        )
        assert response.status_code == 200, f"Create failed: {response.text}"
        thread_id = response.json()["thread_id"]
        assert thread_id

        # ── Step 2: Consume Kafka → awaiting_human_review ──
        msg1 = await consume_until(
            kafka_consumer,
            lambda v: v.get("header", {}).get("thread_id") == thread_id
                      and v.get("header", {}).get("status") == "awaiting_human_review",
        )
        assert msg1 is not None, "Did not receive awaiting_human_review from Kafka"
        assert msg1["header"]["event_id"]
        assert msg1["callback_context"]["node_id"] == "check_quotes"
        event_id_1 = msg1["header"]["event_id"]

        # ── Step 3: Decide new_round (eliminate suppliers) ──
        response = await client.post(
            "/financial/audit/decide",
            json={
                "event_id": event_id_1,
                "thread_id": thread_id,
                "decision": "add in",
                # Extra fields passed as user_input
                "new_deadline": "2026-06-01T18:00:00",
                "supplier_codes": ["SUP_JINGLIN", "SUP_DEXIN"],
            },
        )
        assert response.status_code == 200, f"Decide new_round failed: {response.text}"
        assert response.json()["success"] is True

        # ── Step 4: Consume Kafka → awaiting_human_review (round 2) ──
        msg2 = await consume_until(
            kafka_consumer,
            lambda v: v.get("header", {}).get("thread_id") == thread_id
                      and v.get("header", {}).get("status") == "awaiting_human_review"
                      and v.get("header", {}).get("event_id") != event_id_1,
        )
        assert msg2 is not None, "Did not receive second awaiting_human_review from Kafka"
        event_id_2 = msg2["header"]["event_id"]
        assert event_id_2 != event_id_1

        # ── Step 5: Decide award ──
        response = await client.post(
            "/financial/audit/decide",
            json={
                "event_id": event_id_2,
                "thread_id": thread_id,
                "decision": "reject",  # maps to second transition = "award"
                "winners": [
                    {"material_code": "C050066547", "supplier_code": "SUP_JINGLIN", "awarded_price": 1050.0},
                ],
            },
        )
        assert response.status_code == 200, f"Decide award failed: {response.text}"
        result = response.json()
        assert result["success"] is True
        assert result["next_status"] == "completed"

        # ── Step 6: Consume Kafka → completed ──
        msg3 = await consume_until(
            kafka_consumer,
            lambda v: v.get("header", {}).get("thread_id") == thread_id
                      and v.get("header", {}).get("status") == "completed",
        )
        assert msg3 is not None, "Did not receive completed from Kafka"

        # ── Step 7: Verify final status via adapter ──
        response = await client.get(f"/financial/audit/status?thread_id={thread_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "completed"
