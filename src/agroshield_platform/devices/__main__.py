"""Device administration (platform staff, on the server): python -m agroshield_platform.devices <command>

    register         add a device; prints its key once (only a hash is stored)
    rotate-key       give a device a new key (the old one stops working)
    retire           stop accepting messages from a device (its data is kept)
    add-integration  add a LoRaWAN network server webhook; prints its key once
    list             devices and their health
    mqtt-bridge      store messages that devices publish to an MQTT broker
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from sqlalchemy import select

from agroshield_pricing.config import load_config

from ..db import init_db, make_engine, transaction
from ..models import Device
from ..settings import load_settings
from . import ingest, mqtt, registry


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m agroshield_platform.devices", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("register")
    r.add_argument("--uid", required=True, help="as printed on the device label, e.g. CAM-A-01")
    r.add_argument("--kind", required=True, choices=sorted(registry.KINDS))
    r.add_argument("--ward", required=True)
    r.add_argument("--site-type", required=True, choices=sorted(registry.SITE_TYPES))
    r.add_argument("--site-label", required=True, help='the host site, never a person, e.g. "Primary school"')
    r.add_argument("--name")
    r.add_argument("--lat", type=float)
    r.add_argument("--lon", type=float)
    r.add_argument("--dev-eui", help="LoRaWAN devices: 16 hex digits")
    r.add_argument("--mm-per-tip", type=float, help="rain gauges: calibrated rain per bucket tip (default 0.2)")
    r.add_argument("--depths", help="soil nodes: sensor depths in cm, e.g. 10,30,60")
    r.add_argument("--json", action="store_true", help="print the id and key as JSON (for the simulator)")
    for name in ("rotate-key", "retire"):
        x = sub.add_parser(name)
        x.add_argument("--uid", required=True)
    i = sub.add_parser("add-integration")
    i.add_argument("--name", required=True)
    sub.add_parser("list")
    m = sub.add_parser("mqtt-bridge")
    m.add_argument("--host", required=True)
    m.add_argument("--port", type=int, default=8883)
    m.add_argument("--username")
    m.add_argument("--ca", help="CA certificate file for the broker's TLS")
    m.add_argument("--no-tls", action="store_true", help="plain MQTT, for a local test broker only")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO)
    settings = load_settings()
    factory = init_db(make_engine(settings.database_url))
    if args.cmd == "mqtt-bridge":
        mqtt.run_bridge(factory, args.host, args.port, args.username, os.environ.get("MQTT_PASSWORD"), args.ca,
                        tls=not args.no_tls)
        return 0
    try:
        with transaction(factory) as s:
            if args.cmd == "register":
                cfg = load_config(settings.config_dir)
                extra = {}
                if args.mm_per_tip is not None:
                    extra["mm_per_tip"] = args.mm_per_tip
                if args.depths:
                    extra["depths_cm"] = [int(x) for x in args.depths.split(",")]
                d, key = registry.register(s, uid=args.uid, kind=args.kind, ward_id=args.ward, site_type=args.site_type,
                                           site_label=args.site_label, name=args.name, lat=args.lat, lon=args.lon,
                                           dev_eui=args.dev_eui, settings=extra, actor="cli", wards=cfg.wards)
                if args.json:
                    print(json.dumps({"uid": d.uid, "kind": d.kind, "ward": d.ward_id, "key": key,
                                      **({"dev_eui": d.dev_eui} if d.dev_eui else {})}))
                else:
                    print(f"Registered {d.uid} ({registry.KINDS[d.kind]}, {d.ward_id}).")
                    print(f"Device key (shown once; put it in the device's secrets): {key}")
            elif args.cmd in ("rotate-key", "retire"):
                d = registry.get(s, args.uid)
                if d is None:
                    raise registry.DeviceError(f"No device {args.uid}.")
                if args.cmd == "retire":
                    registry.retire(s, d, "cli")
                    print(f"{d.uid} retired: its messages are refused from now on.")
                else:
                    print(f"New key for {d.uid} (shown once): {registry.rotate_secret(s, d, 'cli')}")
            elif args.cmd == "add-integration":
                _, key = registry.add_integration(s, args.name, "cli")
                print(f"Integration {args.name} added. Webhook header X-Integration-Key (shown once): {key}")
            elif args.cmd == "list":
                for d in s.scalars(select(Device).order_by(Device.ward_id, Device.uid)):
                    h = ingest.health(d)
                    print(f"{d.uid:14} {d.kind:7} {d.ward_id:10} {h['label']:15} battery "
                          f"{'-' if d.last_battery_v is None else f'{d.last_battery_v:.2f} V'}")
    except registry.DeviceError as e:
        print(e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
