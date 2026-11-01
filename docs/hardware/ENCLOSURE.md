# Enclosures and mounting

DRAFT design notes. Nothing here has been built or field-tested yet; verify each point on a bench unit and one pilot
site before ordering in quantity.

## Where devices go

Every device is hosted at a **school or a SACCO office** with a paid caretaker (see
[KNOWN_ISSUES.md](KNOWN_ISSUES.md)): inside a fenced compound, in sight of people during the day, with a named
institution responsible, not on a farmer's plot. The camera watches a demonstration plot planted in the ward's usual
maize at that site; the soil node sits in the same plot; the rain gauge stands in the open part of the compound.
Device labels name the site, never a person.

## Sentinel camera

- **Box**: IP65 or better polycarbonate or ABS box, light-coloured to stay cool in the sun.
- **Lens window**: a clear glass or polycarbonate window sealed into the lid, with a short hood above it against rain
  and glare. Clean it on every caretaker visit; a dirty window lowers greenness readings.
- **Moisture**: a breathable vent (membrane vent) and a desiccant pack, replaced each season; cable glands for every
  cable; drip loops below the box.
- **Aim**: on a 2 to 3 m pole or a building wall, looking down at about 45 degrees across the plot, facing away from
  the sun at the photo hours (in Kenya, close to the equator, the midday sun is high, so mainly keep the sky out of
  the frame). Fix the aim: greenness compares the same view over the season. Take a reference photo at installation.
- **Privacy**: aim at the crop, not at paths, classrooms or homes; the photos are shown only to signed-in underwriters.
- **Power**: lithium cell pack and a small solar panel on the pole, tilted slightly so rain and dust run off;
  charge controller and the modem's power MOSFET inside the box.
- **Antenna**: the modem's antenna outside the box (bulkhead connector) or a glass-fibre whip; metal boxes block signal.
- **Tamper**: security screws, a lockable bracket, the solar cable inside the pole.

## Soil moisture node

- **Electronics** in a small IP67 box on a short post 0.5 to 1 m above ground, beside the sensor pit, with the LoRaWAN
  antenna vertical and clear of metal.
- **Sensors** installed as in [SOIL_NODE.md](SOIL_NODE.md) (horizontal, undisturbed soil, no air gaps); cables in a
  capped PVC pipe with strain relief, buried below plough depth between pit and post.
- **Mark the pit** so nobody digs or ploughs through it; keep cattle out (the plot is inside the host's fence).

## Rain gauge

- **Siting**: open ground, away from buildings and trees (a common rule is a distance of at least twice their
  height), rim level and horizontal, on a firm post at a fixed height recorded at installation.
- **Funnel**: a mesh against leaves and insects, cleaned on every visit (a blocked funnel silently records no rain;
  the CHIRPS check flags a gauge that reads zero through a wet dekad).
- **Node**: the same small IP67 box as the soil node, or shared with it when the two are close.
- **Bird spikes** on the rim only if birds perch there; they must not shade the funnel.
