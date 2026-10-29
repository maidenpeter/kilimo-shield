"""CSV writing that cannot run as a spreadsheet formula.

A text cell that starts with = + - @ or a tab or carriage return is read by Excel and LibreOffice as a formula, so a
member name such as =HYPERLINK(...) in an export could run when the file is opened. Such cells get a leading
apostrophe. Numbers, including negative amounts written as numbers or numeric strings, are left exactly as they are.
"""
from __future__ import annotations

import csv
import re

_NUMERIC = re.compile(r"^[-+]?\d+(\.\d+)?([eE][-+]?\d+)?$")
_RISKY = ("=", "+", "-", "@", "\t", "\r")


def cell(v):
    if isinstance(v, str) and v.startswith(_RISKY) and not _NUMERIC.match(v):
        return "'" + v
    return v


class SafeWriter:
    def __init__(self, f, **kw):
        self._w = csv.writer(f, **kw)

    def writerow(self, row):
        return self._w.writerow([cell(v) for v in row])

    def writerows(self, rows):
        for r in rows:
            self.writerow(r)


def writer(f, **kw) -> SafeWriter:
    return SafeWriter(f, **kw)
