"""MQTT ingestion: a bridge that subscribes to device topics on an MQTT broker and stores what arrives.

    publish   agroshield/v1/devices/<device id>/up    {"key": "<device key>", "messages": [ ... ]}
    answer    agroshield/v1/devices/<device id>/ack   {"results": [{"msg_id": ..., "status": ...}, ...]}

The messages are the same as on HTTPS (see ingest.py), so the same checks and the same idempotency apply. A device
clears a stored message from its queue once the answer says accepted, duplicate, conflict or rejected.

Run the broker with TLS and per-device credentials, and an access list that lets each device publish only to its
own "up" topic and read only its own "ack" topic. The device key in the payload is checked here as well, so a
broker misconfiguration cannot let one device write as another.

    python -m agroshield_platform.devices mqtt-bridge --host broker.example --port 8883 --ca ca.pem

paho-mqtt is optional: pip install "agroshield[hardware]".
"""
from __future__ import annotations

import json
import logging
import re

from sqlalchemy.orm import sessionmaker

from ..db import transaction
from . import ingest, registry

log = logging.getLogger("agroshield.devices.mqtt")
SUBSCRIBE = "agroshield/v1/devices/+/up"
TOPIC_RE = re.compile(r"agroshield/v1/devices/([A-Z0-9][A-Z0-9-]{2,31})/up")
MAX_PAYLOAD = 256 * 1024


def ack_topic(uid: str) -> str:
    return f"agroshield/v1/devices/{uid}/ack"


def handle(factory: sessionmaker, topic: str, payload: bytes, now=None) -> tuple[str, bytes] | None:
    """Store one MQTT publish. Returns the (topic, payload) answer to publish, or None for a topic we do not serve."""
    m = TOPIC_RE.fullmatch(topic or "")
    if not m:
        return None
    uid = m.group(1)

    def answer(obj) -> tuple[str, bytes]:
        return ack_topic(uid), json.dumps(obj).encode()

    if len(payload) > MAX_PAYLOAD:
        return answer({"error": "message too large"})
    try:
        body = json.loads(payload)
    except (ValueError, UnicodeDecodeError):
        return answer({"error": "not JSON"})
    key = body.pop("key", None) if isinstance(body, dict) else None
    with transaction(factory) as s:
        device = registry.authenticate(s, uid, key, now)
        if device is None:
            return answer({"error": "unknown device or wrong key"})
        try:
            results = ingest.ingest_batch(s, device, body, "mqtt", now)
        except ingest.BadRequest as e:
            return answer({"error": str(e)})
    return answer({"results": [r.as_dict() for r in results]})


def run_bridge(factory: sessionmaker, host: str, port: int = 8883, username: str | None = None,
               password: str | None = None, ca_certs: str | None = None, tls: bool = True) -> None:
    """Connect to the broker and serve until stopped (blocking)."""
    try:
        import paho.mqtt.client as paho
    except ImportError as e:                       # optional dependency
        raise SystemExit('The MQTT bridge needs paho-mqtt: pip install "agroshield[hardware]"') from e
    client = paho.Client(paho.CallbackAPIVersion.VERSION2, client_id="agroshield-ingest", clean_session=False)
    if username:
        client.username_pw_set(username, password)
    if tls:
        client.tls_set(ca_certs=ca_certs)

    def on_connect(c, userdata, flags, reason_code, properties):
        log.info("connected to %s:%s (%s); subscribing to %s", host, port, reason_code, SUBSCRIBE)
        c.subscribe(SUBSCRIBE, qos=1)

    def on_message(c, userdata, msg):
        try:
            out = handle(factory, msg.topic, msg.payload)
        except Exception:                          # never let one bad message stop the bridge
            log.exception("could not store an MQTT message on %s", msg.topic)
            return
        if out:
            c.publish(out[0], out[1], qos=1)

    client.on_connect, client.on_message = on_connect, on_message
    client.connect(host, port)
    client.loop_forever()
