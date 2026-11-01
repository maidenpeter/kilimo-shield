// Copy to include/secrets.h (git-ignored) and fill in for each camera. Never commit real values.
// The device key is shown once when the device is registered:
//   python -m agroshield_platform.devices register --kind camera --uid CAM-A-01 --ward ward-a ...
#pragma once

#define DEVICE_ID "CAM-DEMO-01"
#define DEVICE_KEY "replace-with-the-key-shown-at-registration"

#define SERVER_HOST "devices.agroshield.example"
#define SERVER_PORT 443

// GSM: the SIM's access point name (ask the network; Safaricom data SIMs commonly use "safaricom").
#define GSM_APN "internet"

// Wi-Fi build only.
#define WIFI_SSID "school-network"
#define WIFI_PASSWORD "replace-me"

// PEM of the root certificate that signed the server's TLS certificate. The Wi-Fi build refuses to compile
// without it. Only for a bench test against a local server, define ALLOW_INSECURE_TLS instead (never in the field).
// #define ROOT_CA_PEM "-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----\n"
// #define ALLOW_INSECURE_TLS 1
