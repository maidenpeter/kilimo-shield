# Bill of materials

DRAFT. Quantities are per device unless stated. **No prices**: no supplier has been contacted or quoted (the brief
allows no outside contact), so every cost is "to be quoted". Part names are generic types, not chosen suppliers.

## Sentinel field camera

| # | Part | Qty | Notes |
|---|---|---|---|
| 1 | AI-Thinker ESP32-CAM board with OV2640 camera and 4 MB PSRAM | 1 | the firmware's `board = esp32cam` target |
| 2 | microSD card, 8 to 32 GB, FAT32, industrial or high-endurance grade | 1 | the store-and-forward queue |
| 3 | GSM modem module, SIM800L (2G) | 1 | or a TinyGSM-supported 4G Cat-1 module (see SENTINEL_CAMERA.md); not needed for the Wi-Fi build |
| 4 | Data SIM card | 1 | per site; data plan to be chosen |
| 5 | GSM antenna with bulkhead connector | 1 | mounted outside the box |
| 6 | Logic-level P-channel MOSFET and small N-channel driver, resistors | 1 set | switches the modem's power from GPIO 4 |
| 7 | Low-ESR capacitor, 470 to 1000 uF, next to the modem | 1 | for the modem's transmit bursts |
| 8 | 18650 lithium-ion cells (protected) and holder | 2 | in parallel |
| 9 | Solar charge controller for one lithium cell, with protection | 1 | |
| 10 | Solar panel, 6 V, a few watts | 1 | size after a bench measurement of daily energy use |
| 11 | 3.3 V buck-boost regulator | 1 | feeds the ESP32-CAM from the cell |
| 12 | IP65 enclosure with a clear window, membrane vent, desiccant, cable glands | 1 set | see ENCLOSURE.md |
| 13 | Pole or wall bracket, lockable, security screws | 1 set | |
| 14 | USB-to-serial adapter (or ESP32-CAM programmer board) | 1 per technician | for flashing |

## Soil moisture node

| # | Part | Qty | Notes |
|---|---|---|---|
| 1 | LoRaWAN node board (microcontroller with a LoRa radio in the band plan used in Kenya) | 1 | confirm the band plan before buying |
| 2 | Capacitive soil moisture sensors | 2 or 3 | bench-check each (see SOIL_NODE.md calibration notes) |
| 3 | Waterproof digital temperature probe | 1 | soil temperature |
| 4 | Battery (lithium primary cells, or a lithium-ion cell with a small solar panel) | 1 | |
| 5 | IP67 enclosure, cable glands, LoRa antenna | 1 set | |
| 6 | PVC pipe and cap for the cables, post | 1 set | |

## Rain gauge

| # | Part | Qty | Notes |
|---|---|---|---|
| 1 | Tipping-bucket rain gauge with reed switch | 1 | calibrate mm per tip (RAIN_GAUGE.md) |
| 2 | LoRaWAN node board, or shared with a nearby soil node | 1 | counts tips on an interrupt with debounce |
| 3 | Battery, IP67 enclosure, antenna | 1 set | as the soil node |
| 4 | Post, level, mesh for the funnel | 1 set | |

## Shared per site

| # | Part | Qty | Notes |
|---|---|---|---|
| 1 | LoRaWAN gateway with internet or cellular backhaul | 1 per area | at the host school or SACCO office; one gateway can serve several sites in range |
| 2 | Caretaker agreement and visit checklist | 1 per site | not a part; see KNOWN_ISSUES.md |

## Tools for installation and calibration

Kitchen scale and drying oven access (gravimetric soil samples), measuring cylinder (rain gauge calibration),
spirit level, multimeter.
