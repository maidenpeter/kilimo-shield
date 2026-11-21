"""Adversarial payments the generator never makes: every member, with the hardest references and payer names.

The rule under test: a wrong credit is worse than a review, so the matcher may send these to review but must never
credit the wrong member.
"""
import pytest

from data import seed_generator as sg
from engine import recon_engine as rec

DATA = sg.generate_all()
INDEX = rec.MemberIndex(DATA.members)
UNKNOWN_PHONE = "254700000999"


def _outcomes(cases):
    wrong, right = [], 0
    for ref, payer, truth in cases:
        got, method, _ = rec.match_row(ref, UNKNOWN_PHONE, payer, INDEX)
        if got == truth:
            right += 1
        elif got is not None:
            wrong.append((ref, payer, truth, got, method))
    return right, wrong


def _last_two(name: str) -> str:
    return " ".join(name.upper().split()[-2:])


@pytest.mark.parametrize("variant", ["truncated_full_name", "truncated_last_two", "own_name_junk_ref",
                                     "last_two_junk_ref", "spouse_junk_ref"])
def test_no_wrong_credits(variant):
    cases = []
    for m in DATA.members.itertuples():
        digits = m.member_id.split("-")[1]
        if variant == "truncated_full_name":
            cases.append((f"MBR-{digits[:3]}", m.full_name.upper(), m.member_id))
        elif variant == "truncated_last_two":
            cases.append((f"MBR-{digits[:3]}", _last_two(m.full_name), m.member_id))
        elif variant == "own_name_junk_ref":
            cases.append(("SHAMBA", m.full_name.upper(), m.member_id))
        elif variant == "last_two_junk_ref":
            cases.append(("SHAMBA", _last_two(m.full_name), m.member_id))
        elif variant == "spouse_junk_ref" and m.spouse_name:
            cases.append(("SHAMBA", m.spouse_name.upper(), m.member_id))
    right, wrong = _outcomes(cases)
    assert wrong == [], wrong[:5]
    if variant == "last_two_junk_ref":
        assert right == 0  # two names alone never credit anyone: they all go to review
    else:
        assert right > 0
