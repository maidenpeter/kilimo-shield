"""Phase 4: the device simulator (tools/devices/simulate.py) runs end to end against the app through the real API:
photos, soil profiles (LoRaWAN and HTTPS), rain tips, battery drain, an outage with store-and-forward catch-up,
a resent message and a faulty reading. Then the stored data and the underwriter pages are checked.
"""
import importlib.util
import re
import sys
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from agroshield_platform.db import transaction
from agroshield_platform.devices import ingest, registry
from agroshield_platform.models import DeviceImage, DeviceMessage, DeviceReading
from agroshield_platform.web.app import create_app

from conftest import REPO
from test_platform import book, login, settings  # noqa: F401

DAYS = 6


def load_simulator():
    spec = importlib.util.spec_from_file_location("simulate", REPO / "tools" / "devices" / "simulate.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["simulate"] = mod                 # dataclasses look their module up while the file runs
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def simulated(tmp_path_factory, cfg):
    import base64
    import secrets

    from agroshield_platform.crypto import hash_password
    from agroshield_platform.models import Insurer, Officer
    from agroshield_platform.settings import Settings
    from test_platform import PASSWORD

    sim = load_simulator()
    db = tmp_path_factory.mktemp("sim") / "sim.db"
    settings = Settings(database_url=f"sqlite:///{db.as_posix()}", encryption_key=secrets.token_bytes(32),
                        lookup_key=secrets.token_bytes(32), session_secret=base64.b64encode(secrets.token_bytes(32)).decode(),
                        config_dir=REPO / "config", dev_keys=False)
    app = create_app(settings, today=date(2026, 12, 15))
    sim.fast_scratch_db(app.state.factory)
    with transaction(app.state.factory) as s:
        ins = Insurer(code="SIM", name="Partner insurer (to be named)", is_demo=True)
        s.add(ins)
        s.flush()
        s.add(Officer(insurer_id=ins.id, username="uw-sim", display_name="UW Sim", role="underwriter",
                      password_hash=hash_password(PASSWORD)))
    devices, ikey = sim.register_fleet(app.state.factory, cfg.wards)
    end = datetime.now(timezone.utc)
    with TestClient(app) as client:
        report = sim.run(client, devices, days=DAYS, end=end, seed=11, integration_key=ikey,
                         set_clock=lambda t: setattr(app.state, "device_clock", (lambda: t) if t else None))
    return app, report


def test_simulator_report(simulated):
    _, report = simulated
    hours = DAYS * 24
    per = report["per_device"]
    assert report["results"]["rejected"] == 1 and per["SOIL-B-01"]["rejected"] == 1            # the 150% reading
    assert report["results"]["duplicate"] == 2                                                  # one resend each
    assert per["SOIL-A-01"] == {"accepted": hours, "duplicate": 1}                              # LoRaWAN, with outage
    assert per["RAIN-A-01"] == {"accepted": hours} and per["RAIN-B-01"] == {"accepted": hours}  # HTTPS and LoRaWAN
    assert report["caught_up"]["SOIL-A-01"] == 48 and report["caught_up"]["CAM-A-01"] == 4      # two days stored
    assert set(report["outage"]["devices"]) == {"CAM-A-01", "SOIL-A-01"}


def test_simulated_data_is_stored_once_with_health(simulated):
    app, _ = simulated
    with transaction(app.state.factory) as s:
        soil = registry.get(s, "SOIL-A-01")
        n = s.scalar(select(func.count()).select_from(DeviceMessage).where(DeviceMessage.device_id == soil.id))
        assert n == DAYS * 24                                                     # caught up, and the resend stored once
        transports = set(s.scalars(select(DeviceMessage.transport).where(DeviceMessage.device_id == soil.id)))
        assert transports == {"lorawan"}
        assert ingest.late_messages(s, soil, datetime.now(timezone.utc) - timedelta(days=DAYS + 1)) == 48
        cam = registry.get(s, "CAM-A-01")
        assert ingest.late_messages(s, cam, datetime.now(timezone.utc) - timedelta(days=DAYS + 1)) >= 4
        gccs = [g for (g,) in s.execute(select(DeviceImage.gcc).where(DeviceImage.device_id == cam.id)
                                         .order_by(DeviceImage.observed_at))]
        assert len(gccs) == DAYS * 2 and gccs[-1] > gccs[0]                       # the crop greens up
        camb = registry.get(s, "CAM-B-01")
        batt = [v for (v,) in s.execute(select(DeviceReading.value).where(DeviceReading.device_id == camb.id,
                                                                           DeviceReading.metric == "battery_v")
                                        .order_by(DeviceReading.observed_at))]
        assert batt[0] > batt[-1] and ingest.health(camb)["battery_low"]           # drained below 3.45 V
        rain_mm = s.scalar(select(func.sum(DeviceReading.value)).where(DeviceReading.metric == "rain_mm",
                                                                       DeviceReading.device_id == registry.get(s, "RAIN-A-01").id))
        tips = s.scalar(select(func.sum(DeviceReading.value)).where(DeviceReading.metric == "rain_tips",
                                                                    DeviceReading.device_id == registry.get(s, "RAIN-A-01").id))
        assert rain_mm == pytest.approx(tips * 0.2)
        for uid in ("CAM-A-01", "CAM-B-01", "SOIL-A-01", "SOIL-B-01", "RAIN-A-01", "RAIN-B-01"):
            assert ingest.health(registry.get(s, uid))["state"] == "ok", uid
    assert app.state.device_clock is None                                         # the simulator handed the clock back


def test_underwriter_sees_the_simulated_fleet(simulated):
    app, _ = simulated
    c = TestClient(app)
    login(c, "uw-sim")
    html = c.get("/uw/devices").text
    for uid in ("CAM-A-01", "CAM-B-01", "SOIL-A-01", "SOIL-B-01", "RAIN-A-01", "RAIN-B-01"):
        assert f'href="/uw/devices/{uid}"' in html
    assert "Reporting" in html and "(fictional)" in html
    soil = c.get("/uw/devices/SOIL-A-01").text
    assert re.search(r'Sent late \(7 days\)</div><div class="v">48<', soil)          # the two days stored on the node
    assert "LoRaWAN" in soil and "Soil water by depth" in soil
    assert "Message refused" in c.get("/uw/devices/SOIL-B-01").text
    cam = c.get("/uw/devices/CAM-A-01").text
    assert cam.count("/uw/devices/CAM-A-01/photos/") == 6 and "photos sent late after an outage" in cam
    assert "Checked against the satellite" in c.get("/uw/devices/RAIN-B-01").text
