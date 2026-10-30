#!/usr/bin/env python
"""Block a statutorily exempt home address from a published dataset, using a hashed roster.

A records office holds a list of people whose home address the law withholds
from the public. A GIS dataset is exported, uploaded and published, and nobody
compares it with that list, because the list cannot travel: it is itself the
sensitive file. This tool compares the two without moving the list. The
roster holds only keyed hashes (HMAC-SHA256) of normalised street lines. The
dataset's address columns are normalised the same way, hashed with the same
key, and looked up. A row that matches is left out of the clean copy.

The obvious tools already cover the parts around this. ArcGIS and any
geocoder will standardise an address, and a SQL join or a pandas merge will
match two lists. Both need the plain list in the same place as the data. A
plain SHA-256 of an address is not an answer either, because every address in
a county is public and can be hashed in an afternoon. The key is what makes
the roster safe to hold, and the key is kept apart from it.

    python exemptguard.py --self-test
    python exemptguard.py --make-key secret.bin --apply
    python exemptguard.py --build-roster plain.csv --address-field HOME_ADDR \\
        --roster roster.txt --key-file secret.bin --apply
    python exemptguard.py points.csv --roster roster.txt --key-file secret.bin \\
        --address-field SITE_ADDR
    python exemptguard.py points.csv --roster roster.txt --key-file secret.bin \\
        --address-field ADDNUM,STNAME,STTYPE --out clean.csv --report held.csv \\
        --apply

Nothing is written without --apply. The tool never prints an address, a hash
or the key. It prints counts and the dataset line numbers of the rows it holds.

Exit codes: 0 no row matched, and no more rows than --max-unchecked allows had
no street line to check (the default allows none; a dataset with no rows at all
also exits 0), 1 at least one row matched (publish the --out file, not the
input), 2 a file could not be read or written or is empty, 3 refused (the
roster is damaged or the key does not open it), 4 too little was checked or too
little was built (more rows than --max-unchecked allows had no street line), 64
usage error, 70 an unexpected crash, which is never a finding.
"""

from __future__ import print_function

import argparse
import ast
import contextlib
import csv
import hashlib
import hmac
import importlib.util
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
import unicodedata

# =============================================================================
# CONFIGURATION. Deliberately not flags. Change here, not at the call site.
# =============================================================================

# Bump this when any table below changes. A roster records the version it was
# built with, and a different version is refused, because the same address
# would hash to a different value and the roster would silently match less.
NORMALIZER_VERSION = 3

# The shortest key file accepted, in bytes. A short key can be guessed, and a
# guessed key turns the roster back into a list.
MIN_KEY_BYTES = 16

# The longest run of words hashed from the front of a dataset address. A long
# value such as a street line followed by a city and a ZIP code is tried one
# prefix at a time, so the street line is found inside it.
MAX_PREFIX_WORDS = 10

# The default for --max-unchecked: the share of rows that may have no street
# line in any named field before the run exits 4. It is zero, because a row the
# tool could not read is a row it did not check, and exit 0 must not hide that.
MAX_UNCHECKED_PERCENT = 0

# The widest house number range, such as 410-414, that is expanded into one
# street line per number. A wider range is tried as written only.
MAX_RANGE = 200

# The longest house number word that is read as a range end. Python 3.11 and
# later raise ValueError from int() on a run of more than 4300 digits.
MAX_NUMBER_DIGITS = 18

# A typed column name shorter than this gets no "did you mean" hint, because
# two edits make almost any short cell look close to it.
MIN_HINT_CHARS = 5

ROSTER_MAGIC = "exemptguard-roster 1"
DEFAULT_SAMPLE = 10

# Street suffix rows. The first word is the Postal Service standard
# abbreviation, the rest are the primary name and every variant listed beside
# it in Appendix C1 of USPS Publication 28. Each word is folded to the first.
# MEADOWS appears twice in the appendix, under MEADOW and as its own row; the
# later row wins, which is harmless because both sides of a match fold alike.
SUFFIX_ROWS = (
    "ALY ALLEE ALLY ALLEY", "ANX ANNEX ANNX ANEX", "ARC ARCADE",
    "AVE AV AVEN AVENU AVN AVNUE AVENUE", "BYU BAYOO BAYOU", "BCH BEACH",
    "BND BEND", "BLF BLUF BLUFF", "BLFS BLUFFS", "BTM BOT BOTTM BOTTOM",
    "BLVD BOUL BOULV BOULEVARD", "BR BRNCH BRANCH", "BRG BRDGE BRIDGE",
    "BRK BROOK", "BRKS BROOKS", "BG BURG", "BGS BURGS",
    "BYP BYPA BYPAS BYPS BYPASS", "CP CMP CAMP", "CYN CANYN CNYN CANYON",
    "CPE CAPE", "CSWY CAUSWA CAUSEWAY",
    "CTR CEN CENT CENTR CENTRE CNTER CNTR CENTER", "CTRS CENTERS",
    "CIR CIRC CIRCL CRCL CRCLE CIRCLE", "CIRS CIRCLES", "CLF CLIFF",
    "CLFS CLIFFS", "CLB CLUB", "CMN COMMON", "CMNS COMMONS", "COR CORNER",
    "CORS CORNERS", "CRSE COURSE", "CT COURT", "CTS COURTS", "CV COVE",
    "CVS COVES", "CRK CREEK", "CRES CRSENT CRSNT CRESCENT", "CRST CREST",
    "XING CRSSNG CROSSING", "XRD CROSSROAD", "XRDS CROSSROADS", "CURV CURVE",
    "DL DALE", "DM DAM", "DV DIV DVD DIVIDE", "DR DRIV DRV DRIVE",
    "DRS DRIVES", "EST ESTATE", "ESTS ESTATES",
    "EXPY EXP EXPR EXPRESS EXPW EXPRESSWAY", "EXT EXTN EXTNSN EXTENSION",
    "EXTS EXTENSIONS", "FALL", "FLS FALLS", "FRY FRRY FERRY", "FLD FIELD",
    "FLDS FIELDS", "FLT FLAT", "FLTS FLATS", "FRD FORD", "FRDS FORDS",
    "FRST FORESTS FOREST", "FRG FORG FORGE", "FRGS FORGES", "FRK FORK",
    "FRKS FORKS", "FT FRT FORT", "FWY FREEWY FRWAY FRWY FREEWAY",
    "GDN GARDN GRDEN GRDN GARDEN", "GDNS GRDNS GARDENS",
    "GTWY GATEWY GATWAY GTWAY GATEWAY", "GLN GLEN", "GLNS GLENS",
    "GRN GREEN", "GRNS GREENS", "GRV GROV GROVE", "GRVS GROVES",
    "HBR HARB HARBR HRBOR HARBOR", "HBRS HARBORS", "HVN HAVEN",
    "HTS HT HEIGHTS", "HWY HIGHWY HIWAY HIWY HWAY HIGHWAY", "HL HILL",
    "HLS HILLS", "HOLW HLLW HOLLOWS HOLWS HOLLOW", "INLT INLET",
    "IS ISLND ISLAND", "ISS ISLNDS ISLANDS", "ISLE ISLES",
    "JCT JCTION JCTN JUNCTN JUNCTON JUNCTION", "JCTS JCTNS JUNCTIONS",
    "KY KEY", "KYS KEYS", "KNL KNOL KNOLL", "KNLS KNOLLS", "LK LAKE",
    "LKS LAKES", "LAND", "LNDG LNDNG LANDING", "LN LANE", "LGT LIGHT",
    "LGTS LIGHTS", "LF LOAF", "LCK LOCK", "LCKS LOCKS",
    "LDG LDGE LODG LODGE", "LOOP LOOPS", "MALL", "MNR MANOR", "MNRS MANORS",
    "MDW MEADOWS MEADOW", "MDWS MEDOWS MEADOWS", "MEWS", "ML MILL",
    "MLS MILLS", "MSN MISSN MSSN MISSION", "MTWY MOTORWAY", "MT MNT MOUNT",
    "MTN MNTAIN MNTN MOUNTIN MTIN MOUNTAIN", "MTNS MNTNS MOUNTAINS",
    "NCK NECK", "ORCH ORCHRD ORCHARD", "OVAL OVL", "OPAS OVERPASS",
    "PARK PRK", "PARK PARKS", "PKWY PARKWY PKWAY PKY PARKWAY",
    "PKWY PKWYS PARKWAYS", "PASS", "PSGE PASSAGE", "PATH PATHS",
    "PIKE PIKES", "PNE PINE", "PNES PINES", "PL PLACE", "PLN PLAIN",
    "PLNS PLAINS", "PLZ PLZA PLAZA", "PT POINT", "PTS POINTS", "PRT PORT",
    "PRTS PORTS", "PR PRR PRAIRIE", "RADL RAD RADIEL RADIAL", "RAMP",
    "RNCH RANCHES RNCHS RANCH", "RPD RAPID", "RPDS RAPIDS", "RST REST",
    "RDG RDGE RIDGE", "RDGS RIDGES", "RIV RVR RIVR RIVER", "RD ROAD",
    "RDS ROADS", "RTE ROUTE", "ROW", "RUE", "RUN", "SHL SHOAL",
    "SHLS SHOALS", "SHR SHOAR SHORE", "SHRS SHOARS SHORES", "SKWY SKYWAY",
    "SPG SPNG SPRNG SPRING", "SPGS SPNGS SPRNGS SPRINGS", "SPUR",
    "SPUR SPURS", "SQ SQR SQRE SQU SQUARE", "SQS SQRS SQUARES",
    "STA STATN STN STATION",
    "STRA STRAV STRAVEN STRAVN STRVN STRVNUE STRAVENUE",
    "STRM STREME STREAM", "ST STRT STR STREET", "STS STREETS",
    "SMT SUMIT SUMITT SUMMIT", "TER TERR TERRACE", "TRWY THROUGHWAY",
    "TRCE TRACES TRACE", "TRAK TRACKS TRK TRKS TRACK", "TRFY TRAFFICWAY",
    "TRL TRAILS TRLS TRAIL", "TRLR TRLRS TRAILER",
    "TUNL TUNEL TUNLS TUNNL TUNNELS TUNNEL", "TPKE TRNPK TURNPK TURNPIKE",
    "UPAS UNDERPASS", "UN UNION", "UNS UNIONS", "VLY VALLY VLLY VALLEY",
    "VLYS VALLEYS", "VIA VDCT VIADCT VIADUCT", "VW VIEW", "VWS VIEWS",
    "VLG VILL VILLAG VILLG VILLIAGE VILLAGE", "VLGS VILLAGES", "VL VILLE",
    "VIS VIST VST VSTA VISTA", "WALK WALKS", "WALK WALKS", "WALL", "WAY WY",
    "WAYS", "WL WELL", "WLS WELLS",
)

# Rows this tool adds. None of them is a claim about Publication 28.
EXTRA_ROWS = (
    "N NORTH", "S SOUTH", "E EAST", "W WEST",
    "NE NORTHEAST", "NW NORTHWEST", "SE SOUTHEAST", "SW SOUTHWEST",
    "APT APARTMENT", "BLDG BUILDING", "DEPT DEPARTMENT", "FL FLOOR",
    "HNGR HANGER", "RM ROOM", "SPC SPACE", "STE SUITE", "OFC OFFICE",
    "PH PENTHOUSE", "BSMT BASEMENT", "LBBY LOBBY", "LOWR LOWER",
    "UPPR UPPER", "FRNT FRONT", "ST SAINT",
    "1 FIRST", "2 SECOND", "3 THIRD", "4 FOURTH", "5 FIFTH",
    "6 SIXTH", "7 SEVENTH", "8 EIGHTH", "9 NINTH", "10 TENTH",
)

# Secondary unit designators (Publication 28, Appendix C2), as folded above.
# KEY folds to KY because Appendix C1 makes KY the street suffix for KEY.
DESIGNATORS = frozenset(
    "APT BLDG DEPT FL HNGR KY LOT PIER RM SLIP SPC STOP STE TRLR UNIT "
    "BSMT FRNT LBBY LOWR OFC PH REAR SIDE UPPR".split())


def _fold_table():
    table = {}
    for row in SUFFIX_ROWS + EXTRA_ROWS:
        words = row.split()
        for word in words[1:]:
            table[word] = words[0]
    return table


FOLD = _fold_table()

# The folded street suffixes and directions, for carries_more().
_SUFFIXES = frozenset(row.split()[0] for row in SUFFIX_ROWS)
_DIRECTIONS = frozenset("N S E W NE NW SE SW".split())

# U+00B4 would decompose to a space and split the word, so it is deleted like
# an apostrophe.
ACUTE = u"\u00b4"
_NOT_WORD = re.compile(r"[^0-9A-Z#]+")
# N.W. and S.E. are one word, NW and SE. Other letters are left alone.
_DOTTED = re.compile(r"\b([NS])\.([EW])\b")
# A house number a spreadsheet exported as a number: 412.0
_DECIMAL = re.compile(r"^\s*([0-9]+)\.0+(?=\s|$)")
# 5TH, 22ND: the ordinal ending is dropped from a numbered street, so NW 5TH ST
# and NW 5 ST are one street line. The house number (first word) is exempt.
_ORDINAL = re.compile(r"^([0-9]+)(?:ST|ND|RD|TH)$")
_NORMALIZER = re.compile(r"^normalizer ([0-9]+)$")
_ATTACHED = re.compile(r"^([A-Z]+)([0-9][0-9A-Z]*)$")
_BREAK = re.compile(r"\r\n|\r|\n")
_HEX = re.compile(r"^[0-9a-f]{64}$")
_COUNT = re.compile(r"^count ([0-9]+)$")
_CHECK = re.compile(r"^check ([0-9a-f]{64})$")


# ====================================================================== core
# Everything from here to the CLI section is pure: text and bytes in, values
# out. No file, no print, no clock.

def _unitish(word):
    """True when a word can be the range of a unit: 4, B, 12C or a pound sign."""
    return word == "#" or any(c.isdigit() for c in word) or (
        len(word) == 1 and word.isalpha())


def _strip_unit(words):
    """Cut the unit off the end of a street line.

    A designator counts only from the third word on, and only when a range
    follows it or nothing does. KEY, PIER, STOP and SIDE are designators and
    also street names, so 100 KEY WEST AVE and 9 N PIER ST must stay whole.
    """
    for i in range(2, len(words)):
        if words[i] == "#":
            return words[:i]
        if words[i] in DESIGNATORS and (
                i + 1 == len(words) or _unitish(words[i + 1])):
            return words[:i]
    return words


def normalize(text):
    """The street line of an address as a tuple of folded words, or ().

    Case, punctuation, accents, no-break spaces and full-width digits are
    flattened. Everything after the first comma is dropped. An apostrophe is
    deleted (O'BRIEN is OBRIEN, and so is O, acute accent, BRIEN), N.W. is NW,
    and a house number written 412.0 is 412. Suffixes, directionals and unit words are folded to one spelling,
    an ordinal ending is dropped (5TH is 5), a unit is cut off, and leading
    zeros are removed from the house number.
    """
    if not text:
        return ()
    flat = unicodedata.normalize("NFKD", text.replace(ACUTE, ""))
    flat = flat.encode("ascii", "ignore")
    flat = flat.decode("ascii").upper().split(",")[0].replace("#", " # ")
    flat = _DECIMAL.sub(r"\1", flat.replace("'", ""))
    flat = _DOTTED.sub(r"\1\2", flat)
    words = []
    for word in _NOT_WORD.sub(" ", flat).split():
        match = _ATTACHED.match(word)
        if match and FOLD.get(match.group(1), match.group(1)) in DESIGNATORS:
            words.extend(match.groups())
        else:
            words.append(word)
    words = [FOLD.get(w, w) for w in words]
    words = words[:1] + [_ORDINAL.sub(r"\1", w) for w in words[1:]]
    if words and words[0].isdigit():
        words[0] = words[0].lstrip("0") or "0"
    return tuple(_strip_unit(words))


def addressable(words):
    """True when words can be a street line: a house number, then a word.

    A placeholder such as NO SITUS ADDRESS, a street name with no number and a
    city with a state are not street lines, so they are not "checked". Neither
    is a parcel number, a ZIP+4 or a phone number: after the house number, at
    least one word must hold a letter.
    """
    return (len(words) >= 2 and words[0][:1].isdigit()
            and any(c.isalpha() for w in words[1:] for c in w))


def prefixes(words):
    """Every run of two or more leading words, shortest first, capped."""
    return [words[:n] for n in range(2, min(len(words), MAX_PREFIX_WORDS) + 1)]


def numbered(words):
    """The street line, then once per number when it starts with a range.

    A house number range such as 410-414 covers 412, so each number in the
    range is a street line too (see MAX_RANGE). A range is two digit words
    before the street name, so 10 5TH ST (a numbered street) is read as one as
    well, which only holds more rows.
    """
    found = [words]
    if (len(words) > 2 and words[0].isdigit() and words[1].isdigit()
            and max(len(words[0]), len(words[1])) <= MAX_NUMBER_DIGITS):
        low, high = sorted((int(words[0]), int(words[1])))
        if 0 < high - low <= MAX_RANGE:
            for number in range(low, high + 1):
                found.append((str(number),) + words[2:])
    return found


def candidates(words):
    """The street lines to look up for one dataset address: every prefix of
    the words, and of each number of a house number range."""
    return [p for line in numbered(words) for p in prefixes(line)]


def hasher(key):
    return hmac.new(key, digestmod=hashlib.sha256)


def digest(base, words):
    """Keyed hash of one street line. base is hasher(key), copied per call."""
    mac = base.copy()
    mac.update(b"addr:" + " ".join(words).encode("ascii"))
    return mac.hexdigest()


def check_value(key):
    """A keyed hash of a constant, stored in the roster to prove the key."""
    mac = hasher(key)
    mac.update(b"check:exemptguard-roster-1")
    return mac.hexdigest()


def roster_text(key, digests):
    """The roster file: four header lines, then one sorted hash per line."""
    ordered = sorted(digests)
    head = [ROSTER_MAGIC, "normalizer %d" % NORMALIZER_VERSION,
            "check %s" % check_value(key), "count %d" % len(ordered)]
    return "\n".join(head + ordered) + "\n"


def parse_roster(text, key):
    """The set of hashes in a roster, or ValueError saying why it is refused.

    A roster that opens with the wrong key would match nothing and read as a
    clean run. A truncated one would match only part of the list. Both are
    refused here instead.
    """
    lines = [x.strip() for x in text.splitlines() if x.strip()]
    if len(lines) < 4 or lines[0] != ROSTER_MAGIC:
        raise ValueError("this file is not an exemptguard roster")
    # Only digits are echoed: the line is free text in a damaged roster.
    version = _NORMALIZER.match(lines[1])
    if not version:
        raise ValueError("the roster header is damaged")
    if int(version.group(1)) != NORMALIZER_VERSION:
        raise ValueError("the roster was built with a different address "
                         "normalizer (%s, this tool is %d). Rebuild it."
                         % (version.group(1), NORMALIZER_VERSION))
    stored = _CHECK.match(lines[2])
    counted = _COUNT.match(lines[3])
    if not stored or not counted:
        raise ValueError("the roster header is damaged")
    if not hmac.compare_digest(stored.group(1).encode("ascii"),
                               check_value(key).encode("ascii")):
        raise ValueError("the key does not open this roster. A wrong key "
                         "matches nothing and would read as a clean run.")
    entries = lines[4:]
    if len(entries) != int(counted.group(1)):
        raise ValueError("the roster says %s entries and holds %d. It is "
                         "truncated or edited." % (counted.group(1),
                                                   len(entries)))
    if not entries:
        raise ValueError("the roster is empty, so it blocks nothing")
    if not all(_HEX.match(e) for e in entries):
        raise ValueError("the roster holds a line that is not a hash")
    return frozenset(entries)


def parse_key(raw):
    """Key bytes from a key file. Trailing line breaks are not part of it."""
    key = raw.rstrip(b"\r\n")
    if len(key) < MIN_KEY_BYTES:
        raise ValueError("the key file holds %d bytes. At least %d are "
                         "needed, or the roster could be guessed back into "
                         "a list." % (len(key), MIN_KEY_BYTES))
    return key


def _distance(a, b):
    """The edit distance between two strings, ignoring case."""
    a, b = a.lower(), b.lower()
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        new = [i]
        for j, y in enumerate(b, 1):
            new.append(min(row[j] + 1, new[j - 1] + 1, row[j - 1] + (x != y)))
        row = new
    return row[-1]


def _hint(wanted, names):
    """A name from the file that is one or two edits from the one typed.

    A file's own cells are never printed otherwise. A CSV with no header row
    makes its first data row the header, and that row can be an exempt person
    and address. A key file passed as the dataset is one cell of key text. A
    name two edits from text the user typed reveals nothing the user did not
    already know.
    """
    near = [n for n in names if 0 < _distance(wanted, n) <= 2
            and len(wanted) >= MIN_HINT_CHARS]
    if not near:
        return ""
    return " Did you mean %s?" % " or ".join(repr(n) for n in near[:3])


def compile_specs(specs, header):
    """Resolve each --address-field to column positions, or raise ValueError.

    A spec is one column name, or several joined by commas. A name that is
    twice in the header is refused, because one of the two columns would
    otherwise be read without a word and the other never looked at.
    """
    names = [h.strip() for h in header]
    compiled = []
    for spec in specs:
        wanted = [w.strip() for w in spec.split(",")]
        if not all(wanted):
            raise ValueError("--address-field %r has an empty column name"
                             % spec)
        positions = []
        for name in wanted:
            found = [i for i, n in enumerate(names) if n == name]
            if not found:
                raise ValueError(
                    "column %r is not in the CSV. It has %d column(s), and "
                    "their names are not printed.%s Does the file have a "
                    "header row?" % (name, len(names), _hint(name, names)))
            if len(found) > 1:
                raise ValueError("column %r is in the CSV %d times, so it is "
                                 "not clear which one holds the address"
                                 % (name, len(found)))
            positions.append(found[0])
        compiled.append((spec, positions))
    return compiled


def cell_words(cells, positions):
    """The normalised words of one spec in one row. Short rows read as blank."""
    parts = [cells[p].strip() for p in positions if p < len(cells)]
    return normalize(" ".join(p for p in parts if p))


class Report(object):
    """What a screening run found. rows is the number of data rows read, and
    percent the share of them that may have no street line."""

    def __init__(self, rows, roster_size, percent=MAX_UNCHECKED_PERCENT):
        self.rows = rows
        self.roster_size = roster_size
        self.percent = percent
        self.checked = 0
        self.unchecked = []   # dataset lines with no street line
        self.hits = []        # (row index, dataset line, spec)


def screen(rows, compiled, key, digests, percent=MAX_UNCHECKED_PERCENT):
    """Screen rows, a list of (line, cells), against the roster hashes."""
    report = Report(len(rows), len(digests), percent)
    base = hasher(key)
    for index, (line, cells) in enumerate(rows):
        usable = False
        matched = None
        for spec, positions in compiled:
            words = cell_words(cells, positions)
            if not addressable(words):
                continue
            usable = True
            if matched is None and any(
                    digest(base, p) in digests for p in candidates(words)):
                matched = spec
        if matched is not None:
            report.hits.append((index, line, matched))
        if usable:
            report.checked += 1
        else:
            report.unchecked.append(line)
    return report


def too_many(part, whole, percent):
    """True when part is more than percent of whole."""
    return part * 100 > percent * whole


def too_little(report):
    """True when more rows than the report allows were not checked, or when
    rows were read and none was checked, whatever the allowance."""
    return (bool(report.rows) and not report.checked) or too_many(
        len(report.unchecked), report.rows, report.percent)


def gate(report):
    """The exit code of a screening run."""
    if report.hits:
        return 1
    if too_little(report):
        return 4
    return 0


def street_end(words):
    """A roster line cut after its street suffix, or the words unchanged.

    The dataset side is tried by prefix, so a roster line must stop where the
    street stops. A city after the suffix (412 LARKSPUR LN FAIRVIEW) would
    otherwise match only a dataset line that carries the same city. A direction
    or another suffix after the first suffix is part of the street
    (12 OAK ST NE, 5 PARK AVE). A cut in the wrong place leaves a shorter
    entry, which holds more rows, not fewer.
    """
    first = first_suffix(words)
    if first is None:
        return words
    end = first + 1
    while end < len(words) and (words[end] in _SUFFIXES
                                or words[end] in _DIRECTIONS):
        end += 1
    return words[:end]


def first_suffix(words):
    """The index of the first street suffix after the street name, or None.

    The search starts at the third word, so 5 PARK AVE has its suffix at AVE.
    """
    for i in range(2, len(words)):
        if words[i] in _SUFFIXES:
            return i
    return None


def street_forms(words):
    """Every street line one plain address is hashed as.

    The cut line (see street_end) and each shorter run that ends at a suffix or
    a direction, and the line before its first suffix. A city after the street
    with no comma can start with a suffix or a direction word (LAKE CITY,
    ST AUGUSTINE, NORTH PORT) and is then part of the cut, so the street alone
    must be in the roster too. A dataset that has no post-direction or no
    street type still matches. Every form is a prefix of the cut line, and a
    dataset line is tried by prefix, so each form only holds more rows.
    """
    cut = street_end(words)
    first = first_suffix(cut)
    if first is None:
        return [cut]
    return [cut[:n] for n in range(first, len(cut) + 1)]


def carries_more(words):
    """True when a roster line goes on after its street suffix."""
    return len(street_end(words)) < len(words)


def build_digests(rows, compiled, key):
    """Hashes for a roster from plain rows: (set, unusable lines, two-word n,
    cut n).

    A row with no street line is listed, not dropped without a word. A
    two-word key matches every dataset address that starts with those two
    words, and a line that went on after its suffix is cut (see street_end),
    so both are counted. A house number range is hashed as written and once
    per number (see numbered), and each line in the forms of street_forms.
    """
    base = hasher(key)
    found = set()
    short = set()
    long_ = set()
    unusable = []
    for line, cells in rows:
        usable = False
        for _, positions in compiled:
            words = cell_words(cells, positions)
            if addressable(words):
                usable = True
                for numbered_line in numbered(words):
                    for form in street_forms(numbered_line):
                        found.add(digest(base, form))
                cut = street_end(words)
                if len(words) == 2:
                    short.add(digest(base, words))
                if len(cut) < len(words):
                    long_.add(digest(base, cut))
        if not usable:
            unusable.append(line)
    return found, unusable, len(short), len(long_)


def _lines(numbers, sample):
    shown = ", ".join(str(n) for n in numbers[:sample])
    more = len(numbers) - sample
    return shown + (" and %d more" % more if more > 0 else "")


def describe(report, sample=DEFAULT_SAMPLE):
    """The lines a screening run prints. Counts and line numbers only."""
    out = ["rows checked: %d of %d, against %d roster entries"
           % (report.checked, report.rows, report.roster_size),
           "rows held back: %d" % len(report.hits)]
    if report.hits and sample:
        out.append("  dataset lines: %s"
                   % _lines([h[1] for h in report.hits], sample))
    if report.unchecked:
        out.append("rows with no street line (a house number, then a word) in "
                   "any named field: %d" % len(report.unchecked))
        if sample:
            out.append("  dataset lines: %s" % _lines(report.unchecked, sample))
    out.append("")
    code = gate(report)
    if code == 1:
        out.append("VERDICT: %d row(s) carry an address on the exempt roster. "
                   "Do not publish this dataset as it stands. Publish the "
                   "--out file." % len(report.hits))
    elif code == 4 and not report.checked:
        out.append("VERDICT: NOTHING CHECKED. No row had a street line in a "
                   "named field, so no row was compared with the roster. This "
                   "is not a clean dataset. Look for a wrong column, or an "
                   "address column that is empty.")
    elif code == 4:
        out.append("VERDICT: TOO LITTLE CHECKED. Only %d of %d row(s) had a "
                   "street line in a named field. The other %d row(s) were not "
                   "compared with the roster, and --max-unchecked allows %d "
                   "percent. This is not a clean dataset. Look for a wrong "
                   "column, or an address column that is empty. If those "
                   "rows are meant to be blank, raise --max-unchecked."
                   % (report.checked, report.rows, len(report.unchecked),
                      report.percent))
    else:
        out.append("VERDICT: CLEAN. %d of %d row(s) were checked and none "
                   "matched the roster." % (report.checked, report.rows))
        if report.unchecked:
            out.append("%d row(s) had no street line to check, within the %d "
                       "percent that --max-unchecked allows. This verdict "
                       "does not cover them."
                       % (len(report.unchecked), report.percent))
    return out


def describe_build(count, entries, unusable, short, sample=DEFAULT_SAMPLE,
                   long_=0):
    """The lines a roster build prints. Counts and line numbers only."""
    out = ["plain rows read: %d" % count,
           "roster entries: %d (rows that repeat an address count once, and each "
           "address is stored in several spellings)"
           % entries]
    if unusable:
        out.append("rows with no street line (a house number, then a word): "
                   "%d" % len(unusable))
        if sample:
            out.append("  plain lines: %s" % _lines(unusable, sample))
    if short:
        out.append("entries of only two words: %d. Each one matches every "
                   "dataset address that starts with the same two words."
                   % short)
    if long_:
        out.append("entries that went on after the street suffix: %d. Each "
                   "is cut at the suffix, so the roster holds the street line "
                   "only. A cut in the wrong place holds more rows, not fewer."
                   % long_)
    return out


# ====================================================================== I/O

def _breaks(cells):
    """How many line breaks the parsed cells of one record carry."""
    return sum(len(_BREAK.findall(c)) for c in cells)


def read_table(path):
    """The header and the data rows of a CSV as (line, cells).

    The line is the one the record starts on. A blank line is skipped, and a
    quoted cell that holds a line break counts as one record, so the reader's
    own line_num (where the record ends) is walked back by the breaks inside
    its cells. The file must be UTF-8: a lossy decode would turn an accented
    street name into something that no longer matches the roster, and a
    privacy check must fail closed. So must a stray quote: without strict, a
    cell that opens a quote and never closes it swallows every later row.
    """
    # utf-8-sig, because some exporters write a UTF-8 BOM, and it would
    # otherwise stay glued to the first column name (tested with a BOM file).
    with open(path, "r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.reader(handle, strict=True)
        header = next(reader, [])
        rows = []
        for cells in reader:
            if cells:
                rows.append((reader.line_num - _breaks(cells), cells))
    return header, rows


def write_clean(path, header, rows, report):
    """The dataset without the rows that matched, otherwise unchanged."""
    held = set(h[0] for h in report.hits)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        for index, (_, cells) in enumerate(rows):
            if index not in held:
                writer.writerow(cells)


def write_report(path, report):
    """Which dataset lines were held and by which field. Never the address."""
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["dataset_line", "field"])
        for _, line, spec in report.hits:
            writer.writerow([line, spec])


def write_roster(path, key, digests):
    with open(path, "w", newline="", encoding="ascii") as handle:
        handle.write(roster_text(key, digests))


# ----------------------------------------------------------------------- cli

class Stop(Exception):
    """End the run with this exit code. The message is already printed."""

    def __init__(self, code):
        Exception.__init__(self, code)
        self.code = code


def _stop(message, code):
    print("error: %s" % message, file=sys.stderr)
    raise Stop(code)


def _load_key(path):
    try:
        with open(path, "rb") as handle:
            return parse_key(handle.read())
    except ValueError as exc:
        return _refuse(exc)
    except (IOError, OSError) as exc:
        return _stop(exc, 2)


def _refuse(reason):
    print("REFUSED   %s\n\nVERDICT: REFUSED" % reason)
    raise Stop(3)


def _load_roster(path, key):
    try:
        with open(path, "r", newline="", encoding="utf-8",
                  errors="replace") as handle:
            return parse_roster(handle.read(), key)
    except ValueError as exc:
        return _refuse(exc)
    except (IOError, OSError) as exc:
        return _stop(exc, 2)


def _load_table(path):
    try:
        header, rows = read_table(path)
    except UnicodeDecodeError as exc:
        # The message of the exception names a byte of the file. Only the
        # offset is printed, because the file may be a key or a plain list.
        return _stop("%s: not UTF-8 text (first bad byte at offset %d). Save "
                     "the file as CSV UTF-8." % (path, exc.start), 2)
    except (IOError, OSError, csv.Error, UnicodeError) as exc:
        # A cell over csv's 131072 character limit and a missing file are
        # unreadable input, not a finding.
        return _stop("%s: %s" % (path, exc), 2)
    if not header:
        return _stop("%s: the file is empty. Name a CSV with a header row."
                     % path, 2)
    return header, rows


def _compile(specs, header):
    try:
        return compile_specs(specs, header)
    except ValueError as exc:
        return _stop(exc, 64)


def _same_file(a, b):
    """True when two paths reach one file: a link, a hard link or a spelling."""
    if os.path.exists(a) and os.path.exists(b):
        return os.path.samefile(a, b)
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(
        os.path.realpath(b))


def _no_clash(outputs, inputs):
    """Refuse an output that would replace an input or another output.

    Checked on a dry run too. The input is read in full before anything is
    written, and then it is gone.
    """
    for flag, path in outputs:
        for name, other in inputs:
            if _same_file(path, other):
                _stop("%s %s is also %s. Name a new file." % (flag, path, name),
                      64)
    for i, (flag, path) in enumerate(outputs):
        for other_flag, other in outputs[i + 1:]:
            if _same_file(path, other):
                _stop("%s and %s name the same file, so the second would "
                      "replace the first." % (flag, other_flag), 64)


def _distinct(inputs):
    """Refuse two inputs that are one file, such as a key named as the dataset.

    The dataset is read as a CSV, and a read error or a column error about it
    must never show the key or the roster.
    """
    for i, (name, path) in enumerate(inputs):
        for other_name, other in inputs[i + 1:]:
            if _same_file(path, other):
                _stop("%s and %s are the same file. Name the right one."
                      % (name, other_name), 64)


def _verb(path):
    """'replaced' when --apply is about to overwrite a file, else 'wrote'.

    An output that is not an input is replaced without a question, so a
    nightly rerun can reuse its names. The word keeps that from being silent.
    """
    return "replaced" if os.path.exists(path) else "wrote"


def _make_key(args):
    if not args.apply:
        print("Check only. %s was not written. Re-run with --apply."
              % args.make_key)
        return 0
    try:
        # O_EXCL: a key that replaced the old one would orphan its roster.
        fd = os.open(args.make_key, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                     0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(os.urandom(32).hex() + "\n")
    except FileExistsError:
        return _stop("%s already exists. A new key would orphan the roster "
                     "built with the old one, so it is not replaced."
                     % args.make_key, 2)
    except (IOError, OSError) as exc:
        return _stop("could not write %s: %s" % (args.make_key, exc), 2)
    print("wrote %s, 256 random bits. Keep it out of the repository and away "
          "from the roster." % args.make_key)
    return 0


def _build(args):
    if args.out or args.report:
        _stop("--out and --report belong to a screening run, not to "
              "--build-roster.", 64)
    _no_clash([("--roster", args.roster)],
              [("the plain list", args.build_roster),
               ("--key-file", args.key_file)])
    _distinct([("the plain list", args.build_roster),
               ("--key-file", args.key_file)])
    key = _load_key(args.key_file)
    header, rows = _load_table(args.build_roster)
    compiled = _compile(args.address_field, header)
    found, unusable, short, long_ = build_digests(rows, compiled, key)
    print("exemptguard: %s" % args.build_roster)
    for line in describe_build(len(rows), len(found), unusable, short,
                               args.sample, long_):
        print(line)
    if not found:
        print("\nVERDICT: NOTHING BUILT. No row had a street line, and an "
              "empty roster blocks nothing. Look for a wrong column.")
        return 4
    if too_many(len(unusable), len(rows), args.max_unchecked):
        print("\nVERDICT: TOO LITTLE BUILT. Only %d of %d plain row(s) had a "
              "street line, so the roster would leave %d of them out, and "
              "--max-unchecked allows %d percent. Nothing written. Look for "
              "a wrong column. If those rows cannot be matched, such as a "
              "PO Box, raise --max-unchecked and keep the plain list for "
              "them." % (len(rows) - len(unusable), len(rows), len(unusable),
                         args.max_unchecked))
        return 4
    if args.apply:
        verb = _verb(args.roster)
        try:
            write_roster(args.roster, key, found)
        except (IOError, OSError) as exc:
            return _stop("could not write %s: %s" % (args.roster, exc), 2)
        print("\n%s %s" % (verb, args.roster))
    else:
        print("\nCheck only. %s was not written. Re-run with --apply."
              % args.roster)
    if unusable:
        print("VERDICT: roster of %d entries. %d plain row(s) are NOT on it, "
              "so the roster does not cover them. Keep the plain list for "
              "them." % (len(found), len(unusable)))
    else:
        print("VERDICT: roster of %d entries. Every plain row is on it, so "
              "the plain list is not needed to screen a dataset."
              % len(found))
    return 0


def _screen(args):
    outputs = [(flag, path) for flag, path in (("--out", args.out),
                                               ("--report", args.report))
               if path]
    if args.apply and not outputs:
        _stop("--apply needs --out or --report.", 64)
    inputs = [("the dataset", args.dataset), ("--roster", args.roster),
              ("--key-file", args.key_file)]
    _no_clash(outputs, inputs)
    _distinct(inputs)
    key = _load_key(args.key_file)
    digests = _load_roster(args.roster, key)
    header, rows = _load_table(args.dataset)
    compiled = _compile(args.address_field, header)
    report = screen(rows, compiled, key, digests, args.max_unchecked)
    print("exemptguard: %s %d row(s), roster %s"
          % (args.dataset, len(rows), args.roster))
    for line in describe(report, args.sample):
        print(line)
    code = gate(report)
    if outputs and not args.apply:
        print("\nCheck only. %s not written. Re-run with --apply."
              % " and ".join(path for _, path in outputs))
    elif outputs and code == 4:
        print("\nNothing written, because too little was checked and a copy "
              "would look like a clean one.")
    elif outputs:
        for flag, path in outputs:
            verb = _verb(path)
            try:
                if flag == "--out":
                    write_clean(path, header, rows, report)
                else:
                    write_report(path, report)
            except (IOError, OSError, csv.Error) as exc:
                # A traceback would exit 1, which a scheduled job reads as
                # "a row matched". A failed write is a different fact.
                return _stop("could not write %s: %s" % (path, exc), 2)
            print("\n%s %s" % (verb, path))
    return code


def _parse(argv):
    ap = argparse.ArgumentParser(
        prog="exemptguard.py",
        description="Block a statutorily exempt home address from a "
                    "published dataset, using a hashed roster.",
        epilog="Nothing is written without --apply. The tool prints counts "
               "and line numbers, never an address, a hash or the key.",
        allow_abbrev=False,
    )
    ap.add_argument("dataset", nargs="?", metavar="DATASET",
                    help="the CSV to screen before it is published")
    ap.add_argument("--roster", help="the hashed roster file")
    ap.add_argument("--key-file", dest="key_file",
                    help="the file that holds the key. Never a flag value.")
    ap.add_argument("--address-field", dest="address_field", action="append",
                    help="the column that holds a street line, or several "
                         "column names joined by commas that are read as "
                         "one. Repeat the flag for a second address column.")
    ap.add_argument("--build-roster", dest="build_roster", metavar="PLAIN",
                    help="build the roster from this CSV of plain addresses "
                         "instead of screening a dataset")
    ap.add_argument("--make-key", dest="make_key", metavar="PATH",
                    help="create a new random key file at this path")
    ap.add_argument("--out", help="path for the dataset without the held rows")
    ap.add_argument("--report",
                    help="path for the list of held dataset lines")
    ap.add_argument("--max-unchecked", dest="max_unchecked", type=int,
                    default=MAX_UNCHECKED_PERCENT, metavar="PERCENT",
                    help="the share of rows (0 to 100) that may have no "
                         "street line before the run exits 4 (default %d). "
                         "The same limit applies to --build-roster."
                         % MAX_UNCHECKED_PERCENT)
    ap.add_argument("--sample", type=int, default=DEFAULT_SAMPLE,
                    help="how many line numbers to list under each heading "
                         "(default %d)" % DEFAULT_SAMPLE)
    ap.add_argument("--apply", action="store_true",
                    help="write the roster, the key, --out and --report. "
                         "Without this nothing is written.")
    ap.add_argument("--self-test", dest="self_test", action="store_true",
                    help="run the offline assertions and exit")
    return ap.parse_args(argv)


def _tolerate_odd_characters():
    """Make print() unable to fail on a character the console cannot encode.

    A file name with a character a piped cp1252 stdout cannot write would
    raise UnicodeEncodeError and exit 1, the code for "a row matched".
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(errors="replace")


def main(argv=None):
    """Run the CLI. An error this code did not anticipate exits 70, because 1
    is the code a scheduled job reads as 'a row matched'."""
    _tolerate_odd_characters()
    try:
        return _run(argv)
    except Exception as exc:
        print("error: unexpected %s: %s. This is a fault in the tool, not a "
              "finding about the data." % (type(exc).__name__, exc),
              file=sys.stderr)
        traceback.print_exc()
        return 70


def _run(argv):
    try:
        args = _parse(sys.argv[1:] if argv is None else argv)
    except SystemExit as exc:
        # argparse exits 2 on a flag it refuses, and 2 here means a file
        # could not be read. A mistyped --ap is a usage error, so it gets 64.
        return 64 if exc.code == 2 else exc.code
    if args.self_test:
        return self_test()
    try:
        modes = [m for m in (args.dataset, args.build_roster, args.make_key)
                 if m]
        if len(modes) != 1:
            _stop("name exactly one of DATASET, --build-roster and "
                  "--make-key. Use --self-test to verify the tool without "
                  "them.", 64)
        if args.sample < 0:
            _stop("--sample cannot be negative.", 64)
        if not 0 <= args.max_unchecked <= 100:
            _stop("--max-unchecked is a percent, from 0 to 100.", 64)
        if args.make_key:
            return _make_key(args)
        for flag, value in (("--roster", args.roster),
                            ("--key-file", args.key_file)):
            if not value:
                _stop("%s is required." % flag, 64)
        if not args.address_field:
            _stop("--address-field is required.", 64)
        return _build(args) if args.build_roster else _screen(args)
    except Stop as stop:
        return stop.code



# ------------------------------------------------------------------ self-test

def self_test():
    """Run the assertions in a temp directory that is removed even when one
    of them raises, so a crash never leaves exemptguard-selftest-* behind."""
    tmp = tempfile.mkdtemp(prefix="exemptguard-selftest-")
    try:
        return _self_test(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _self_test(tmp):
    """Assertions over the decision core and the CLI. No network, no real
    credentials. Every address and key here is synthetic. The only files are
    the ones written under tmp."""
    passed = [0]
    failed = []
    labels = []

    def check(cond, label):
        labels.append(label)
        if cond:
            passed[0] += 1
            print("PASS  %s" % label)
        else:
            failed.append(label)
            print("FAIL  %s" % label)

    def raises(fn, label):
        try:
            fn()
        except ValueError:
            check(True, label)
        except Exception as exc:
            check(False, "%s (wrong exception %r)" % (label, exc))
        else:
            check(False, "%s (no error raised)" % label)

    captured = []

    def cli(argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        captured.append(out.getvalue() + err.getvalue())
        return code, out.getvalue(), err.getvalue()

    def path(name):
        return os.path.join(tmp, name)

    def tmpfile(name, text):
        with open(path(name), "w", newline="", encoding="utf-8") as handle:
            handle.write(text)
        return path(name)

    def slurp(name):
        with open(name, "r", newline="", encoding="utf-8") as handle:
            return handle.read()

    print("exemptguard self-test: temporary files only, no network, no real "
          "credentials")
    print("-" * 68)

    N = normalize
    base_line = ("12", "OAK", "ST")

    # ---- normalising a street line
    check(N("12 Oak St.") == N("12 OAK STREET") == N("12 oak str") == base_line,
          "case, punctuation and the suffix spellings fold to one street line")
    check(N("412 Larkspur Lane") == ("412", "LARKSPUR", "LN"),
          "a spelled-out suffix folds to the Publication 28 abbreviation")
    check(N("88 North Quill Street") == ("88", "N", "QUILL", "ST")
          and N("5 Southwest 3rd Ave") == ("5", "SW", "3", "AVE"),
          "a spelled-out directional folds to its letters")
    check(N("88 N. Quill St, Apt 3, Fairview FL 33000") == N("88 N Quill St"),
          "everything after the first comma is dropped")
    units = ["Apt 4", "APT. 4", "#4", "# 4", "Apt #4", "APT4", "Unit B",
             "Suite 200", "Ste 200-A", "Lot 5", "Rm 12", "Fl 2", "Bldg C",
             "Trlr 9", "Apt", "Rear", "Upper", "Floor 3"]
    check(all(N("12 Oak St " + u) == base_line for u in units),
          "every unit spelling is cut off, including #4 and APT4  "
          "<-- pinned defect")
    check(N("12 Oak Apt 4") == ("12", "OAK"),
          "a unit is cut even when the street suffix is missing")
    check(N("12 Oak St FL 33000") == base_line,
          "a state and ZIP code after the street are cut with the FL")
    check(N("12 O'Brien Rd") == N("12 OBRIEN RD") == ("12", "OBRIEN", "RD")
          and N("123 N.W. 5th St") == N("123 NW 5th St")
          == ("123", "NW", "5", "ST")
          and N("5 S.E. Oak St") == ("5", "SE", "OAK", "ST")
          and N("412.0 Larkspur Lane") == N("412.00 Larkspur Ln")
          == ("412", "LARKSPUR", "LN")
          and N("12.5 Oak St") == ("12", "5", "OAK", "ST"),
          "an apostrophe is deleted, N.W. is NW, and a house number written "
          "412.0 is 412  <-- pinned defect")
    check(N("5 E.W. Oak St") == ("5", "E", "W", "OAK", "ST"),
          "only N.E., N.W., S.E. and S.W. are joined: other dotted letters "
          "stay separate words")
    check(N("412 Larkspur Ln, Fairview") == ("412", "LARKSPUR", "LN"),
          "a city after a comma is dropped")
    check(addressable(("12", "OAK")) and addressable(("0", "A"))
          and addressable(N("412A Larkspur Ln"))
          and addressable(("4A", "OAK"))
          and not addressable(("NO", "SITUS", "ADDRESS"))
          and not addressable(("LARKSPUR", "LN")) and not addressable(("12",))
          and not addressable(()),
          "a street line is a house number and then a word, so a placeholder "
          "or a street name alone is not one  <-- pinned defect")
    check(N("100 Key West Ave") == ("100", "KY", "W", "AVE")
          and N("9 N Pier St") == ("9", "N", "PIER", "ST")
          and N("1500 Heron Pier Road") == ("1500", "HERON", "PIER", "RD")
          and N("12 N Side St") == ("12", "N", "SIDE", "ST")
          and N("7 Stop Rd") == ("7", "STOP", "RD"),
          "the words KEY, PIER, SIDE and STOP in a street name are not read as a "
          "unit  <-- pinned defect")
    check(N("0012 Oak St") == base_line and N("000 Oak St")[0] == "0",
          "leading zeros leave the house number, and zero stays zero")
    check(N("5 Fifth Ave") == N("5 5th Ave") and N("5 Saint Johns Rd")
          == N("5 St Johns Rd"),
          "ordinal words and SAINT fold to one spelling")
    check(N("412 NW 5th Street") == N("412 NW 5 ST") == N("412 NW Fifth St")
          == ("412", "NW", "5", "ST")
          and N("412 SE 17th Ave") == N("412 SE 17 AVE")
          and N("22 2nd Ave") == N("22 2 Ave") and N("5th Oak St")[0] == "5TH",
          "a numbered street written with and without its ordinal ending "
          "is one street line, and the house number is left alone  "
          "<-- pinned defect")
    check(N("12 Oak St Suite200") == base_line
          and N("12 Oak St Apartment4") == base_line
          and N("12 Oak St Suite 200") == base_line,
          "a long-form unit joined to its number is split and cut")
    check(N("12 Oak\u00a0St") == base_line
          and N("\uff11\uff12 Oak St") == base_line,
          "a no-break space and full-width digits read as plain text  "
          "<-- pinned defect")
    check(N("12 Rivi\u00e8re Rd") == N("12 Riviere Rd")
          == N("12 Rivie\u0300re Rd"),
          "an accented name matches its unaccented spelling in both "
          "Unicode forms  <-- pinned defect")
    check(N("12-14 Oak St") == ("12", "14", "OAK", "ST"),
          "a hyphen separates words")
    check(N("12 Oak St Foo4") == ("12", "OAK", "ST", "FOO4"),
          "letters joined to a number split only when they name a unit")
    check(N(None) == N("") == N("   ") == N(",") == () and N("Vacant")
          == ("VACANT",),
          "blank text is no words, and one word stays one word")
    check(all(FOLD.get(v, v) == v for v in FOLD.values()) and len(FOLD) > 300,
          "folding is stable: folding a folded word changes nothing")
    table = "|".join(SUFFIX_ROWS + EXTRA_ROWS
                     + (" ".join(sorted(DESIGNATORS)),))
    check(hashlib.sha256(table.encode("ascii")).hexdigest() == (
        "f6e1f2305441184a66642e99b7be5b319a86454263387428db2ea0174248ae66")
          and len(SUFFIX_ROWS) == 206 and len(EXTRA_ROWS) == 34,
          "the suffix, extra-row and designator tables are the ones that "
          "were checked against Publication 28. If this fails after an edit, "
          "recheck the table, then bump NORMALIZER_VERSION and the pinned hash  "
          "<-- pinned defect")
    last = {}
    for row in SUFFIX_ROWS + EXTRA_ROWS:
        for variant in row.split()[1:]:
            last[variant] = row.split()[0]
    check(all(FOLD[v] == last[v] for v in last)
          and all(N("12 Oak %s" % v) == ("12", "OAK", last[v])
                  for v in last if last[v] not in DESIGNATORS)
          and all(N("12 Oak St %s 4" % d) == ("12", "OAK", "ST")
                  and N("12 Oak St %s" % d) == ("12", "OAK", "ST")
                  for d in DESIGNATORS),
          "every variant in the tables folds to its standard abbreviation "
          "and every designator cuts the unit off  <-- pinned defect")
    check(N("12 Oak St Apt4 Lane") == ("12", "OAK", "ST")
          and N("12 Oak St Apt4B Lane") == ("12", "OAK", "ST")
          and N("12 Oak St Boxwood4") == ("12", "OAK", "ST", "BOXWOOD4"),
          "a unit joined to its number, APT4, is split and cut, and another "
          "word with a digit is not  <-- pinned defect")
    check(N("12 O\u00b4Brien Ln") == N("12 O'Brien Ln") == N("12 OBrien Ln")
          == ("12", "OBRIEN", "LN") and N("12 O\u2019Brien Ln") == N(
              "12 OBrien Ln"),
          "an acute accent in a name is deleted like an apostrophe, and does "
          "not split the word  <-- pinned defect")
    check(prefixes(("A", "B", "C")) == [("A", "B"), ("A", "B", "C")]
          and prefixes(("A",)) == []
          and len(prefixes(tuple("W%d" % i for i in range(15)))[-1])
          == MAX_PREFIX_WORDS,
          "prefixes start at two words and stop at the cap")
    ten = ("1",) + tuple("W%d" % i for i in range(2, 11))
    eleven = ten + ("W11",)
    check(len(ten) == MAX_PREFIX_WORDS == 10
          and ten in candidates(eleven + ("W12",))
          and eleven not in candidates(eleven + ("W12",)),
          "a ten-word street line is found inside a longer one and an "
          "eleven-word line is not  <-- pinned defect")
    check(candidates(("410", "414", "LARKSPUR", "LN"))
          == prefixes(("410", "414", "LARKSPUR", "LN")) + [
              p for n in range(410, 415)
              for p in prefixes((str(n), "LARKSPUR", "LN"))]
          and ("412", "LARKSPUR", "LN") in candidates(
              ("414", "410", "LARKSPUR", "LN"))
          and ("411", "LARKSPUR", "LN") in candidates(
              ("410", "411", "LARKSPUR", "LN"))
          and ("411", "LARKSPUR", "LN") in candidates(
              ("409", "411", "LARKSPUR", "LN"))
          and candidates(("410", "410", "A", "B")) == prefixes(
              ("410", "410", "A", "B"))
          and candidates(("410", "414")) == prefixes(("410", "414"))
          and ("412", "LARKSPUR", "LN") in candidates(
              ("212", "412", "LARKSPUR", "LN"))
          and ("412", "LARKSPUR", "LN") not in candidates(
              ("211", "412", "LARKSPUR", "LN")),
          "a house number range is tried one number at a time, up to "
          "MAX_RANGE wide  <-- pinned defect")
    check(("412", "LARKSPUR", "LN") in candidates(("412", "413", "LARKSPUR", "LN"))
          and ("413", "LARKSPUR", "LN") in candidates(
              ("412", "413", "LARKSPUR", "LN"))
          and ("412", "LARKSPUR") in candidates(("410", "414", "LARKSPUR")),
          "the smallest range, two neighbours, and a range before a one-word "
          "street are both tried  <-- pinned defect")
    giant = "9" * 5000
    edge = "1" * MAX_NUMBER_DIGITS
    edge2 = "1" * (MAX_NUMBER_DIGITS - 1) + "2"
    check(len(numbered((edge, edge2, "OAK"))) == 3
          and len(numbered((edge, "1" * (MAX_NUMBER_DIGITS + 1), "OAK"))) == 1
          and numbered(("5", giant, "OAK")) == [("5", giant, "OAK")]
          and numbered((giant, "5", "OAK")) == [(giant, "5", "OAK")]
          and numbered(("4A", "5", "OAK")) == [("4A", "5", "OAK")]
          and not addressable(("4A", "5")),
          "the longest house number that can end a range is "
          "MAX_NUMBER_DIGITS wide, and a number with a letter is not a "
          "range  <-- pinned defect")
    check(candidates((giant, giant, "OAK")) == prefixes((giant, giant, "OAK"))
          and numbered(("1", "2")) == [("1", "2")]
          and numbered((giant, "2", "OAK")) == [(giant, "2", "OAK")],
          "a house number of thousands of digits is not read as a range end "
          "and raises nothing on any Python  <-- pinned defect")

    # ---- the hash, the key and the roster file
    key = b"synthetic-test-key-0123456789"
    other = b"another-synthetic-key-abcdefgh"
    base = hasher(key)
    d1 = digest(base, base_line)
    check(len(d1) == 64 and d1 == digest(base, base_line)
          == digest(hasher(key), base_line),
          "a hash is 64 hex characters and the same every time")
    check(d1 != digest(hasher(other), base_line)
          and d1 != hashlib.sha256(b"12 OAK ST").hexdigest()
          and d1 != hashlib.sha256(b"addr:12 OAK ST").hexdigest(),
          "the hash depends on the key, so it is not a plain SHA-256 that "
          "anyone could compute from the public address list  "
          "<-- pinned defect")
    check(d1 == "7b66b8564b6bbdbb78f48bc098e8e7625b34fd0300f08000b9fc67ca87"
          "1b2bdc" and check_value(key) == "517a425c25bce4cc1b508acd909ff9056"
          "7866c38cc095f2befea89389e086ae1",
          "a hash and a key check are fixed values, so any change to the "
          "hashed text breaks old rosters visibly  <-- pinned defect")
    late = key[:20] + b"-a-different-tail"
    check(d1 != digest(hasher(late), base_line)
          and check_value(key) != check_value(late),
          "a key that differs only after its first 16 bytes is a different "
          "key  <-- pinned defect")
    text = roster_text(key, {d1, digest(base, ("1", "ELM", "ST"))})
    check(parse_roster(text, key) == {d1, digest(base, ("1", "ELM", "ST"))}
          and text.splitlines()[0] == ROSTER_MAGIC
          and text.splitlines()[4:] == sorted(text.splitlines()[4:])
          and "\r" not in text,
          "a roster reads back to the same set, sorted, with plain line ends")
    check(parse_roster(text.replace("\n", "\r\n") + "\n\n", key)
          == parse_roster(text, key),
          "a roster copied through Windows line ends and blank lines still "
          "reads  <-- pinned defect")
    raises(lambda: parse_roster(text, other),
           "a wrong key is refused, because it would match nothing and read "
           "as clean  <-- pinned defect")
    raises(lambda: parse_roster(text, late),
           "a key that differs late in the file is refused too")
    lines = text.splitlines()
    raises(lambda: parse_roster("\n".join(lines[:3]) + "\n", key),
           "a roster of three lines is refused as a file that is not a "
           "roster, not a crash")
    raises(lambda: parse_roster("\n".join(lines[:-1]) + "\n", key),
           "a roster with a line cut off is refused, not half-applied  "
           "<-- pinned defect")
    raises(lambda: parse_roster(text + d1 + "\n", key),
           "a roster with a line added is refused")
    raises(lambda: parse_roster(roster_text(key, set()), key),
           "a roster with no entries is refused, because it blocks nothing")
    raises(lambda: parse_roster("\n".join(lines[:-1] + ["z" * 64]) + "\n",
                                key),
           "a roster line that is not a hash is refused")
    raises(lambda: parse_roster(text.replace("roster 1", "roster 2", 1), key),
           "a file with another magic line is refused")
    raises(lambda: parse_roster("hello\n", key),
           "a file that is not a roster is refused")
    raises(lambda: parse_roster(
        text.replace("normalizer %d" % NORMALIZER_VERSION, "normalizer 9"),
        key),
        "a roster from another normalizer version is refused  "
        "<-- pinned defect")
    raises(lambda: parse_roster(
        text.replace("normalizer %d" % NORMALIZER_VERSION, "normalizer x"),
        key),
        "a roster whose normalizer line is not a version is refused")
    raises(lambda: parse_roster(text.replace("check ", "chunk "), key),
           "a damaged header line is refused")
    raises(lambda: parse_roster(text.replace("count 2", "count two"), key),
           "a count that is not a number is refused")

    def reason(fn):
        try:
            fn()
        except ValueError as exc:
            return str(exc)

    check("the roster is empty" in reason(
        lambda: parse_roster(roster_text(key, set()), key))
          and "(9, this tool is %d)" % NORMALIZER_VERSION in reason(
              lambda: parse_roster(text.replace(
                  "normalizer %d" % NORMALIZER_VERSION, "normalizer 9"), key))
          and "says 5 entries and holds 2" in reason(
              lambda: parse_roster(text.replace("count 2", "count 5"), key)),
          "a refused roster says why: empty, another normalizer version, or "
          "a count that does not match")
    check(parse_key(b"abcdefghijklmnop\r\n") == b"abcdefghijklmnop"
          and len(parse_key(b"x" * 16)) == 16,
          "a key keeps every byte but the line ending, and 16 bytes pass")
    raises(lambda: parse_key(b"x" * 15 + b"\n"),
           "a key of 15 bytes is refused")

    # ---- the two README demos: why a plain hash and a raw-text hash fail
    pool = ["%d Larkspur Ln" % n for n in range(1, 20001)]
    target = N("412 Larkspur Lane")
    plain_roster = {hashlib.sha256(" ".join(target).encode("ascii"))
                    .hexdigest()}
    keyed_roster = {digest(base, target)}

    def attack(known, make):
        return [a for a in pool if make(" ".join(N(a))) in known]

    plain_found = attack(plain_roster, lambda t: hashlib.sha256(
        t.encode("ascii")).hexdigest())
    keyed_found = attack(keyed_roster, lambda t: hashlib.sha256(
        t.encode("ascii")).hexdigest()) + attack(
            keyed_roster, lambda t: hashlib.sha256(
                ("addr:" + t).encode("ascii")).hexdigest())
    check(plain_found == ["412 Larkspur Ln"] and keyed_found == [],
          "a plain SHA-256 roster gives up its address to a search over a "
          "public address list, and the keyed roster does not")
    check([a for a in pool if digest(base, N(a)) in keyed_roster]
          == ["412 Larkspur Ln"],
          "a thief who holds the key as well as the keyed roster recovers the "
          "address with the same search, so the key is kept apart")
    demo_plain = ["412 Larkspur Lane", "88 N. Quillfeather Street, Apt 3",
                  "1500 Heron Pier Road", "21 Tamarack Court"]
    demo_data = ["412 Larkspur Ln", "90 Birchwood Ct",
                 "88 North Quillfeather St Unit B, Fairview FL 33000",
                 "4120 Larkspur Ln", "100 Key West Ave",
                 "21 Tamarack Ct Apt 2", ""]

    def raw_hash(text):
        mac = hasher(key)
        mac.update(text.strip().upper().encode("ascii"))
        return mac.hexdigest()

    raw_roster = {raw_hash(a) for a in demo_plain}
    demo_roster = frozenset(digest(base, N(a)) for a in demo_plain)
    check(sum(raw_hash(a) in raw_roster for a in demo_data) == 0
          and len(screen([(i + 2, [a]) for i, a in enumerate(demo_data)],
                         compile_specs(["A"], ["A"]), key,
                         demo_roster).hits) == 3,
          "a keyed hash of the raw text matches 0 of the 7 demo rows, and "
          "the folded hash holds 3")

    # ---- columns
    header = ["ID", "ADDNUM", "STNAME", "SITE", "SITE"]
    check(compile_specs(["ID, ADDNUM"], header) == [("ID, ADDNUM", [0, 1])]
          and compile_specs(["ADDNUM", "STNAME"], header)
          == [("ADDNUM", [1]), ("STNAME", [2])],
          "a spec names one column or several joined by commas")
    raises(lambda: compile_specs(["NOPE"], header),
           "a column that is not there is refused, and the file's columns are not listed")
    check(_hint("SITE_ADDR", ["ID", "SITE_ADR", "Jane Roe"])
          == " Did you mean 'SITE_ADR'?"
          and _hint("SITE_ADDR", ["ID", "Jane Roe", "412 Larkspur Lane"]) == ""
          and _hint("SITE_ADDR", ["site_addr"]) == ""
          and _hint("ID", ["IDS"]) == "" and _hint("SITE_ADDR", []) == ""
          and _hint("HOME_ADDR", ["HOME_ADDX", "HOME_ADD", "HOME_ADDRE",
                                  "HOME_ADR"]).count(" or ") == 2
          and _distance("kitten", "SITTING") == 3 and _distance("", "ab") == 2
          and _distance("abc", "abd") == 1 and _distance("abc", "abcd") == 1
          and _distance("abc", "") == 3 and _distance("ab", "ba") == 2
          and _distance("same", "SAME") == 0
          and _hint("SITE_ADDR", ["SITE_AD"]) == " Did you mean 'SITE_AD'?"
          and _hint("SITE_ADDR", ["SITE_A"]) == ""
          and _hint("ADDR1", ["ADDR2"]) == " Did you mean 'ADDR2'?"
          and _hint("ADDR", ["ADDX"]) == "",
          "a file's cells are never printed as column names, only a name "
          "within two edits of the typed one  <-- pinned defect")
    raises(lambda: compile_specs(["SITE_ADDR"], ["Xk9fT2mQpL7vZ4rWc8Hd"]),
           "a column error about a one-cell file raises")
    try:
        compile_specs(["SITE_ADDR"], ["Xk9fT2mQpL7vZ4rWc8Hd", "Jane Roe"])
    except ValueError as exc:
        text = str(exc)
    check("Xk9f" not in text and "Jane" not in text and "2 column(s)" in text,
          "the column error prints neither a key nor a person from the "
          "file  <-- pinned defect")
    raises(lambda: compile_specs(["SITE"], header),
           "a column name that appears twice is refused  <-- pinned defect")
    raises(lambda: compile_specs(["ID,"], header),
           "an empty column name in a spec is refused")
    raises(lambda: compile_specs([""], ["ID", ""]),
           "an empty spec does not select a column with a blank name")
    check(cell_words(["412", "Larkspur", "Lane"], [0, 1, 2])
          == ("412", "LARKSPUR", "LN") and cell_words(["412"], [3]) == ()
          and cell_words(["", " "], [0, 1]) == (),
          "a short row and blank cells read as no address, not an error")

    # ---- screening rows against a roster, in memory
    plain = [(2, ["412 Larkspur Lane"]), (3, ["88 N. Quill Street, Apt 3"]),
             (4, [""]), (5, ["Vacant"]), (6, ["412 LARKSPUR LN"]),
             (7, ["12 Broadway"])]
    found, unusable, short, long_ = build_digests(
        plain, compile_specs(["HOME"], ["HOME"]), key)
    check(len(found) == 5 and unusable == [4, 5] and short == 1
          and long_ == 0,
          "a repeated address counts once, an empty row and a one-word row "
          "are listed, and a two-word key is counted")
    two, none_, _, _ = build_digests([(2, ["1 A St", "9 B St"])],
                                     compile_specs(["X", "Y"], ["X", "Y"]),
                                     key)
    check(len(two) == 4 and none_ == [],
          "a row with a second address column gives a key per column")
    _, no_number, _, _ = build_digests(
        [(2, ["Larkspur Lane"]), (3, ["No Situs Address"])],
        compile_specs(["HOME"], ["HOME"]), key)
    check(no_number == [2, 3],
          "a plain-list row with no house number is listed, not hashed  "
          "<-- pinned defect")
    check(carries_more(N("412 Larkspur Lane Fairview"))
          and carries_more(N("412 Larkspur Lane Fairview FL 33000"))
          and not carries_more(N("12 Oak St NE"))
          and not carries_more(N("88 N Quillfeather St"))
          and not carries_more(N("5 Saint Johns Rd"))
          and not carries_more(N("100 Key West Ave"))
          and not carries_more(N("12 Oak Park Lane"))
          and not carries_more(("12", "OAK")),
          "a roster line that goes on after its street suffix is "
          "recognised, and a direction or a second suffix is not")
    _, _, _, city_n = build_digests(
        [(2, ["412 Larkspur Lane Fairview"]), (3, ["412 Larkspur Lane"]),
         (4, ["412 Larkspur Lane Fairview"])],
        compile_specs(["HOME"], ["HOME"]), key)
    check(city_n == 1,
          "the build counts a roster entry that goes on after its suffix "
          "once  <-- pinned defect")
    check(street_end(N("412 Larkspur Lane Fairview FL 33000"))
          == ("412", "LARKSPUR", "LN")
          and street_end(N("12 Oak St NE Fairview")) == ("12", "OAK", "ST", "NE")
          and street_end(N("12 Oak Park Lane Fairview"))
          == ("12", "OAK", "PARK", "LN")
          and street_end(N("12 Oak St")) == ("12", "OAK", "ST")
          and street_end(("12", "OAK")) == ("12", "OAK"),
          "a roster line is cut after its street suffix, a direction or a "
          "second suffix stays, and a line with no suffix is left whole")
    roster = frozenset(digest(base, w) for w in (
        ("412", "LARKSPUR", "LN"), ("88", "N", "QUILL", "ST")))
    spec1 = compile_specs(["A"], ["A"])
    cut_found, _, _, cut_n = build_digests(
        [(2, ["412 Larkspur Lane Fairview FL 34400"]),
         (3, ["88 N Quill St Fairview FL 34400"])],
        compile_specs(["HOME"], ["HOME"]), key)
    check(cut_found >= roster and len(cut_found) == 4 and cut_n == 2
          and len(screen([(2, ["412 Larkspur Ln"]), (3, ["88 N Quill St"]),
                          (4, ["90 Birchwood Ct"])], spec1, key,
                         cut_found).hits) == 2,
          "a roster built from lines that go on after the suffix finds a "
          "dataset line that stops at the street  <-- pinned defect")

    def held(*addresses, **kw):
        rows = [(i + 2, [a]) for i, a in enumerate(addresses)]
        return screen(rows, kw.get("specs", spec1), key, roster,
                      kw.get("percent", 50))

    rep = held("412 Larkspur Ln", "90 Birchwood Ct", "88 North Quill Street "
               "Unit B, Fairview FL 33000", "")
    check([h[1] for h in rep.hits] == [2, 4] and rep.checked == 3
          and rep.unchecked == [5] and rep.rows == 4 and gate(rep) == 1,
          "a dataset address that spells the street another way is held, "
          "and a blank one is unchecked")
    check(len(held("412 LARKSPUR LANE APT 9 FAIRVIEW FL 33000").hits) == 1
          and len(held("412 Larkspur Ln Fairview 33000").hits) == 1,
          "a street line followed by a city and a ZIP code with no comma is "
          "still found  <-- pinned defect")
    rep = held("2234-001-000", "34471-1234", "352-555-1234", "5 3")
    check(gate(rep) == 4 and rep.checked == 0 and len(rep.unchecked) == 4,
          "a parcel number, a ZIP+4, a phone number and two bare numbers are "
          "not street lines, so a wrong column is exit 4  <-- pinned defect")
    check(held("4120 Larkspur Ln", "41 Larkspur Ln", "1412 Larkspur Ln",
               "412 Larkspurs Ln").hits == [],
          "a different house number or street is not held: the match is on "
          "whole words, not on text  <-- pinned defect")
    check(len(held("412 Larkspur Ln Ext").hits) == 1,
          "a longer street line that begins with a roster line is held, "
          "because holding too much is the safe error")

    def forms_of(text):
        return frozenset(digest(base, f) for f in street_forms(N(text)))

    check(len(screen([(2, ["12 Oak St"])], spec1, key,
                     forms_of("12 Oak Street NE")).hits) == 1
          and len(screen([(2, ["12 Oak St NE"])], spec1, key,
                         forms_of("12 Oak Street")).hits) == 1
          and len(screen([(2, ["12 Oak St SW"])], spec1, key,
                         forms_of("12 Oak Street NE")).hits) == 1,
          "a roster line with a post-direction finds a dataset line "
          "without it, and the reverse, and holds the wrong direction too  "
          "<-- pinned defect")
    check(len(screen([(2, ["88 N Quillfeather"])], spec1, key,
                     forms_of("88 N Quillfeather St")).hits) == 1
          and len(screen([(2, ["412 Larkspur"])], spec1, key,
                         forms_of("412 Larkspur Lane")).hits) == 1
          and screen([(2, ["412 Birchwood"])], spec1, key,
                     forms_of("412 Larkspur Lane")).hits == [],
          "a dataset with no street type still finds the roster line  "
          "<-- pinned defect")
    check(len(screen([(2, ["412 Larkspur Ct"])], spec1, key,
                     forms_of("412 Larkspur Lane")).hits) == 1
          and len(screen([(2, ["12 Oak St"])], spec1, key,
                         forms_of("12 N Oak St")).hits) == 0
          and len(screen([(2, ["12 N Oak St"])], spec1, key,
                         forms_of("12 Oak St")).hits) == 0
          and len(screen([(2, ["9 Elm St; 412 Larkspur Ln"])], spec1, key,
                         forms_of("412 Larkspur Ln")).hits) == 0
          and len(screen([(2, ["9 Elm St & 412 Larkspur Ln"])], spec1, key,
                         forms_of("9 Elm St")).hits) == 1
          and screen([(2, ["Apt 4, 412 Larkspur Ln"])], spec1, key,
                     forms_of("412 Larkspur Ln")).unchecked == [2]
          and numbered(N("412-5 Larkspur Ln")) == [("412", "5", "LARKSPUR", "LN")]
          and ("5", "ST") in candidates(N("10 5th St"))
          and ("10", "ST") in candidates(N("10 5th St")),
          "the stated limits hold: a spelling kept on one side only, the "
          "street type, a second address in a cell, a unit first, a "
          "hyphenated unit and a range that is really a numbered street")
    check(street_forms(N("412 Larkspur Lane Lake City FL"))
          == [("412", "LARKSPUR"), ("412", "LARKSPUR", "LN"),
              ("412", "LARKSPUR", "LN", "LK")]
          and street_forms(N("5 Oak Ave North Port"))
          == [("5", "OAK"), ("5", "OAK", "AVE"), ("5", "OAK", "AVE", "N"),
              ("5", "OAK", "AVE", "N", "PRT")]
          and street_forms(("12", "OAK")) == [("12", "OAK")]
          and first_suffix(N("5 Park Ave")) == 2
          and first_suffix(("12", "OAK")) is None,
          "a city that starts with a suffix or a direction word is cut off "
          "in the roster by keeping every shorter street line  "
          "<-- pinned defect")
    city_forms = frozenset(
        digest(base, f) for line in numbered(N("412 Larkspur Lane Lake City"))
        for f in street_forms(line)) | frozenset(
        digest(base, f) for f in street_forms(N("9 Elm Street St Augustine")))
    check(len(screen([(2, ["412 Larkspur Ln"]), (3, ["9 Elm St, St Augustine"]),
                      (4, ["412 Larkspur Ln, Lake City"])],
                     spec1, key, city_forms).hits) == 3,
          "a roster city such as Lake City or St Augustine, typed after the "
          "suffix with no comma, does not hide the street  <-- pinned defect")
    range_found, _, _, _ = build_digests(
        [(2, ["412-414 Larkspur Ln"])], spec1, key)
    check(len(screen([(2, ["412 Larkspur Ln"]), (3, ["413 Larkspur Ln"]),
                      (4, ["414 Larkspur Ln"]), (5, ["415 Larkspur Ln"]),
                      (6, ["412 414 Larkspur Ln"])],
                     spec1, key, range_found).hits) == 4,
          "a roster home written as a range holds every number in it, and "
          "the range as the dataset spells it  <-- pinned defect")
    check(held("412 Larkspar Ln", "412 Lark Spur Ln").hits == [],
          "known limit: a misspelled street is not matched, there is no "
          "fuzzy matching")
    rep = held("90 Birchwood Ct", "55 Cedar Rd", "")
    check(gate(rep) == 0 and rep.checked == 2,
          "no match with rows checked is clean")
    rep = held("", "Vacant", "   ")
    check(gate(rep) == 4 and rep.checked == 0 and rep.unchecked == [2, 3, 4]
          and "NOTHING CHECKED" in "\n".join(describe(rep)),
          "rows read and none checked is exit 4, not a clean run  "
          "<-- pinned defect")
    check(gate(held()) == 0 and "CLEAN. 0 of 0" in "\n".join(describe(held())),
          "a dataset with no rows is not an error")
    rep = held("NO SITUS ADDRESS", "VACANT LAND", "Fairview FL",
               "Larkspur Ln", "Unit 4")
    check(gate(rep) == 4 and rep.checked == 0 and len(rep.unchecked) == 5
          and not rep.hits,
          "a placeholder, a street name with no house number and a city are "
          "not street lines, so they are not checked  <-- pinned defect")
    rep = held("90 Birchwood Ct", "55 Cedar Rd", "", "Vacant")
    shown = "\n".join(describe(rep))
    check(gate(rep) == 0 and rep.checked == 2
          and "VERDICT: CLEAN. 2 of 4 row(s) were checked" in shown
          and "2 row(s) had no street line to check" in shown
          and "does not cover them" in shown,
          "with 50 percent allowed, half the rows unchecked is still clean, "
          "and the verdict says which rows it does not cover  "
          "<-- pinned defect")
    rep = held("90 Birchwood Ct", "", "Vacant", "")
    shown = "\n".join(describe(rep))
    check(gate(rep) == 4 and rep.checked == 1
          and "TOO LITTLE CHECKED" in shown
          and "Only 1 of 4 row(s)" in shown and "NOTHING CHECKED" not in shown
          and "CLEAN" not in shown,
          "with 50 percent allowed, more than half the rows unchecked is exit 4, "
          "not a clean run  "
          "<-- pinned defect")
    rep = held(*(["90 Birchwood Ct"] * 49 + [""] * 51))
    rep50 = held(*(["90 Birchwood Ct"] * 50 + [""] * 50))
    check(gate(rep) == 4 and gate(rep50) == 0,
          "the limit is exact: 51 unchecked rows in 100 is exit 4 and 50 is "
          "not  <-- pinned defect")
    check(gate(held(*(["90 Birchwood Ct"] * 99 + [""] * 101))) == 4
          and gate(held(*(["90 Birchwood Ct"] * 100 + [""] * 100))) == 0,
          "the limit scales with the row count: 101 unchecked rows in 200 is "
          "exit 4 and 100 is not  <-- pinned defect")
    check(_lines([1, 2, 3], 3) == "1, 2, 3"
          and _lines([1, 2, 3], 2) == "1, 2 and 1 more"
          and any("rows with no street line (a house number, then a word) in "
                  "any named field: 3" == x for x in describe(held(
                      "", "Vacant", "   "))),
          "a list that fits --sample has no 'and N more', and the count of "
          "rows with no street line is printed")
    rep = held("90 Birchwood Ct")
    check(gate(rep) == 0 and rep.checked == 1
          and "CLEAN. 1 of 1" in "\n".join(describe(rep)),
          "one row checked and no match is clean")
    wide = held("412 Larkspur Ln", *([""] * 9))
    check(gate(wide) == 1,
          "a match is exit 1 even when most rows are unchecked")
    check(len(held("410-414 Larkspur Ln").hits) == 1
          and len(held("414-410 Larkspur Ln").hits) == 1
          and held("413-419 Larkspur Ln", "400-900 Larkspur Ln").hits == [],
          "an address range that covers a roster house number is held, and "
          "one that does not is not  <-- pinned defect")
    check(len(screen([(2, ["412.0", "Larkspur", "Lane"])],
                     compile_specs(["N,S,T"], ["N", "S", "T"]), key,
                     roster).hits) == 1,
          "a house number exported as 412.0 is held when it is on the "
          "roster  <-- pinned defect")
    city_roster = frozenset([digest(base, N("412 Larkspur Lane Fairview"))])
    check(screen([(2, ["412 Larkspur Ln"])], spec1, key, city_roster).hits
          == [] and len(screen([(2, ["412 Larkspur Ln Fairview"])], spec1, key,
                               city_roster).hits) == 1,
          "known limit: a roster line with a city after the street does not "
          "find a dataset line that stops at the street")
    two_specs = compile_specs(["A", "B"], ["A", "B"])
    rep = screen([(2, ["", "412 Larkspur Ln"]), (3, ["90 Birchwood Ct", ""]),
                  (4, ["412 Larkspur Ln", "88 N Quill St"])],
                 two_specs, key, roster)
    check([(h[1], h[2]) for h in rep.hits] == [(2, "B"), (4, "A")]
          and rep.checked == 3,
          "a second address column is checked, a row is held once, and the "
          "field that matched first is named")
    many = [(i, ["412 Larkspur Ln"]) for i in range(2, 30)]
    shown = describe(screen(many, spec1, key, roster), 3)
    check("  dataset lines: 2, 3, 4 and 25 more" in shown
          and not any("dataset lines" in x for x in
                      describe(screen(many, spec1, key, roster), 0)),
          "the list of held lines is cut at --sample, and --sample 0 lists "
          "none")
    check(not any("dataset lines" in x for x in describe(
        held("", "Vacant"), 0)) and any("dataset lines: 2, 3" in x
                                        for x in describe(held("", "Vacant"))),
          "the unchecked lines are listed too, and --sample 0 lists none")
    out_text = "\n".join(describe(rep)).lower()
    check("larkspur" not in out_text and "quill" not in out_text
          and roster.isdisjoint(out_text.split()),
          "the report text carries no address and no hash")
    b_lines = describe_build(7, 4, [6, 7], 2, 10)
    check(b_lines[2] == "rows with no street line (a house number, then a "
          "word): 2" and describe(held("90 Birchwood Ct"))[-2] == "",
          "the build report counts the plain rows with no street line, and a "
          "blank line sets the verdict apart")
    check(b_lines[0] == "plain rows read: 7"
          and any("plain lines: 6, 7" in x for x in b_lines)
          and any("only two words: 2." in x for x in b_lines),
          "the build report counts rows, entries, unusable rows and "
          "two-word entries")
    check(not any("plain lines" in x for x in describe_build(7, 4, [6], 0, 0))
          and len(describe_build(7, 4, [], 0, 0)) == 2,
          "the build report lists no lines at --sample 0 and prints no "
          "heading for a count of zero")
    check(any("entries that went on after the street suffix: 3."
              in x for x in describe_build(7, 4, [], 0, 10, 3)),
          "the build report counts entries that go on after the suffix")

    # ---- the CLI, on real files
    key_path = tmpfile("secret.bin", key.decode("ascii") + "\r\n")
    plain_csv = tmpfile(
        "plain.csv",
        "ID,HOME_ADDR\n1,412 Larkspur Lane\n"
        "2,\"88 N. Quillfeather Street, Apt 3\"\n3,1500 Heron Pier Road\n"
        "4,21 Tamarack Court\n5,\n6,Vacant\n7,412 LARKSPUR LN\n")
    roster_path = path("roster.txt")
    base_args = ["--roster", roster_path, "--key-file", key_path]
    build = ["--build-roster", plain_csv, "--address-field", "HOME_ADDR",
             "--max-unchecked", "30"]
    code, out, err = cli(build + base_args)
    check(code == 0 and not os.path.exists(roster_path)
          and "Check only. " in out and "roster entries: 8" in out
          and "plain lines: 6, 7" in out,
          "a roster build without --apply writes nothing and reports the "
          "counts")
    code, out, err = cli(build + base_args + ["--apply"])
    roster_file = slurp(roster_path)
    check(code == 0 and "wrote %s" % roster_path in out
          and out.startswith("exemptguard: %s\n" % plain_csv)
          and len(roster_file.splitlines()) == 12
          and parse_roster(roster_file, key) is not None,
          "--apply writes a roster of 8 hashes for 4 addresses that reads "
          "back with the key")
    low = roster_file.lower()
    check(not any(w in low for w in ("larkspur", "quill", "heron", "tamarack",
                                     "oak"))
          and all(_HEX.match(x) for x in roster_file.splitlines()[4:]),
          "the roster file holds no address text, only hashes  "
          "<-- pinned defect")

    dataset = (
        "PARCEL,ADDNUM,STNAME,STTYPE,SITE_ADDR,CITY\n"
        "P01,412,Larkspur,Lane,412 Larkspur Ln,Fairview\n"
        "P02,90,Birchwood,Court,90 Birchwood Ct,Fairview\n"
        "P03,88,N Quillfeather,Street,"
        "\"88 North Quillfeather St Unit B, Fairview FL 33000\",Fairview\n"
        "\n"
        "P04,4120,Larkspur,Lane,4120 Larkspur Ln,Fairview\n"
        "P05,55,Cedar,Road,\"55 Cedar\nHollow Rd\",Fairview\n"
        "P06,1500,Heron Pier,Road,1500 Heron Pier Rd,Fairview\n"
        "P07,100,Key West,Avenue,100 Key West Ave,Fairview\n"
        "P08,21,Tamarack,Court,\"21 Tamarack Ct\nApt 2\",Fairview\n"
        "P09,,,,,Fairview\n"
        "P10,7,Vacant\n")
    data_path = tmpfile("points.csv", dataset)
    run = [data_path] + base_args
    flat = dataset.split("\n")
    want = [i + 1 for i, line in enumerate(flat)
            if any(w in line for w in ("P01,", "P03,", "P06,", "P08,"))]
    code, out, err = cli(run + ["--address-field", "SITE_ADDR"])
    check(code == 1 and "rows held back: 4" in out
          and "dataset lines: %s" % ", ".join(map(str, want)) in out
          and "rows checked: 8 of 10" in out and "dataset lines: 13, 14" in out
          and "Publish the --out file" in out and err == "",
          "the dataset screens at exit 1 with the lines of the 4 rows the "
          "roster holds, counted past a blank line and a quoted line break  "
          "<-- pinned defect")
    check(want == [2, 4, 9, 11],
          "the expected lines were taken from the file, and the quoted line "
          "break moved the later ones down by one")
    code, out, err = cli(run + ["--address-field", "ADDNUM,STNAME,STTYPE"])
    check(code == 1 and "rows held back: 4" in out
          and "rows checked: 9 of 10" in out,
          "an address split over three columns is joined before it is "
          "checked")
    code, out, err = cli(run + ["--address-field", "SITE_ADDR",
                                "--address-field", "ADDNUM,STNAME,STTYPE"])
    check(code == 1 and "rows held back: 4" in out
          and "rows checked: 9 of 10" in out,
          "two --address-field flags check both and hold each row once")

    out_path, report_path = path("clean.csv"), path("held.csv")
    two_out = ["--out", out_path, "--report", report_path]
    sa = ["--address-field", "SITE_ADDR"]
    code, out, err = cli(run + sa + two_out)
    check(code == 1 and "Check only. " in out and not os.path.exists(out_path)
          and not os.path.exists(report_path),
          "nothing is written without --apply, and the run says so")
    code, out, err = cli(run + sa + two_out + ["--apply"])
    clean = slurp(out_path)
    check(code == 1 and "wrote %s" % out_path in out
          and "wrote %s" % report_path in out,
          "--apply writes the clean copy and the list of held lines")
    check(all(w not in clean for w in ("P01,", "P03,", "P06,", "P08,",
                                       "412 Larkspur Ln", "Quillfeather",
                                       "Heron", "Tamarack"))
          and all(w in clean for w in ("P02,", "P04,", "P05,", "P07,",
                                       "P09,", "P10,", "4120 Larkspur Ln"))
          and clean.startswith("PARCEL,ADDNUM,STNAME,STTYPE,SITE_ADDR,CITY\n")
          and "\"55 Cedar\nHollow Rd\"" in clean
          and clean.count("\nP") == 6,
          "the clean copy has no exempt address, keeps the other 6 rows "
          "whole, and keeps the header and a quoted line break")
    report_csv = slurp(report_path)
    check(report_csv == "dataset_line,field\n2,SITE_ADDR\n4,SITE_ADDR\n"
          "9,SITE_ADDR\n11,SITE_ADDR\n",
          "the report names the dataset line and the field, and nothing "
          "else")
    code, out, err = cli([out_path] + base_args + sa)
    check(code == 4 and "Only 4 of 6" in out,
          "screening the clean copy again exits 4 until the two blank rows "
          "are allowed  <-- pinned defect")
    code, out, err = cli([out_path] + base_args + sa
                         + ["--max-unchecked", "34"])
    check(code == 0 and "VERDICT: CLEAN. 4 of 6" in out,
          "screening the clean copy again exits 0, which proves the copy "
          "for the 4 rows that had a street line")
    code, out, err = cli(run + sa + ["--report", report_path, "--apply"])
    check(code == 1 and slurp(report_path) == report_csv,
          "--report alone writes only the report")

    # ---- refusals: nothing is written and the exit code says why
    before = slurp(out_path)
    empty_data = tmpfile("blank.csv", "PARCEL,SITE_ADDR\nP1,\nP2,Vacant\n")
    code, out, err = cli([empty_data] + base_args + sa + two_out + ["--apply"])
    check(code == 4 and "NOTHING CHECKED" in out
          and "Nothing written" in out and slurp(out_path) == before,
          "a dataset where no row has an address exits 4 and writes no copy "
          "that would look clean  <-- pinned defect")
    blanks = tmpfile("blanks.csv", "PARCEL,SITE_ADDR\nP1,90 Birchwood Ct\nP2,\n"
                     "P3,UNIT 2 412 Larkspur Ln\n")
    code, out, err = cli([blanks] + base_args + sa + two_out + ["--apply"])
    check(code == 4 and "TOO LITTLE CHECKED" in out and "Only 1 of 3" in out
          and "allows 0 percent" in out and "Nothing written" in out
          and slurp(out_path) == before and "CLEAN" not in out,
          "one row with no street line, here a unit written first, makes a "
          "run with no match exit 4 and write no copy  <-- pinned defect")
    code, out, err = cli([blanks] + base_args + sa + ["--max-unchecked", "67"])
    check(code == 0 and "VERDICT: CLEAN. 1 of 3" in out
          and "within the 67 percent that --max-unchecked allows" in out,
          "--max-unchecked allows the blank rows and the verdict still says "
          "it does not cover them")
    code, out, err = cli([empty_data] + base_args + sa
                         + ["--max-unchecked", "100"])
    check(code == 4 and "NOTHING CHECKED" in out,
          "no row checked is exit 4 even when 100 percent may be blank  "
          "<-- pinned defect")
    for bad in ("101", "-1"):
        code, out, err = cli(run + sa + ["--max-unchecked", bad])
        check(code == 64 and "--max-unchecked" in err,
              "--max-unchecked %s is a usage error" % bad)
    wrong = tmpfile("wrong.bin", "a-different-synthetic-key-xyz\n")
    code, out, err = cli([data_path, "--roster", roster_path, "--key-file",
                          wrong] + sa)
    check(code == 3 and "REFUSED" in out and "does not open" in out
          and "rows checked" not in out,
          "a wrong key exits 3 and checks nothing, instead of reporting a "
          "clean dataset  <-- pinned defect")
    short_key = tmpfile("short.bin", "tooshort\n")
    code, out, err = cli([data_path, "--roster", roster_path, "--key-file",
                          short_key] + sa)
    check(code == 3 and "REFUSED" in out and "8 bytes" in out,
          "a key file of 8 bytes is refused")
    cut = tmpfile("cut.txt", "\n".join(roster_file.splitlines()[:-1]) + "\n")
    code, out, err = cli([data_path, "--roster", cut, "--key-file",
                          key_path] + sa)
    check(code == 3 and "truncated" in out,
          "a truncated roster file is refused at the command line")
    code, out, err = cli([data_path, "--roster", path("none.txt"),
                          "--key-file", key_path] + sa)
    check(code == 2 and "none.txt" in err,
          "a roster that is not there exits 2")
    code, out, err = cli([data_path, "--roster", roster_path, "--key-file",
                          path("none.bin")] + sa)
    check(code == 2 and "none.bin" in err,
          "a key file that is not there exits 2")
    code, out, err = cli([path("none.csv")] + base_args + sa)
    check(code == 2 and "none.csv" in err, "a dataset that is not there exits 2")
    latin = path("latin.csv")
    with open(latin, "wb") as handle:
        handle.write(b"PARCEL,SITE_ADDR\nP1,12 Rivi\xe8re Rd\n")
    code, out, err = cli([latin] + base_args + sa)
    check(code == 2 and "latin.csv" in err and "rows checked" not in out
          and "offset 27" in err and "0xe8" not in err,
          "a dataset that is not UTF-8 exits 2 instead of being read "
          "lossily, and the error shows an offset and no byte  "
          "<-- pinned defect")
    zero = tmpfile("zero.csv", "")
    code, out, err = cli([zero] + base_args + sa)
    code2, out2, err2 = cli(["--build-roster", zero, "--address-field", "A"]
                            + base_args)
    check(code == 2 == code2 and "zero.csv: the file is empty" in err
          and "empty" in err2 and out == "",
          "a zero-byte file exits 2 and says it is empty, instead of a "
          "usage error about its columns")
    huge = tmpfile("huge.csv", "PARCEL,SITE_ADDR\nP1,%s\n" % ("x" * 140000))
    code, out, err = cli([huge] + base_args + sa)
    check(code == 2 and "field larger" in err,
          "a cell over the csv field limit exits 2")
    stray = tmpfile("stray.csv", "ID,NAME,SITE_ADDR\n0,Zed,7 Fir Rd\n"
                    "1,\"Bob,5 Pine Rd\n2,Ann,412 Larkspur Ln\n3,Cy,9 Elm St\n")
    code, out, err = cli([stray] + base_args + sa)
    check(code == 2 and "stray.csv" in err and "unexpected end" in err
          and "VERDICT" not in out,
          "a cell that opens a quote and never closes it exits 2, instead of "
          "swallowing every later row into one cell  <-- pinned defect")
    mostly = tmpfile("mostly.csv", "ID,SITE_ADDR,FULL\n0,,x\n1,,412 Larkspur Ln\n"
                     "2,,412 Larkspur Ln\n3,90 Birchwood Ct,y\n")
    code, out, err = cli([mostly] + base_args + sa + two_out + ["--apply"]
                         + ["--max-unchecked", "50"])
    check(code == 4 and "TOO LITTLE CHECKED" in out
          and "Only 1 of 4 row(s)" in out and "Nothing written" in out
          and slurp(out_path) == before,
          "a dataset where the named column is mostly empty exits 4 and "
          "writes no copy  <-- pinned defect")
    bom = path("bom.csv")
    with open(bom, "wb") as handle:
        handle.write(b"\xef\xbb\xbfSITE_ADDR,PARCEL\n412 Larkspur Ln,P1\n")
    code, out, err = cli([bom] + base_args + sa)
    check(code == 1 and "rows held back: 1" in out,
          "a UTF-8 byte order mark does not stay glued to the first column "
          "name")
    nohead = tmpfile("nohead.csv", "412 Larkspur Lane,Fairview\n"
                     "90 Birch Ct,Fairview\n")
    code, out, err = cli([nohead] + base_args + sa)
    check(code == 64 and "not in the CSV" in err
          and "Larkspur" not in err + out and "412" not in err + out
          and "Birch" not in err + out and "Fairview" not in err
          and "2 column(s)" in err,
          "a file with no header row exits 64 and the first data row, a "
          "home address, is not printed  <-- pinned defect")
    typed = tmpfile("typed.key", "Xk9fT2mQpL7vZ4rWc8Hd\n")
    named = tmpfile("named.csv", "Jane Roe,412 Larkspur Lane\n")
    code, out, err = cli([typed] + base_args + sa)
    code2, out2, err2 = cli(["--build-roster", named, "--address-field",
                             "HOME_ADDR", "--roster", path("n-r.txt"),
                             "--key-file", key_path])
    check(code == 64 == code2 and "Xk9f" not in err + out
          and "Jane" not in err2 + out2 and "Roe" not in err2 + out2
          and "1 column(s)" in err and "2 column(s)" in err2,
          "a typed key passed as the dataset and a person's name in a "
          "headerless plain list reach neither output  <-- pinned defect")
    near = tmpfile("near.csv", "PARCEL,SITE_ADR\nP1,90 Birchwood Ct\n")
    code, out, err = cli([near] + base_args + sa)
    check(code == 64 and "Did you mean 'SITE_ADR'?" in err,
          "a column name one edit off the typed one is offered")
    code, out, err = cli([key_path, "--roster", roster_path, "--key-file",
                          key_path] + sa)
    code2, out2, err2 = cli(["--build-roster", key_path, "--address-field",
                             "A", "--roster", path("k-r.txt"), "--key-file",
                             key_path])
    code3, out3, err3 = cli([roster_path, "--roster", roster_path,
                             "--key-file", key_path] + sa)
    check(code == 64 == code2 == code3 and "are the same file" in err
          and "are the same file" in err2 and "are the same file" in err3
          and out == "" and out2 == "" and out3 == "",
          "the dataset or the plain list named as the key file or the roster "
          "is refused before anything is read  <-- pinned defect")
    code, out, err = cli(run + ["--address-field", "NOPE"])
    check(code == 64 and "'NOPE' is not in the CSV" in err and out == "",
          "a wrong column name exits 64 and lists the real ones")
    dupes = tmpfile("dupes.csv", "A,SITE_ADDR,SITE_ADDR\nP1,1 Oak St,x\n")
    code, out, err = cli([dupes] + base_args + sa)
    check(code == 64 and "2 times" in err,
          "a dataset with the address column named twice exits 64  "
          "<-- pinned defect")
    code, out, err = cli(run + sa + ["--apply"])
    check(code == 64 and "--apply needs" in err,
          "--apply with nothing to write exits 64")
    for flag, target in (("--out", data_path), ("--out", roster_path),
                         ("--report", key_path)):
        code, out, err = cli(run + sa + [flag, target])
        check(code == 64 and "Name a new file" in err
              and slurp(data_path) == dataset,
              "%s naming the dataset, the roster or the key is refused on "
              "a dry run too" % flag)
    hard = path("hard.csv")
    os.link(data_path, hard)
    code, out, err = cli(run + sa + ["--out", hard, "--apply"])
    check(code == 64 and "Name a new file" in err
          and slurp(data_path) == dataset,
          "an --out that is a hard link to the dataset is refused and the "
          "dataset is not overwritten  <-- pinned defect")
    real_dir, link_dir = path("real"), path("linked")
    os.mkdir(real_dir)
    shutil.copy(data_path, os.path.join(real_dir, "d.csv"))
    made = subprocess.run(
        ["cmd", "/c", "mklink", "/J", link_dir, real_dir] if os.name == "nt"
        else ["ln", "-s", real_dir, link_dir],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode == 0
    check(made and _same_file(os.path.join(link_dir, "d.csv"),
                              os.path.join(real_dir, "d.csv"))
          and not _same_file(data_path, os.path.join(real_dir, "d.csv"))
          and _same_file(os.path.join(link_dir, "new.csv"),
                         os.path.join(real_dir, "new.csv"))
          and _same_file(path("new.csv"), path("x/../new.csv")),
          "a path through a directory link reaches the same file, and two "
          "files with the same text are not the same file")
    code, out, err = cli(run + sa + ["--out", path("same.csv"), "--report",
                                     path("same.csv"), "--apply"])
    check(code == 64 and "name the same file" in err
          and not os.path.exists(path("same.csv")),
          "--out and --report naming one file are refused and nothing is "
          "written")
    code, out, err = cli(run + sa + ["--out", path("no-dir/x.csv"), "--apply"])
    check(code == 2 and "could not write" in err and "VERDICT" in out,
          "a clean copy that cannot be written exits 2, and the verdict "
          "printed above it still reads")
    keep = tmpfile("precious.txt", "PRECIOUS\n")
    code, out, err = cli(run + sa + ["--out", keep, "--apply"])
    check(code == 1 and "replaced %s" % keep in out and "wrote" not in out
          and slurp(keep).startswith("PARCEL,"),
          "an existing --out file is replaced, and the run says 'replaced' "
          "instead of 'wrote'  <-- pinned defect")
    keep2 = tmpfile("precious2.txt", "PRECIOUS\n")
    code, out, err = cli(["--build-roster", plain_csv, "--address-field",
                          "HOME_ADDR", "--roster", keep2, "--key-file",
                          key_path, "--apply", "--max-unchecked", "30"])
    check(code == 0 and "replaced %s" % keep2 in out,
          "an existing roster file is replaced, and the run says so")
    header_only = tmpfile("header-only.csv", "PARCEL,SITE_ADDR\n")
    code, out, err = cli([header_only] + base_args + sa)
    check(code == 0 and "VERDICT: CLEAN. 0 of 0 row(s)" in out,
          "a dataset with a header and no rows exits 0, because it has "
          "nothing to check")
    code, out, err = cli(run + sa + ["--sample", "-1"])
    check(code == 64 and "--sample" in err, "a negative --sample exits 64")
    code, out, err = cli([data_path] + sa + ["--key-file", key_path])
    check(code == 64 and "--roster is required" in err,
          "a screening run with no --roster exits 64")
    code, out, err = cli([data_path] + sa + ["--roster", roster_path])
    check(code == 64 and "--key-file is required" in err,
          "a screening run with no --key-file exits 64")
    code, out, err = cli([data_path] + base_args)
    check(code == 64 and "--address-field is required" in err,
          "a screening run with no --address-field exits 64")
    code, out, err = cli(base_args)
    check(code == 64 and "exactly one" in err,
          "no dataset, no --build-roster and no --make-key exits 64")
    code, out, err = cli([data_path] + build + base_args)
    check(code == 64 and "exactly one" in err,
          "a dataset together with --build-roster exits 64")

    # ---- a prefix of any flag, the write flag first, is refused
    abbreviations = ("--ap", "--appl", "--app", "--rost", "--key", "--addr",
                     "--rep", "--sel", "--make", "--build", "--sam", "--ou",
                     "--max", "--max-un", "--max-unchecke")
    codes = []
    for flag in abbreviations:
        argv = run + sa + two_out + [flag]
        codes.append(cli(argv)[0])
    check(codes == [64] * len(abbreviations),
          "a prefix of a long flag, such as --ap for --apply, is refused with "
          "exit 64 and not read as the flag  <-- pinned defect")
    check(slurp(out_path) == clean,
          "and a refused prefix writes nothing")
    parsers = []
    for node in ast.walk(ast.parse(_source())):
        if (isinstance(node, ast.Call)
                and getattr(node.func, "attr", "") == "ArgumentParser"):
            parsers.append([k.arg for k in node.keywords])
    check(len(parsers) == 1 and all("allow_abbrev" in p for p in parsers),
          "every ArgumentParser in the source sets allow_abbrev")
    code, out, err = cli(["--help"])
    check(code == 0 and "usage:" in out and "--apply" in out,
          "--help prints the usage and exits 0")

    # ---- building a roster
    code, out, err = cli(build + base_args + ["--out", path("o.csv")])
    check(code == 64 and "belong to a screening run" in err,
          "--out with --build-roster exits 64")
    for target in (plain_csv, key_path):
        code, out, err = cli(["--build-roster", plain_csv, "--address-field",
                              "HOME_ADDR", "--roster", target, "--key-file",
                              key_path, "--apply"])
        check(code == 64 and "Name a new file" in err,
              "a roster path that is the plain list or the key is refused")
    check(slurp(plain_csv).startswith("ID,HOME_ADDR\n1,412 Larkspur")
          and slurp(key_path) == key.decode("ascii") + "\r\n",
          "and neither file was touched")
    code, out, err = cli(build + ["--roster", roster_path, "--key-file",
                                  short_key, "--apply"])
    check(code == 3 and "REFUSED" in out, "a short key refuses a build")
    code, out, err = cli(["--build-roster", path("none.csv"),
                          "--address-field", "A"] + base_args)
    check(code == 2, "a plain list that is not there exits 2")
    code, out, err = cli(["--build-roster", plain_csv, "--address-field",
                          "NOPE"] + base_args)
    check(code == 64, "a wrong column name exits 64 for a build too")
    no_addr = tmpfile("noaddr.csv", "ID,HOME_ADDR\n1,\n2,Vacant\n")
    before = slurp(roster_path)
    code, out, err = cli(["--build-roster", no_addr, "--address-field",
                          "HOME_ADDR"] + base_args + ["--apply"])
    check(code == 4 and "NOTHING BUILT" in out and slurp(roster_path) == before,
          "a plain list with no usable address exits 4 and leaves the "
          "existing roster alone  <-- pinned defect")
    code, out, err = cli(build + ["--roster", path("no-dir/r.txt"),
                                  "--key-file", key_path, "--apply"])
    check(code == 2 and "could not write" in err,
          "a roster that cannot be written exits 2")
    two_word = tmpfile("two.csv", "A\n12 Broadway\n")
    code, out, err = cli(["--build-roster", two_word, "--address-field", "A",
                          "--roster", path("two.txt"), "--key-file", key_path,
                          "--sample", "0"])
    check(code == 0 and "entries of only two words: 1" in out,
          "a two-word entry is called out in the build report")
    tail_csv = tmpfile("tail.csv", "ID,HOME\n1,412 Larkspur Ln Fairview FL "
                       "34400\n2,88 N Quill St Fairview FL 34400\n")
    tail_roster = path("tail-roster.txt")
    tail_data = tmpfile("tail-data.csv", "PARCEL,SITE_ADDR\nP1,412 Larkspur "
                        "Ln\nP2,88 N Quill St\nP3,90 Birchwood Ct\n")
    code, out, err = cli(["--build-roster", tail_csv, "--address-field",
                          "HOME", "--roster", tail_roster, "--key-file",
                          key_path, "--apply"])
    code2, out2, err2 = cli([tail_data, "--roster", tail_roster, "--key-file",
                             key_path] + sa)
    check(code == 0 and "entries that went on after the street suffix: 2" in out
          and "VERDICT: roster of 4 entries. Every plain row is on it" in out
          and code2 == 1 and "rows held back: 2" in out2,
          "a roster built from one-line addresses with a city and ZIP code "
          "holds the street-only dataset lines, instead of reading as clean  "
          "<-- pinned defect")
    mostly_plain = tmpfile("mostly-plain.csv", "ID,HOME_ADDR\n1,412 Larkspur "
                           "Lane\n" + "".join("%d,Vacant\n" % i
                                              for i in range(2, 11)))
    code, out, err = cli(["--build-roster", mostly_plain, "--address-field",
                          "HOME_ADDR", "--roster", path("mostly-r.txt"),
                          "--key-file", key_path, "--apply"])
    check(code == 4 and "TOO LITTLE BUILT" in out
          and "Only 1 of 10 plain row(s)" in out
          and not os.path.exists(path("mostly-r.txt")),
          "a plain list where most rows have no street line exits 4 and "
          "writes no roster  <-- pinned defect")
    half_rows = "".join("%d,%s\n" % (i, "12%d Elm St" % i if i < 5 else "-")
                        for i in range(10))
    half_ok = tmpfile("half-ok.csv", "ID,HOME_ADDR\n" + half_rows)
    half_bad = tmpfile("half-bad.csv", "ID,HOME_ADDR\n" + half_rows.replace(
        "4,124 Elm St", "4,-"))
    code, out, err = cli(["--build-roster", half_ok, "--address-field",
                          "HOME_ADDR", "--roster", path("half-r.txt"),
                          "--key-file", key_path, "--apply",
                          "--max-unchecked", "50"])
    code2, out2, err2 = cli(["--build-roster", half_bad, "--address-field",
                             "HOME_ADDR", "--roster", path("half-r2.txt"),
                             "--key-file", key_path, "--apply",
                             "--max-unchecked", "50"])
    check(code == 0 and os.path.exists(path("half-r.txt"))
          and code2 == 4 and not os.path.exists(path("half-r2.txt")),
          "the build limit is exact: 5 unusable rows in 10 builds with "
          "--max-unchecked 50, and 6 do not")
    code, out, err = cli(["--build-roster", half_ok, "--address-field",
                          "HOME_ADDR", "--roster", path("half-r3.txt"),
                          "--key-file", key_path, "--apply"])
    check(code == 4 and "TOO LITTLE BUILT" in out
          and "--max-unchecked allows 0 percent" in out
          and not os.path.exists(path("half-r3.txt")),
          "a plain list with even one row that has no street line builds "
          "no roster until the loss is allowed  <-- pinned defect")
    header_plain = tmpfile("header-plain.csv", "ID,HOME_ADDR\n")
    code, out, err = cli(["--build-roster", header_plain, "--address-field",
                          "HOME_ADDR", "--roster", path("hp.txt"),
                          "--key-file", key_path, "--apply"])
    check(code == 4 and "NOTHING BUILT" in out
          and not os.path.exists(path("hp.txt")),
          "a plain list with a header and no rows builds no empty roster  "
          "<-- pinned defect")
    odd = tmpfile("odd.txt", "\n".join(roster_file.splitlines()[:1]
                                       + ["412 LARKSPUR LANE, FAIRVIEW"]
                                       + roster_file.splitlines()[2:]) + "\n")
    code, out, err = cli([data_path, "--roster", odd, "--key-file", key_path]
                         + sa)
    check(code == 3 and "damaged" in out and "LARKSPUR" not in out + err,
          "a roster whose normalizer line holds text is refused without "
          "printing that text  <-- pinned defect")
    code, out, err = cli(build + base_args)
    check(code == 0 and "VERDICT: roster of 8 entries. 2 plain row(s) are NOT "
          "on it" in out and "not needed" not in out,
          "the build verdict states the number of entries and the rows left "
          "out, and does not call the plain list unneeded  "
          "<-- pinned defect")
    code, out, err = cli(["--build-roster", plain_csv, "--address-field",
                          "HOME_ADDR"] + base_args)
    check(code == 4 and "TOO LITTLE BUILT" in out,
          "a build that leaves 2 of 7 plain rows out exits 4 by default")

    # ---- the key file
    new_key = path("fresh.bin")
    code, out, err = cli(["--make-key", new_key])
    check(code == 0 and not os.path.exists(new_key) and "Check only" in out,
          "--make-key without --apply writes nothing")
    code, out, err = cli(["--make-key", new_key, "--apply"])
    with open(new_key, "rb") as handle:
        fresh = parse_key(handle.read())
    mode_ok = os.name == "nt" or (os.stat(new_key).st_mode & 0o077) == 0
    check(code == 0 and re.match(r"^[0-9a-f]{64}$", fresh.decode("ascii"))
          and fresh.decode("ascii") not in out and mode_ok
          and out.startswith("wrote %s, 256 random bits." % new_key),
          "--make-key --apply writes 64 hex characters, owner-only where "
          "the system has modes, and never prints them")
    code, out, err = cli(["--make-key", new_key, "--apply"])
    with open(new_key, "rb") as handle:
        again = parse_key(handle.read())
    check(code == 2 and "already exists" in err and again == fresh,
          "--make-key will not replace an existing key, which would orphan "
          "its roster  <-- pinned defect")
    code, out, err = cli(["--make-key", path("no-dir/k.bin"), "--apply"])
    check(code == 2 and "could not write" in err,
          "a key that cannot be written exits 2")
    code, out, err = cli(["--make-key", path("fresh2.bin"), "--apply"])
    with open(path("fresh2.bin"), "rb") as handle:
        check(parse_key(handle.read()) != fresh,
              "two generated keys are different")
    new_roster = path("fresh-roster.txt")
    code, _, _ = cli(build + ["--roster", new_roster, "--key-file", new_key,
                              "--apply"])
    code2, out, err = cli(run + sa + ["--roster", new_roster, "--key-file",
                                      new_key])
    code3, out3, err3 = cli(run + sa + ["--roster", new_roster, "--key-file",
                                        key_path])
    check(code == 0 and code2 == 1 and code3 == 3,
          "a generated key builds a roster that screens the dataset, and "
          "the first key no longer opens it")

    # ---- nothing secret reaches output
    artefacts = "\n".join(captured + [roster_file, clean, report_csv]).lower()
    leak = [w for w in (key.decode("ascii"), fresh.decode("ascii"),
                        "a-different-synthetic-key") if w in artefacts]
    check(leak == [], "no key appears in any output, report, roster or copy")
    shown = "\n".join(captured).lower()
    check(not any(w in shown for w in ("larkspur", "quillfeather", "heron",
                                       "tamarack")),
          "no exempt address appears in anything printed, in any run  "
          "<-- pinned defect")
    check(all(d not in shown for d in parse_roster(roster_file, key)),
          "no roster hash appears in anything printed")

    # ---- a character the console cannot encode, and a crash
    calls = []

    class Reconfigurable(io.StringIO):
        def reconfigure(self, **kw):
            calls.append(kw)

    with contextlib.redirect_stdout(Reconfigurable()), \
            contextlib.redirect_stderr(Reconfigurable()):
        main(["--help"])
    check(calls == [{"errors": "replace"}] * 2,
          "main reconfigures stdout and stderr to replace what they cannot "
          "encode")
    uni = tmpfile("d\u00e9j\u00e0.csv", "PARCEL,SITE_ADDR\nP1,412 Larkspur Ln\n")
    child = subprocess.run(
        [sys.executable, os.path.abspath(__file__), uni, "--roster",
         roster_path, "--key-file", key_path, "--address-field", "SITE_ADDR"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=dict(os.environ, PYTHONIOENCODING="ascii"))
    check(child.returncode == 1 and b"d?j?.csv" in child.stdout
          and b"Traceback" not in child.stderr
          and b"VERDICT: 1 row(s) carry" in child.stdout,
          "a file name the console cannot encode prints as ? and the verdict "
          "still arrives, instead of a traceback and exit 1  "
          "<-- pinned defect")

    real_screen = globals()["screen"]

    def boom(*args, **kw):
        raise RuntimeError("probe")

    try:
        globals()["screen"] = boom
        code, out, err = cli(run + sa)
    finally:
        globals()["screen"] = real_screen
    check(code == 70 and "unexpected RuntimeError: probe" in err
          and "Traceback" in err and "VERDICT" not in out,
          "an unexpected exception exits 70, not the 1 that means a row "
          "matched  <-- pinned defect")

    real_self_test = globals()["self_test"]
    try:
        globals()["self_test"] = lambda: 7
        code, out, err = cli(["--self-test", "--apply", "--out", "x"])
    finally:
        globals()["self_test"] = real_self_test
    check(code == 7,
          "main returns the exit status of --self-test and ignores every "
          "other flag, so a red self-test fails CI  <-- pinned defect")

    seen = []

    def exploding(tmp_dir):
        seen.append(tmp_dir)
        raise RuntimeError("probe")

    real_body = globals()["_self_test"]
    try:
        globals()["_self_test"] = exploding
        try:
            self_test()
        except RuntimeError:
            seen.append("raised")
    finally:
        globals()["_self_test"] = real_body
    check(len(seen) == 2 and seen[1] == "raised"
          and not os.path.exists(seen[0]),
          "a self-test that raises still removes its temp directory  "
          "<-- pinned defect")

    # ---- what the source is allowed to be
    tree = ast.parse(_source())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module.split(".")[0])
    check(imported <= {"__future__", "argparse", "ast", "contextlib", "csv",
                       "hashlib", "hmac", "importlib", "io", "os", "re",
                       "shutil", "subprocess", "sys", "tempfile", "traceback",
                       "unicodedata"}
          and not imported & {"socket", "ssl", "urllib", "http", "smtplib",
                              "ftplib", "requests", "xmlrpc"},
          "the tool imports the standard library only and no network module, "
          "so no credential can leave it")
    check(not any(isinstance(n, ast.JoinedStr) for n in ast.walk(tree)),
          "the source has no f-string, so it runs on Python 3.9")
    check(all(ord(c) < 128 for c in _source()),
          "the source is pure ASCII")

    # ---- the harness itself
    quiet = sys.stdout
    sys.stdout = io.StringIO()
    mark = len(failed)
    label_mark = len(labels)
    try:
        check(False, "probe: a false condition must be recorded as a failure")
        raises(lambda: None, "probe: a call that raises nothing must fail")
        raises(lambda: [][0], "probe: the wrong exception must fail")
    finally:
        sys.stdout = quiet
    probe = failed[mark:]
    del failed[mark:], labels[label_mark:]
    check(len(probe) == 3,
          "check() and raises() really do record a failure  <-- pinned defect")
    raises(lambda: (_ for _ in ()).throw(ValueError("x")),
           "and raises() accepts the ValueError it is looking for")

    def summary(passed_count, failures):
        print("-" * 68)
        total = passed_count + len(failures)
        if failures:
            print("%d assertions, %d failed" % (total, len(failures)))
            for f in failures:
                print("  FAILED: %s" % f)
            return 1
        print("%d assertions, 0 failed" % total)
        return 0

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        red = summary(1, ["probe one", "probe two"])
    check(red == 1 and "3 assertions, 2 failed" in buf.getvalue()
          and "  FAILED: probe two" in buf.getvalue(),
          "the footer reports failures by count and by name, and exits 1  "
          "<-- pinned defect")

    spec = importlib.util.spec_from_file_location(
        "exemptguard_imported", os.path.abspath(__file__))
    module = importlib.util.module_from_spec(spec)
    buf = io.StringIO()
    # No bytecode cache, so the self-test writes nothing outside tmp.
    cache_before = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        with contextlib.redirect_stdout(buf):
            spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = cache_before
    check(buf.getvalue() == "" and module.normalize("12 Oak Street") ==
          base_line, "importing the module prints nothing and exposes the core")

    check(passed[0] == len(labels) - len(failed) and len(labels) > 200,
          "the pass count is the number of checks made less the failures, so "
          "the footer total is not off by one  <-- pinned defect")
    return summary(passed[0], failed)


def _source():
    with open(os.path.abspath(__file__), "rb") as handle:
        return handle.read().decode("ascii")


if __name__ == "__main__":
    sys.exit(main())
