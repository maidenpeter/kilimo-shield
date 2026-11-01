"""Hardware layer (milestone 9): field devices that help check the satellite rainfall index and reduce basis risk.

Device data is NEVER a trigger source. Triggers and payouts follow the satellite rainfall index in the policy
(agroshield_pricing and monitoring.py); neither imports this package, and a test keeps it that way. No single
device, least of all one a farmer controls, may decide a payout.

    registry   register devices and LoRaWAN network servers; keys are shown once and kept only as a SHA-256 hash
    ingest     validate and store readings and photos, idempotent on the device's message id; device health
    greenness  greenness index of a sentinel camera photo (green chromatic coordinate, excess green)
    lorawan    soil moisture node and rain gauge binary payloads, and the network server webhook
    rain       tipping bucket tips to mm, checks against CHIRPS, the TAHMO adapter (blocked: needs credentials)
    mqtt       MQTT bridge (paho-mqtt, optional)

Command line: python -m agroshield_platform.devices --help
"""
