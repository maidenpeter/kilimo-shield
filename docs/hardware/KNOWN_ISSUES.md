# Known issues and how the design answers them

The rule above all of these: **device data never decides a payout.** Payouts follow the satellite rainfall index in
the policy. Devices help check that index and show where it misses what happened on the ground (basis risk), so the
product and its pricing can be improved. No single device, and above all no device a farmer controls, may decide or
change a payout. This is enforced in code: the pricing package and the trigger and payout code do not import the
device package (`tests/test_devices.py`), and no device table is read by them.

## Theft and vandalism

- **Host at schools and SACCO offices**, inside a fenced compound, with a **paid caretaker** under a written
  agreement (a small monthly fee, a visit checklist: clean the camera window and the rain funnel, check the box is
  shut and the panel clean, report damage). Not on farmers' plots.
- Nothing worth stealing in sight: the electronics are in a plain box; the solar panel is the most visible part, so
  it is small, bolted with security screws and its cable runs inside the pole.
- **Detection**: a device that stops reporting shows as Late, then Not heard from, on the underwriter's Devices page;
  a camera photo that is suddenly dark or of a different view is visible on its page. Operations visits the site.
- **No data value to tampering**: since devices cannot change payouts, there is no reason for anyone to interfere
  with a device to win a payout.

## Power and signal gaps

- **Store and forward** everywhere: the camera queues photos on its SD card (up to 400, oldest dropped first and
  reported), soil nodes and gauges keep readings and resend them with their age; the server accepts readings up to 90
  days old and stores each once (message ids), so a long outage loses nothing and a resend never double counts.
  The simulator plays a two-day outage and the catch-up (`tests/test_device_simulator.py`).
- **Health on the page**: last heard from, battery (with a low warning), signal, and how many messages arrived late.
- **Clock**: devices set their clock from the network on every wake; the server refuses times in the future, before
  2024 (an unset clock) or more than 90 days old, so a bad clock cannot slip readings into the wrong season.
- **Batteries**: size the solar panel after a bench measurement of daily energy use; cloudy long-rains weeks are the
  worst case. The heartbeat reports battery every wake.
- **2G**: the SIM800L is a 2G modem. Check 2G coverage at each site and the network's plans to switch 2G off; a 4G
  Cat-1 modem supported by TinyGSM avoids that risk.
- **TLS on the SIM800L**: the module's own TLS stack is old and does not check the server's certificate, so a
  well-placed attacker could read a device key. Mitigations: prefer a 4G module whose TLS checks certificates (the
  Wi-Fi build already checks against `ROOT_CA_PEM`), rotate keys (`rotate-key`) if a device is lost, and remember
  that a stolen key can at most add readings for that one device, never change a payout.

## Sensor drift and bad readings

- **Validation on arrival**: physical ranges for every reading; a message with any bad value is refused whole and
  listed under Problems on the device's page (the simulator sends a 150% soil reading to prove it).
- **Cross-check rain gauges against CHIRPS** (built, `devices/rain.py`): 10-day totals compared with the ward's CHIRPS
  data in the repo, flagging much wetter, much drier and possible blocked funnel; single days above twice the
  wettest CHIRPS day on record for the month are flagged too. DRAFT thresholds.
- **Cross-check against TAHMO stations**: Blocked. Needs TAHMO API credentials under a data-sharing agreement and the
  nearest station codes (see RAIN_GAUGE.md). The adapter interface is in place as a labelled stub.
- **Soil sensors**: recalibrate against a gravimetric sample each season; watch that shallow sensors respond to rain
  before deep ones; temperature is logged with every reading for a later correction.
- **Cameras**: greenness is relative; a dirty window, a moved camera or a changed white balance shifts it. Compare a
  camera only with itself, keep a reference photo of the view, and clean the window on every visit.
- **Outliers are for people**: a flag asks someone to look. It never edits a reading, an index or a payout.

## Privacy

- Devices hold no personal data. Site labels name the institution type, never a person; a label with an ID or phone
  number is refused at registration.
- Camera photos can show people who walk past: aim at the crop, show photos only to signed-in underwriters, and agree
  a retention period before the pilot (not set yet).
- Device keys are stored only as hashes and never travel in a URL.
