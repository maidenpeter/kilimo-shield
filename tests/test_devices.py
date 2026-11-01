"""Phase 4, milestone 9: hardware layer. Device registry, ingestion (HTTPS, MQTT, LoRaWAN), validation and idempotency,
photos and greenness, device health, rain gauge checks against CHIRPS, the TAHMO stub, the underwriter pages, and
the rule that device data never reaches pricing, triggers or payouts. All devices and sites are fictional.
"""
import io
import json
import re
import shutil
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from agroshield_platform.db import transaction
from agroshield_platform.devices import greenness, ingest, lorawan, mqtt, rain, registry
from agroshield_platform.models import Device, DeviceImage, DeviceIssue, DeviceMessage, DeviceReading
from agroshield_platform.web.app import create_app

from conftest import REPO
from test_platform import PASSWORD, assert_no_pii, book, login, settings  # noqa: F401
from test_uw import world  # noqa: F401

UTC = timezone.utc


def now():
    return datetime.now(UTC).replace(microsecond=0)


def jpeg(rgb=(60, 140, 50), size=(64, 48), fmt="JPEG") -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, rgb).save(buf, fmt)
    return buf.getvalue()


@pytest.fixture
def app(settings, book):  # noqa: F811
    return create_app(settings, book, today=date(2026, 12, 15))


@pytest.fixture
def fleet(app, cfg):
    """One device of each kind in ward-a, a LoRaWAN soil node, and a network server integration."""
    keys = {}
    with transaction(app.state.factory) as s:
        for uid, kind, extra in (("CAM-T-01", "camera", {}), ("SOIL-T-01", "soil", {}),
                                 ("RAIN-T-01", "rain", {"settings": {"mm_per_tip": 0.5}}),
                                 ("SOIL-T-02", "soil", {"dev_eui": "70B3D57ED0000001"}),
                                 ("RAIN-T-02", "rain", {"dev_eui": "70b3d57ed0000002"})):
            _, keys[uid] = registry.register(s, uid=uid, kind=kind, ward_id="ward-a", site_type="school",
                                             site_label="Primary school (fictional)", actor="test", wards=cfg.wards, **extra)
        _, keys["integration"] = registry.add_integration(s, "test network server", "test")
    return keys


def post_readings(c, uid, key, *msgs):
    return c.post("/api/devices/v1/readings", json={"messages": list(msgs)}, headers={"X-Device-Id": uid, "X-Device-Key": key})


def msg(msg_id, at=None, **readings):
    return {"msg_id": msg_id, "observed_at": (at or now() - timedelta(minutes=5)).isoformat(), "readings": readings}


# ------------------------------------------------------------------ registry and authentication
def test_register_keeps_only_a_hash_and_validates(app, cfg, fleet):
    with transaction(app.state.factory) as s:
        d = registry.get(s, "cam-t-01")
        assert d.secret_hash == registry.hash_secret(fleet["CAM-T-01"]) and fleet["CAM-T-01"] not in d.secret_hash
        assert d.settings["photos_per_day"] == 2 and registry.get(s, "RAIN-T-01").settings["mm_per_tip"] == 0.5
        assert registry.get(s, "RAIN-T-02").dev_eui == "70B3D57ED0000002"           # normalised
        bad = [dict(uid="x"), dict(kind="drone"), dict(ward_id="ward-z"), dict(site_type="home"),
               dict(site_label="Farm of 0722 718 281"), dict(dev_eui="12"), dict(lat=12.0), dict(uid="CAM-T-01")]
        for over in bad:
            kw = dict(uid="NEW-01", kind="soil", ward_id="ward-a", site_type="school", site_label="School (fictional)")
            with pytest.raises(registry.DeviceError):
                registry.register(s, **{**kw, **over}, actor="t", wards=cfg.wards)
    db = (app.state.factory.kw["bind"].url.database)
    raw = open(db, "rb").read()
    assert all(k.encode() not in raw for k in fleet.values())                      # no key anywhere in the database


def test_authentication_and_wrong_keys(app, fleet):
    t = now()
    with transaction(app.state.factory) as s:
        assert registry.authenticate(s, "CAM-T-01", fleet["CAM-T-01"]).uid == "CAM-T-01"
        assert registry.authenticate(s, "CAM-T-01", fleet["SOIL-T-01"], t) is None
        assert registry.authenticate(s, "CAM-T-01", "nope", t + timedelta(minutes=1)) is None   # noted once only
        assert registry.authenticate(s, "NOPE-01", fleet["CAM-T-01"]) is None
        assert registry.authenticate(s, "CAM-T-01", None) is None
        d = registry.get(s, "CAM-T-01")
        assert s.scalar(select(func.count()).select_from(DeviceIssue).where(DeviceIssue.kind == "auth_failed")) == 1
        new = registry.rotate_secret(s, d, "t")
        assert registry.authenticate(s, "CAM-T-01", fleet["CAM-T-01"]) is None and registry.authenticate(s, "CAM-T-01", new)
        registry.retire(s, d, "t")
        assert registry.authenticate(s, "CAM-T-01", new) is None
    c = TestClient(app)
    r = post_readings(c, "SOIL-T-01", "wrong", msg("m1", soil_vwc_10cm=20))
    assert r.status_code == 401 and "wrong key" in r.json()["error"]
    assert c.post("/api/devices/v1/readings", json={"messages": [msg("m1", soil_vwc_10cm=20)]}).status_code == 401


# ------------------------------------------------------------------ ingestion: validation and idempotency
def test_readings_are_validated(app, fleet):
    c = TestClient(app)
    key = fleet["SOIL-T-01"]
    t = now()
    cases = {
        "range": (msg("a", soil_vwc_10cm=140.0), "outside"),
        "unknown": (msg("b", rain_tips=3), "not a reading a soil device sends"),
        "depth": (msg("c", soil_vwc_900cm=20.0), "depth"),
        "future": (msg("d", at=t + timedelta(hours=1), soil_vwc_10cm=20.0), "future"),
        "old": (msg("e", at=t - timedelta(days=91), soil_vwc_10cm=20.0), "90 days"),
        "unset clock": ({"msg_id": "f", "observed_at": 946684800, "readings": {"soil_vwc_10cm": 20.0}}, "before 2024"),
        "naive": ({"msg_id": "g", "observed_at": "2026-10-30T10:00:00", "readings": {"soil_vwc_10cm": 20.0}}, "time zone"),
        "text": (msg("h", soil_vwc_10cm="wet"), "not a number"),
        "empty": (msg("i"), "no readings"),
        "id": (msg("bad id with spaces", soil_vwc_10cm=20.0), "msg_id"),
        "battery": (msg("j", battery_v=40.0), "outside"),
    }
    r = post_readings(c, "SOIL-T-01", key, *[m for m, _ in cases.values()])
    assert r.status_code == 200
    for (name, (_, why)), res in zip(cases.items(), r.json()["results"]):
        assert res["status"] == "rejected" and any(why in x for x in res["reasons"]), (name, res)
    r = post_readings(c, "RAIN-T-01", fleet["RAIN-T-01"], msg("k", rain_tips=3))
    assert "interval_min" in r.json()["results"][0]["reasons"][0]
    assert post_readings(c, "SOIL-T-01", key).status_code == 400                      # no messages
    assert c.post("/api/devices/v1/readings", content=b"{", headers={"X-Device-Id": "SOIL-T-01", "X-Device-Key": key}).status_code == 400
    with transaction(app.state.factory) as s:
        assert s.scalar(select(func.count()).select_from(DeviceMessage)) == 0
        d = registry.get(s, "SOIL-T-01")
        assert d.last_error.startswith("Message refused") and d.last_seen_at is None
        assert s.scalar(select(func.count()).select_from(DeviceIssue).where(DeviceIssue.kind == "rejected")) == 12


def test_readings_are_idempotent_and_rain_tips_become_mm(app, fleet):
    c = TestClient(app)
    t = now() - timedelta(hours=1)
    first = msg("RAIN-T-01-1", at=t, rain_tips=7, interval_min=60, battery_v=3.61)
    r = post_readings(c, "RAIN-T-01", fleet["RAIN-T-01"], first, first)
    assert [x["status"] for x in r.json()["results"]] == ["accepted", "duplicate"]
    reordered = {"readings": first["readings"], "observed_at": first["observed_at"], "msg_id": first["msg_id"]}
    assert post_readings(c, "RAIN-T-01", fleet["RAIN-T-01"], reordered).json()["results"][0]["status"] == "duplicate"
    changed = {**first, "readings": {**first["readings"], "rain_tips": 9}}
    assert post_readings(c, "RAIN-T-01", fleet["RAIN-T-01"], changed).json()["results"][0]["status"] == "conflict"
    # the same message id from another device is a different message
    assert post_readings(c, "RAIN-T-02", fleet["RAIN-T-02"], first).json()["results"][0]["status"] == "accepted"
    with transaction(app.state.factory) as s:
        d = registry.get(s, "RAIN-T-01")
        vals = dict(s.execute(select(DeviceReading.metric, DeviceReading.value).where(DeviceReading.device_id == d.id)).all())
        assert vals == {"rain_tips": 7, "interval_min": 60, "battery_v": 3.61, "rain_mm": 3.5}    # 7 tips x 0.5 mm
        assert s.scalar(select(func.count()).select_from(DeviceMessage).where(DeviceMessage.device_id == d.id)) == 1
    assert ingest.tips_to_mm(12, 0.2) == 2.4


def test_device_errors_are_recorded_scrubbed(app, fleet):
    c = TestClient(app)
    m = {**msg("e1", battery_v=3.9), "errors": ["SD card missing or unreadable", "call 0722718281"], "firmware": "cam-0.1.0"}
    assert post_readings(c, "CAM-T-01", fleet["CAM-T-01"], m).json()["results"][0]["status"] == "accepted"
    with transaction(app.state.factory) as s:
        d = registry.get(s, "CAM-T-01")
        details = [i.detail for i in s.scalars(select(DeviceIssue).where(DeviceIssue.device_id == d.id))]
        assert "SD card missing or unreadable" in details and not any("0722718281" in x for x in details)
        assert d.firmware == "cam-0.1.0" and d.last_battery_v == 3.9


# ------------------------------------------------------------------ health
def test_health_states_and_late_batches(app, fleet):
    c = TestClient(app)
    t = now()
    post_readings(c, "SOIL-T-01", fleet["SOIL-T-01"], msg("new", at=t - timedelta(minutes=10), soil_vwc_10cm=25.0, battery_v=3.5))
    post_readings(c, "SOIL-T-01", fleet["SOIL-T-01"], msg("old", at=t - timedelta(days=2), soil_vwc_10cm=30.0, battery_v=3.9))
    with transaction(app.state.factory) as s:
        d = registry.get(s, "SOIL-T-01")
        assert d.last_battery_v == 3.5                     # a stored, older reading never overwrites the newest
        assert ingest.health(d, t)["state"] == "ok" and ingest.health(d, t)["seen_text"] == "just now"
        assert ingest.health(d, t + timedelta(hours=3))["label"] == "Late"
        assert ingest.health(d, t + timedelta(hours=30))["state"] == "offline"
        assert ingest.late_messages(s, d, t - timedelta(days=7)) == 1
        cam = registry.get(s, "CAM-T-01")
        assert ingest.health(cam, t)["state"] == "never"
        cam.last_battery_v = 3.3
        assert ingest.health(cam, t)["battery_low"]
        d.status = "retired"
        assert ingest.health(d, t)["label"] == "Retired"


# ------------------------------------------------------------------ photos and greenness
def test_greenness_index():
    green = greenness.analyse(jpeg((60, 140, 50)))
    grey = greenness.analyse(jpeg((128, 128, 128)))
    soil = greenness.analyse(jpeg((122, 92, 64)))
    assert green["gcc"] > 0.45 > grey["gcc"] > soil["gcc"] and abs(grey["gcc"] - 1 / 3) < 0.01
    assert green["green_fraction"] == 1.0 and soil["green_fraction"] == 0.0 and green["exg"] > 0.3
    half = np.zeros((40, 40, 3))
    half[:, :20] = (60, 140, 50)
    half[:, 20:] = (122, 92, 64)
    assert greenness.indices(half)["green_fraction"] == pytest.approx(0.5)
    with pytest.raises(greenness.PhotoError, match="too dark"):
        greenness.analyse(jpeg((5, 5, 5)))
    with pytest.raises(greenness.PhotoError, match="not a JPEG"):
        greenness.analyse(jpeg(fmt="PNG"))
    with pytest.raises(greenness.PhotoError, match="could not be read"):
        greenness.analyse(b"\xff\xd8\xff garbage")


def test_photo_upload(app, fleet, settings):  # noqa: F811
    c = TestClient(app)
    t = int((now() - timedelta(hours=2)).timestamp())
    h = {"X-Device-Id": "CAM-T-01", "X-Device-Key": fleet["CAM-T-01"], "X-Msg-Id": "CAM-T-01-1-1",
         "X-Observed-At": str(t), "X-Battery-mV": "3950", "Content-Type": "image/jpeg"}
    photo = jpeg()
    r = c.post("/api/devices/v1/images", content=photo, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "accepted" and r.json()["greenness_gcc"] > 0.45
    assert c.post("/api/devices/v1/images", content=photo, headers=h).json()["status"] == "duplicate"
    assert c.post("/api/devices/v1/images", content=jpeg((128, 128, 128)), headers=h).status_code == 409
    assert c.post("/api/devices/v1/images", content=jpeg(fmt="PNG"), headers={**h, "X-Msg-Id": "x2"}).status_code == 422
    assert c.post("/api/devices/v1/images", content=photo, headers={**h, "X-Msg-Id": "x3", "X-Observed-At": "0"}).status_code == 422
    assert c.post("/api/devices/v1/images", content=b"\0" * (3 * 1024 * 1024 + 1), headers={**h, "X-Msg-Id": "x4"}).status_code == 413
    soil = {**h, "X-Device-Id": "SOIL-T-01", "X-Device-Key": fleet["SOIL-T-01"], "X-Msg-Id": "x5"}
    assert c.post("/api/devices/v1/images", content=photo, headers=soil).status_code == 422
    assert c.post("/api/devices/v1/images", content=photo, headers={**h, "X-Device-Key": "wrong"}).status_code == 401
    with transaction(app.state.factory) as s:
        [img] = s.scalars(select(DeviceImage)).all()
        assert img.width == 64 and img.gcc > 0.45 and img.observed_at.replace(tzinfo=UTC).timestamp() == t
        stored = settings_store(settings) / img.path
        assert stored.read_bytes() == photo and "CAM-T-01" in img.path
        d = registry.get(s, "CAM-T-01")
        assert d.last_battery_v == 3.95
        metrics = set(s.scalars(select(DeviceReading.metric).where(DeviceReading.device_id == d.id)))
        assert metrics == {"battery_v", "greenness_gcc", "greenness_exg", "green_fraction"}


def settings_store(settings):  # noqa: F811
    from agroshield_platform.web.devices import image_store
    return image_store(settings)


# ------------------------------------------------------------------ LoRaWAN
SOIL_BYTES = lorawan.encode_soil(42, 0, 3612, [(10, 23.4), (30, 27.0), (60, None)], 19.25, flags=0b0100100)
RAIN_BYTES = lorawan.encode_rain(7, 30, 3580, 12, 60, -1.5, flags=0b0010001)


def test_payload_layout_and_round_trip():
    assert len(SOIL_BYTES) == 20 and len(RAIN_BYTES) == 14
    assert SOIL_BYTES.hex() == "01002a000024" "0e1c" "03" "0a00ea" "1e010e" "3cffff" "0785"
    d = lorawan.decode(1, SOIL_BYTES)
    assert d["seq"] == 42 and d["readings"] == {"soil_vwc_10cm": 23.4, "soil_vwc_30cm": 27.0, "soil_temp_c": 19.25,
                                                "battery_v": 3.612}
    assert d["errors"] == ["soil sensor at depth 3 not responding", "device restarted"] and not d["battery_low"]
    r = lorawan.decode(2, RAIN_BYTES)
    assert r["age_min"] == 30 and r["readings"] == {"rain_tips": 12, "interval_min": 60, "air_temp_c": -1.5, "battery_v": 3.58}
    assert r["battery_low"] and r["errors"] == ["rain gauge switch fault: tip count may be wrong"]
    for port, data in ((1, SOIL_BYTES[:-1]), (2, RAIN_BYTES + b"\0"), (3, RAIN_BYTES), (1, b"\x02" + SOIL_BYTES[1:]), (1, b"")):
        with pytest.raises(lorawan.PayloadError):
            lorawan.decode(port, data)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_ttn_javascript_decoder_matches_python():
    js = (REPO / "firmware" / "soil-node" / "ttn_decoder.js").as_posix()
    cases = [(1, SOIL_BYTES), (2, RAIN_BYTES), (1, lorawan.encode_soil(1, 5, 0, [(15, 0.0)], None))]
    script = (f"const d = require({json.dumps(js)});"
              f"const cases = {json.dumps([[p, list(b)] for p, b in cases])};"
              "console.log(JSON.stringify(cases.map(([p, b]) => d.decodeUplink({fPort: p, bytes: b}))));")
    out = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
    for (port, data), js_out in zip(cases, out):
        py = lorawan.decode(port, data)
        assert js_out["data"] == py, port
    bad = subprocess.run(["node", "-e", f"console.log(JSON.stringify(require({json.dumps(js)}).decodeUplink({{fPort: 9, bytes: [1]}})))"],
                         capture_output=True, text=True, check=True).stdout
    assert json.loads(bad)["errors"] == ["unknown FPort 9"]


def ttn(eui, port, data, received, rssi=-97):
    import base64
    return {"end_device_ids": {"device_id": "x", "dev_eui": eui}, "received_at": received,
            "uplink_message": {"f_port": port, "f_cnt": 3, "frm_payload": base64.b64encode(data).decode(),
                               "rx_metadata": [{"rssi": rssi - 10}, {"rssi": rssi}]}}


def test_lorawan_webhook(app, fleet):
    c = TestClient(app)
    hk = {"X-Integration-Key": fleet["integration"]}
    t = now() - timedelta(minutes=1)
    stamp = t.strftime("%Y-%m-%dT%H:%M:%S.123456789Z")                          # nanoseconds, as TTN sends
    body = ttn("70B3D57ED0000001", 1, SOIL_BYTES, stamp)
    assert c.post("/api/devices/v1/lorawan/uplink", json=body).status_code == 401
    assert c.post("/api/devices/v1/lorawan/uplink", json=body, headers={"X-Integration-Key": fleet["SOIL-T-01"]}).status_code == 401
    r = c.post("/api/devices/v1/lorawan/uplink", json=body, headers=hk)
    assert r.status_code == 200 and r.json()["status"] == "accepted" and r.json()["msg_id"] == f"lw1-42-{t:%Y%m%d}"
    assert c.post("/api/devices/v1/lorawan/uplink", json=body, headers=hk).json()["status"] == "duplicate"
    # the node resends the same stored reading 3 minutes later (age 3, other gateway): still the same reading
    later = (t + timedelta(minutes=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    resend = SOIL_BYTES[:3] + (3).to_bytes(2, "big") + SOIL_BYTES[5:]
    assert c.post("/api/devices/v1/lorawan/uplink", json=ttn("70B3D57ED0000001", 1, resend, later, -80), headers=hk).json()["status"] == "duplicate"
    # a rain payload stored for 30 minutes, through ChirpStack
    import base64
    cs = {"deviceInfo": {"devEui": "70b3d57ed0000002"}, "fPort": 2, "data": base64.b64encode(RAIN_BYTES).decode(),
          "time": t.isoformat(), "rxInfo": [{"rssi": -110}]}
    assert c.post("/api/devices/v1/lorawan/uplink", json=cs, headers=hk).json()["status"] == "accepted"
    assert c.post("/api/devices/v1/lorawan/uplink", json=ttn("70B3D57ED0000001", 2, RAIN_BYTES, stamp), headers=hk).status_code == 422
    assert c.post("/api/devices/v1/lorawan/uplink", json=ttn("0000000000000000", 1, SOIL_BYTES, stamp), headers=hk).status_code == 404
    assert c.post("/api/devices/v1/lorawan/uplink", json={"hello": 1}, headers=hk).status_code == 400
    with transaction(app.state.factory) as s:
        soil = registry.get(s, "SOIL-T-02")
        assert soil.last_signal_dbm == -97 and soil.last_battery_v == 3.612
        assert s.scalar(select(func.count()).select_from(DeviceMessage).where(DeviceMessage.device_id == soil.id)) == 1
        rg = registry.get(s, "RAIN-T-02")
        m = s.scalar(select(DeviceMessage).where(DeviceMessage.device_id == rg.id))
        assert m.transport == "lorawan" and abs(m.observed_at.replace(tzinfo=UTC) - (t - timedelta(minutes=30))) < timedelta(seconds=1)
        vals = dict(s.execute(select(DeviceReading.metric, DeviceReading.value).where(DeviceReading.device_id == rg.id)).all())
        assert vals["rain_mm"] == 2.4 and vals["signal_dbm"] == -110                 # 12 tips x 0.2 mm (default)
        errs = [i.detail for i in s.scalars(select(DeviceIssue).where(DeviceIssue.device_id == soil.id))]
        assert "device restarted" in errs and any("FPort 2 is for a rain device" in e for e in errs)


# ------------------------------------------------------------------ MQTT
def test_mqtt_bridge_handler(app, fleet):
    f = app.state.factory
    good = json.dumps({"key": fleet["SOIL-T-01"], "messages": [msg("mq-1", soil_vwc_10cm=21.5)]}).encode()
    topic, ack = mqtt.handle(f, "agroshield/v1/devices/SOIL-T-01/up", good)
    assert topic == "agroshield/v1/devices/SOIL-T-01/ack"
    assert json.loads(ack) == {"results": [{"msg_id": "mq-1", "status": "accepted"}]}
    assert json.loads(mqtt.handle(f, "agroshield/v1/devices/SOIL-T-01/up", good)[1])["results"][0]["status"] == "duplicate"
    # one device cannot write as another, even if the broker lets it publish there
    other = json.dumps({"key": fleet["CAM-T-01"], "messages": [msg("mq-2", soil_vwc_10cm=21.5)]}).encode()
    assert "wrong key" in json.loads(mqtt.handle(f, "agroshield/v1/devices/SOIL-T-01/up", other)[1])["error"]
    assert json.loads(mqtt.handle(f, "agroshield/v1/devices/SOIL-T-01/up", b"{nope")[1]) == {"error": "not JSON"}
    assert mqtt.handle(f, "other/topic", good) is None
    assert fleet["SOIL-T-01"] not in mqtt.handle(f, "agroshield/v1/devices/SOIL-T-01/up", good)[1].decode()
    with transaction(f) as s:
        assert s.scalar(select(DeviceMessage.transport).where(DeviceMessage.msg_id == "mq-1")) == "mqtt"


def test_mqtt_bridge_wires_paho(app, monkeypatch):
    paho = pytest.importorskip("paho.mqtt.client")
    calls = {}

    class FakeClient:
        def __init__(self, *a, **k): calls["init"] = k
        def username_pw_set(self, u, p): calls["user"] = u
        def tls_set(self, ca_certs=None): calls["tls"] = ca_certs
        def connect(self, host, port): calls["connect"] = (host, port)
        def subscribe(self, topic, qos=0): calls["sub"] = topic
        def publish(self, topic, payload, qos=0): calls["pub"] = topic
        def loop_forever(self):
            self.on_connect(self, None, None, 0, None)
            m = type("M", (), {"topic": "agroshield/v1/devices/X-1/up", "payload": b"{}"})
            self.on_message(self, None, m)
    monkeypatch.setattr(paho, "Client", FakeClient)
    mqtt.run_bridge(app.state.factory, "broker.test", 8883, "bridge", "pw", "ca.pem")
    assert calls["connect"] == ("broker.test", 8883) and calls["sub"] == mqtt.SUBSCRIBE and calls["tls"] == "ca.pem"
    assert calls["pub"] == "agroshield/v1/devices/X-1/ack"


# ------------------------------------------------------------------ rain gauge checks
def test_rain_checks_against_chirps():
    chirps = rain.ChirpsFiles(REPO / "data" / "raw" / "chirps")
    sat = chirps.series("ward-a")
    assert chirps.last_day("ward-a") == date(2025, 12, 31) and not chirps.available("ward-z")
    dk = list(rain.dekads(date(2020, 1, 1), date(2020, 12, 31)))
    assert len(dk) == 36 and dk[2] == (date(2020, 1, 21), date(2020, 1, 31)) and dk[5][1] == date(2020, 2, 29)

    def total(a, b):
        return sum(sat[a + timedelta(days=i)] for i in range((b - a).days + 1))
    wet = next((a, b) for a, b in dk if total(a, b) > 60)
    dry = next((a, b) for a, b in dk if total(a, b) < 5)
    start, end = date(2020, 1, 1), date(2020, 12, 31)
    days = {start + timedelta(days=i) for i in range((end - start).days + 1)}
    gauge = {d: sat[d] for d in days}                                     # a gauge that agrees with the satellite
    assert rain.check_against_chirps("ward-a", gauge, days, chirps, start, end) == []
    for i in range((wet[1] - wet[0]).days + 1):
        gauge[wet[0] + timedelta(days=i)] = 0.0                             # blocked funnel in a wet dekad
    gauge[dry[0]] = 80.0                                                    # a storm the satellite missed
    flags = {f.kind: f for f in rain.check_against_chirps("ward-a", gauge, days, chirps, start, end)}
    assert flags["possible_blocked_funnel"].start == wet[0] and "funnel" in flags["possible_blocked_funnel"].text
    assert flags["wetter_than_satellite"].start == dry[0] and flags["wetter_than_satellite"].gauge_mm >= 80
    # a dekad the gauge did not fully report is not judged
    assert not [f for f in rain.check_against_chirps("ward-a", gauge, days - {wet[0]}, chirps, start, end)
                if f.kind == "possible_blocked_funnel"]
    # after the CHIRPS file ends only the single-day check applies
    month_max = chirps.wettest_day_by_month("ward-a")[3]
    late = {date(2026, 3, 10): month_max * 2 + 1, date(2026, 3, 11): 5.0}
    [f] = rain.check_against_chirps("ward-a", late, set(late), chirps, date(2026, 3, 1), date(2026, 3, 31))
    assert f.kind == "unusually_heavy_day" and f.start == date(2026, 3, 10)
    assert rain.check_against_chirps("ward-z", late, set(late), chirps, date(2026, 3, 1), date(2026, 3, 31)) == []


def test_tahmo_adapter_is_a_labelled_blocked_stub():
    with pytest.raises(rain.TahmoBlocked, match="credentials"):
        rain.TahmoAdapter().daily("TA00000", date(2026, 1, 1), date(2026, 1, 31))
    with pytest.raises(rain.TahmoBlocked):
        rain.TahmoAdapter("user", "secret").daily("TA00000", date(2026, 1, 1), date(2026, 1, 31))
    assert "BLOCKED" in rain.TahmoAdapter.__doc__


# ------------------------------------------------------------------ never a trigger source
TRIGGER_AND_PAYOUT = ("monitoring.py", "services.py", "mpesa.py", "settlement.py", "underwriting.py", "sms.py", "ussd.py")


def test_pricing_triggers_and_payouts_never_import_the_device_module():
    files = list((REPO / "src" / "agroshield_pricing").rglob("*.py")) + \
        [REPO / "src" / "agroshield_platform" / n for n in TRIGGER_AND_PAYOUT]
    pat = re.compile(r"^\s*(from|import)\s+\S*devices|import_module\(\s*['\"]\S*devices", re.M)
    for f in files:
        assert not pat.search(f.read_text(encoding="utf-8")), f.name
    code = ("import sys, agroshield_pricing, agroshield_pricing.engine, agroshield_pricing.monitor, "
            "agroshield_pricing.quote, agroshield_pricing.api, agroshield_platform.monitoring, "
            "agroshield_platform.services, agroshield_platform.mpesa, agroshield_platform.settlement, "
            "agroshield_platform.underwriting\n"
            "print(sorted(m for m in sys.modules if 'devices' in m))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         env={**__import__("os").environ, "PYTHONPATH": str(REPO / "src")}).stdout
    assert out.strip() == "[]"


# ------------------------------------------------------------------ underwriter pages
def _seed_devices(app, cfg):
    keys = {}
    with transaction(app.state.factory) as s:
        for uid, kind, ward in (("CAM-A-01", "camera", "ward-a"), ("RAIN-A-01", "rain", "ward-a"),
                                ("SOIL-B-01", "soil", "ward-b")):
            _, keys[uid] = registry.register(s, uid=uid, kind=kind, ward_id=ward, site_type="school",
                                             site_label=f"Primary school {ward} (fictional)", actor="t", wards=cfg.wards)
    c = TestClient(app)
    t = now() - timedelta(hours=1)
    post_readings(c, "RAIN-A-01", keys["RAIN-A-01"], msg("r1", at=t, rain_tips=50, interval_min=60, battery_v=3.2))
    post_readings(c, "SOIL-B-01", keys["SOIL-B-01"], msg("s1", at=t, soil_vwc_10cm=21.0, soil_vwc_30cm=26.0, soil_temp_c=18.5))
    r = c.post("/api/devices/v1/images", content=jpeg(), headers={
        "X-Device-Id": "CAM-A-01", "X-Device-Key": keys["CAM-A-01"], "X-Msg-Id": "p1", "X-Observed-At": t.isoformat()})
    assert r.status_code == 200
    return keys


def test_underwriter_device_pages(world, cfg):  # noqa: F811
    _seed_devices(world, cfg)
    c = TestClient(world)
    login(c, "uw-UW1")
    page = c.get("/uw/devices")
    assert page.status_code == 200
    html = page.text
    assert "never for payouts" in html and "satellite rainfall index" in html
    assert 'href="/uw/devices" aria-current="page">Devices' in html
    assert "your cover" in html and html.index("Rongai West") < html.index("Molo Highlands")   # covered ward first
    assert "CAM-A-01" in html and "SOIL-B-01" in html and "10.0 mm today" in html           # 50 tips x 0.2 mm
    assert "21.0%" in html and "Greenness" in html and '<span class="chip warn">low</span>' in html   # RAIN-A-01: 3.2 V
    assert "\N{EM DASH}" not in html                                                     # no em dashes
    assert_no_pii(html)
    for uid, text in (("RAIN-A-01", "Checked against the satellite"), ("SOIL-B-01", "Soil water by depth"),
                      ("CAM-A-01", "Latest photos")):
        r = c.get(f"/uw/devices/{uid}")
        assert r.status_code == 200 and text in r.text and "never for payouts" in r.text, uid
    cam = c.get("/uw/devices/CAM-A-01").text
    src = re.search(r'src="(/uw/devices/CAM-A-01/photos/\d+\.jpg)"', cam).group(1)
    assert c.get(src).headers["content-type"] == "image/jpeg"
    assert c.get("/uw/devices/NOPE-01").status_code == 404
    assert c.get("/uw/devices/SOIL-B-01/photos/1.jpg").status_code == 404                  # photo of another device
    # SACCO staff and the public cannot see device pages or photos
    off = TestClient(world)
    login(off, "man-UW1")
    assert off.get("/uw/devices", follow_redirects=False).status_code == 403
    assert TestClient(world).get(src, follow_redirects=False).headers["location"] == "/login"


def test_underwriter_page_without_cover_or_devices(app, cfg):
    from agroshield_platform.crypto import hash_password
    from agroshield_platform.models import Insurer, Officer
    with transaction(app.state.factory) as s:
        ins = Insurer(code="NEW", name="Partner insurer (to be named)", is_demo=True)
        s.add(ins)
        s.flush()
        s.add(Officer(insurer_id=ins.id, username="uw-new", display_name="UW New", role="underwriter",
                      password_hash=hash_password(PASSWORD)))
    c = TestClient(app)
    login(c, "uw-new")
    html = c.get("/uw/devices").text
    assert "No devices yet" in html and "your cover" not in html


# ------------------------------------------------------------------ command line
def test_device_cli(tmp_path, monkeypatch, capsys):
    import base64
    import secrets
    from agroshield_platform.devices.__main__ import main
    for k, n in (("NATIONAL_ID_ENCRYPTION_KEY", 32), ("LOOKUP_HMAC_KEY", 32), ("SESSION_SECRET", 32)):
        monkeypatch.setenv(k, base64.b64encode(secrets.token_bytes(n)).decode())
    monkeypatch.setenv("CALLBACK_TOKEN", "t" * 24)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'cli.db').as_posix()}")
    assert main(["register", "--uid", "rain-c-01", "--kind", "rain", "--ward", "ward-b", "--site-type", "sacco_office",
                 "--site-label", "SACCO office (fictional)", "--mm-per-tip", "0.25", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["uid"] == "RAIN-C-01" and len(out["key"]) >= 40
    assert main(["register", "--uid", "RAIN-C-01", "--kind", "rain", "--ward", "ward-b", "--site-type", "school",
                 "--site-label", "x"]) == 2
    assert main(["list"]) == 0 and "Never reported" in capsys.readouterr().out
    assert main(["rotate-key", "--uid", "RAIN-C-01"]) == 0 and "New key" in capsys.readouterr().out
    assert main(["add-integration", "--name", "ttn"]) == 0 and "X-Integration-Key" in capsys.readouterr().out
    assert main(["retire", "--uid", "RAIN-C-01"]) == 0
    assert main(["retire", "--uid", "NOPE-1"]) == 2
