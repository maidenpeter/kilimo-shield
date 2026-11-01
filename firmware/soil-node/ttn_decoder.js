// AgroShield soil moisture node (FPort 1) and rain gauge (FPort 2) uplink decoder, version 1 payloads.
// Paste into The Things Stack: Applications > Payload formatters > Uplink > Custom Javascript formatter.
// Byte layout: docs/hardware/SOIL_NODE.md. The server decodes the raw bytes itself
// (src/agroshield_platform/devices/lorawan.py); this formatter is for the network console, and a test checks that
// both give the same readings.

function u16(b, i) { return (b[i] << 8) | b[i + 1]; }
function i16(b, i) { var v = u16(b, i); return v & 0x8000 ? v - 0x10000 : v; }

var SOIL_FLAGS = { 0: "soil sensor at depth 1 not responding", 1: "soil sensor at depth 2 not responding",
                   2: "soil sensor at depth 3 not responding", 3: "temperature sensor fault", 5: "device restarted" };
var RAIN_FLAGS = { 0: "rain gauge switch fault: tip count may be wrong", 3: "temperature sensor fault",
                   5: "device restarted" };

function decodeUplink(input) {
  var b = input.bytes, port = input.fPort;
  if (!b || b.length < 1 || b[0] !== 1) return { errors: ["unknown payload version"] };
  var readings = {}, names, flags, mv, seq, age;
  if (port === 1) {
    if (b.length < 12) return { errors: ["soil payload too short"] };
    var n = b[8];
    if (n < 1 || n > 3 || b.length !== 11 + 3 * n) return { errors: ["soil payload length does not match its number of depths"] };
    for (var k = 0; k < n; k++) {
      var cm = b[9 + 3 * k], raw = u16(b, 10 + 3 * k);
      if (raw !== 0xffff) readings["soil_vwc_" + cm + "cm"] = raw / 10;
    }
    var t = i16(b, 9 + 3 * n);
    if (t !== 0x7fff) readings.soil_temp_c = t / 100;
    names = SOIL_FLAGS;
  } else if (port === 2) {
    if (b.length !== 14) return { errors: ["rain payload must be 14 bytes"] };
    readings.rain_tips = u16(b, 8);
    readings.interval_min = u16(b, 10);
    var at = i16(b, 12);
    if (at !== 0x7fff) readings.air_temp_c = at / 100;
    names = RAIN_FLAGS;
  } else {
    return { errors: ["unknown FPort " + port] };
  }
  seq = u16(b, 1); age = u16(b, 3); flags = b[5]; mv = u16(b, 6);
  if (mv) readings.battery_v = mv / 1000;
  var errors = [];
  for (var bit in names) if (flags & (1 << bit)) errors.push(names[bit]);
  return {
    data: { version: 1, seq: seq, age_min: age, flags: flags, readings: readings, errors: errors,
            battery_low: !!(flags & 16), backlog: !!(flags & 64) },
    warnings: errors
  };
}

if (typeof module !== "undefined") module.exports = { decodeUplink: decodeUplink };
