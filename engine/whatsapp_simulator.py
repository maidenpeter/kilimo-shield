"""Amber-zone ground-truth verification, simulated end to end (no WhatsApp message is sent).

A ward's Vegetation Condition Index (VCI) decides what happens:
  VCI above 40%      GREEN: keep monitoring
  VCI 35% to 40%     AMBER: hold the payout and ask the ward's lead farmers and agro-vets for geotagged photos,
                     paying KSh 100 airtime per photo. If at least 60% of the valid photos confirm stress, the
                     payout is unlocked; otherwise the hold is released with no payout.
  VCI below 35%      RED: the index alone is clear, so the payout goes ahead without verification

The verifier network, the photos and their tags are synthetic and deterministic for a given ward and VCI.
"""
from __future__ import annotations

import math
import zlib
from dataclasses import dataclass, field
from enum import Enum

import numpy as np
import pandas as pd

from engine.parametric_engine import WARDS

AMBER_LOW, AMBER_HIGH = 35.0, 40.0
CONSENSUS_THRESHOLD = 0.60


def share_text(share: float, threshold: float = CONSENSUS_THRESHOLD) -> str:
    """The agreement as a percentage, half up. A whole number that would land on the other side of the rule gets a
    decimal, so 59.6% never reads as "60%" next to a released hold."""
    from decimal import ROUND_HALF_UP, Decimal
    for places in (0, 1, 2):
        shown = Decimal(repr(round(100 * share, 6))).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
        if (shown >= Decimal(repr(round(100 * threshold, 6)))) == (share >= threshold):
            return f"{shown}%"
    return f"{100 * share:.3f}%"
BOUNTY_KSH = 100
NETWORK_SIZE = 15
SUBMISSIONS = 12
GEOFENCE_KM = 6.0

LEAD_NAMES = ["Wanjiku Kamau", "Kiprop Korir", "Mutua Musyoka", "Odhiambo Otieno", "Makena Mwenda", "Chebet Langat",
              "Nyambura Mbugua", "Wafula Simiyu", "Mwende Kilonzo", "Kerubo Nyaga", "Kipkemboi Rotich",
              "Atieno Owino", "Njoroge Kariuki", "Nekesa Wekesa", "Kawira Muriuki"]
AGROVET_SHOPS = ["Upendo Agrovet", "Mavuno Agrovet", "Shamba Bora Agrovet", "Neema Vet Supplies", "Baraka Agrovet"]
STRESS_TAGS = ["Severe maize wilting and dry pasture", "Maize leaf rolling, pasture browning",
               "Stunted maize, water pans dry", "Pasture grazed bare, no maize stover expected"]
NORMAL_TAGS = ["Crop green, pasture fair", "Light afternoon wilting only", "Normal growth for the stage"]


class State(str, Enum):
    GREEN = "GREEN (MONITORING)"
    AMBER_HOLD = "AMBER (HOLD)"
    VERIFYING = "AMBER (VERIFYING)"
    RED_UNLOCKED = "RED (PAYOUT UNLOCKED)"
    RED_AUTOMATIC = "RED (AUTOMATIC PAYOUT)"
    RELEASED = "GREEN (HOLD RELEASED, NO PAYOUT)"


def zone(vci: float) -> str:
    if vci < AMBER_LOW:
        return "RED"
    if vci <= AMBER_HIGH:
        return "AMBER"
    return "GREEN"


def _rng(*parts) -> np.random.Generator:
    return np.random.default_rng(zlib.crc32(":".join(map(str, parts)).encode()))


def verifier_network(ward_key: str, size: int = NETWORK_SIZE) -> pd.DataFrame:
    """The ward's registered lead farmers and agro-vets (fictional), with masked phone numbers."""
    rng = _rng("network", ward_key)
    names = rng.permutation(LEAD_NAMES)[:size]
    rows = []
    for i, name in enumerate(names):
        agro_vet = i % 4 == 3
        rows.append({
            "verifier": f"{name} ({rng.choice(AGROVET_SHOPS)})" if agro_vet else str(name),
            "role": "Agro-vet" if agro_vet else "Lead farmer",
            "phone_masked": f"2547{rng.integers(10, 99)}***{rng.integers(100, 999)}",
        })
    return pd.DataFrame(rows)


def bounty_message(ward_key: str, vci: float, bounty: int = BOUNTY_KSH) -> str:
    ward = WARDS[ward_key]
    return (
        f"KilimoShield field check, {ward.name}.\n"
        f"Satellite greenness is low (VCI {vci:.1f}%). Please send ONE photo of a maize plot or pasture near you "
        f"today, with location switched on. You get KSh {bounty} airtime for each valid photo.\n"
        f"Tuma picha MOJA ya shamba la mahindi au malisho leo, ukiwa umewasha location. "
        f"Utapata KSh {bounty} za airtime."
    )


def _offset(lat: float, lon: float, km: float, bearing_deg: float) -> tuple[float, float]:
    dlat = km / 111.0 * math.cos(math.radians(bearing_deg))
    dlon = km / (111.0 * max(math.cos(math.radians(lat)), 0.2)) * math.sin(math.radians(bearing_deg))
    return lat + dlat, lon + dlon


def confirm_probability(vci: float) -> float:
    """Lower VCI inside the amber band makes stress more likely to show on the ground."""
    return float(np.clip(0.35 + 0.12 * (AMBER_HIGH - vci), 0.05, 0.97))


def simulate_submissions(ward_key: str, vci: float, n: int = SUBMISSIONS,
                         start: pd.Timestamp = pd.Timestamp("2026-11-20 09:00")) -> pd.DataFrame:
    """Photos sent back by the network: GPS, time, role, the sender's tag, and whether it confirms stress."""
    ward = WARDS[ward_key]
    network = verifier_network(ward_key)
    rng = _rng("subs", ward_key, f"{vci:.1f}")
    p = confirm_probability(vci)
    picks = rng.choice(len(network), size=min(n, len(network)), replace=False)
    rows = []
    minutes = np.sort(rng.integers(4, 240, size=len(picks)))
    for k, (idx, minute) in enumerate(zip(picks, minutes)):
        far = k == len(picks) - 1 and rng.random() < 0.4  # one photo is sometimes taken outside the ward
        km = float(rng.uniform(7.5, 12.0)) if far else float(rng.uniform(0.3, 4.5))
        lat, lon = _offset(ward.lat, ward.lon, km, float(rng.uniform(0, 360)))
        confirms = bool(rng.random() < p)
        rows.append({
            "verifier": network.loc[idx, "verifier"], "role": network.loc[idx, "role"],
            "submitted_at": (start + pd.Timedelta(minutes=int(minute))).strftime("%Y-%m-%d %H:%M"),
            "gps_lat": round(lat, 5), "gps_lon": round(lon, 5), "distance_km": round(km, 2),
            "inside_ward": km <= GEOFENCE_KM,
            "stress_tag": str(rng.choice(STRESS_TAGS if confirms else NORMAL_TAGS)),
            "confirms_stress": confirms,
        })
    subs = pd.DataFrame(rows)
    subs["airtime_ksh"] = np.where(subs["inside_ward"], BOUNTY_KSH, 0)
    return subs


def consensus(submissions: pd.DataFrame) -> float:
    valid = submissions[submissions["inside_ward"]]
    return float(valid["confirms_stress"].mean()) if len(valid) else 0.0


@dataclass
class AmberZoneMachine:
    """State machine for one ward and one VCI reading. Each step appends to an audit log."""
    ward_key: str
    vci: float
    threshold: float = CONSENSUS_THRESHOLD
    state: State = State.GREEN
    log: list[str] = field(default_factory=list)
    submissions: pd.DataFrame | None = None

    def __post_init__(self):
        z = zone(self.vci)
        if z == "RED":
            self.state = State.RED_AUTOMATIC
            self._note(f"VCI {self.vci:.1f}% is below {AMBER_LOW:.0f}%: payout goes ahead on the index alone.")
        elif z == "AMBER":
            self.state = State.AMBER_HOLD
            self._note(f"VCI {self.vci:.1f}% is in the {AMBER_LOW:.0f}% to {AMBER_HIGH:.0f}% amber zone: payout on hold.")
        else:
            self.state = State.GREEN
            self._note(f"VCI {self.vci:.1f}% is above {AMBER_HIGH:.0f}%: no action, keep monitoring.")

    def _note(self, text: str) -> None:
        self.log.append(f"{self.state.value}: {text}")

    @property
    def can_verify(self) -> bool:
        return self.state == State.AMBER_HOLD

    def send_bounties(self, network_size: int = NETWORK_SIZE) -> str:
        if self.state != State.AMBER_HOLD:
            raise ValueError(f"Bounties are only sent from {State.AMBER_HOLD.value}, not {self.state.value}")
        self.state = State.VERIFYING
        self._note(f"Photo request sent to {network_size} lead farmers and agro-vets (KSh {BOUNTY_KSH} airtime each).")
        return bounty_message(self.ward_key, self.vci)

    def receive(self, submissions: pd.DataFrame) -> None:
        if self.state != State.VERIFYING:
            raise ValueError("Photos can only be received while verifying")
        self.submissions = submissions
        outside = int((~submissions["inside_ward"]).sum())
        self._note(f"{len(submissions)} photos received; {outside} taken outside the ward and excluded.")

    def decide(self) -> State:
        if self.state != State.VERIFYING or self.submissions is None:
            raise ValueError("Nothing to decide yet")
        share = consensus(self.submissions)
        if share >= self.threshold:
            self.state = State.RED_UNLOCKED
            self._note(f"{share_text(share, self.threshold)} of valid photos confirm stress (at least "
                       f"{self.threshold:.0%}): payout unlocked.")
        else:
            self.state = State.RELEASED
            self._note(f"Only {share_text(share, self.threshold)} confirm stress (below {self.threshold:.0%}): hold "
                       "released, no payout.")
        return self.state

    def run(self) -> State:
        """Bounties, photos and decision in one go, for an amber reading."""
        if self.can_verify:
            self.send_bounties()
            self.receive(simulate_submissions(self.ward_key, self.vci))
            self.decide()
        return self.state

    @property
    def airtime_cost(self) -> int:
        return 0 if self.submissions is None else int(self.submissions["airtime_ksh"].sum())
