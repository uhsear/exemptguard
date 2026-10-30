# exemptguard

Hold back every row of a dataset whose street address is on a hashed roster of exempt addresses,
before the dataset is published. The roster holds keyed hashes and no address text, so the list
does not have to travel. Refuses a roster that the key does not open, refuses a dataset it could
not check, and writes a clean copy only under `--apply`.

Some people have a home address that the law keeps out of public records: certain officers,
judges and prosecutors, for example. The records office knows who they are. The GIS group does
not, and the list cannot go to the GIS group, because the list is the secret. So the check does
not happen. An analyst exports address points for the open data site. The file holds a few
hundred thousand rows, and a few of them are homes that the law says to withhold. Nobody looks,
because nobody can look. The file goes up, search engines index it, and the first anyone hears
of it is a phone call.

The defence everybody reaches for first is a hashed list. Hash every exempt address, send the
hashes, and compare. It looks safe, and it is not. Every address in a county is public, so an
attacker hashes every address and reads the roster back. The self-test runs that attack on 20,000
synthetic candidate addresses. A search against a plain SHA-256 roster finds the planted address.
The same search against a keyed hash (HMAC-SHA256) of the same address finds nothing, because the
key is not known. The key is what makes a stolen roster safe. This tool uses the key and keeps the
key out of the roster.

The roster is safe on its own. It is not safe together with the key. Whoever runs the check holds
both, and with both can run the same search over the public address list and recover the exempt
addresses (the self-test does that too). Give the key only to a person you would trust with the
list. What the roster removes is the plain list from every file that travels.

Hashing raw text fails the other way. The roster says `412 Larkspur Lane`. The dataset says
`412 Larkspur Ln`. The two hashes differ, and every row passes. In the demo below, a keyed hash
of the raw text, even after upper-casing and trimming it, matched 0 of 7 dataset rows, and three
of them are on the roster (the self-test pins both numbers). This tool
folds both sides to one spelling first: case, punctuation, `Lane` and `Ln`, `North` and `N`,
`Apt 4` and `#4`, `5th` and `5`, and a trailing city and ZIP code.

The quietest failure is a check that ran and compared nothing. The wrong key matches no row. A
roster cut short in transit matches only part of the list. An address column that is empty, or
that holds no street lines, gives nothing to compare. Each of them reads as a clean dataset to a
scheduled job. This tool refuses the first two with exit 3 and the last with exit 4. A column
name that is not in the file exits 64. It also refuses to build a roster from a plain list where
rows have no street line, unless you say how many may be left out.

```
$ python exemptguard.py --self-test
exemptguard self-test: temporary files only, no network, no real credentials
--------------------------------------------------------------------
...
PASS  every unit spelling is cut off, including #4 and APT4  <-- pinned defect
...
PASS  the words KEY, PIER, SIDE and STOP in a street name are not read as a unit  <-- pinned defect
...
PASS  a numbered street written with and without its ordinal ending is one street line, and the house number is left alone  <-- pinned defect
...
PASS  the hash depends on the key, so it is not a plain SHA-256 that anyone could compute from the public address list  <-- pinned defect
...
PASS  a wrong key is refused, because it would match nothing and read as clean  <-- pinned defect
...
PASS  a roster with a line cut off is refused, not half-applied  <-- pinned defect
...
PASS  a file's cells are never printed as column names, only a name within two edits of the typed one  <-- pinned defect
...
PASS  a roster built from lines that go on after the suffix finds a dataset line that stops at the street  <-- pinned defect
...
PASS  a street line followed by a city and a ZIP code with no comma is still found  <-- pinned defect
PASS  a parcel number, a ZIP+4, a phone number and two bare numbers are not street lines, so a wrong column is exit 4  <-- pinned defect
...
PASS  a roster line with a post-direction finds a dataset line without it, and the reverse, and holds the wrong direction too  <-- pinned defect
PASS  a dataset with no street type still finds the roster line  <-- pinned defect
...
PASS  a roster city such as Lake City or St Augustine, typed after the suffix with no comma, does not hide the street  <-- pinned defect
PASS  a roster home written as a range holds every number in it, and the range as the dataset spells it  <-- pinned defect
...
PASS  rows read and none checked is exit 4, not a clean run  <-- pinned defect
...
PASS  one row with no street line, here a unit written first, makes a run with no match exit 4 and write no copy  <-- pinned defect
...
PASS  a plain list with even one row that has no street line builds no roster until the loss is allowed  <-- pinned defect
...
PASS  the roster file holds no address text, only hashes  <-- pinned defect
...
PASS  a typed key passed as the dataset and a person's name in a headerless plain list reach neither output  <-- pinned defect
...
PASS  a prefix of a long flag, such as --ap for --apply, is refused with exit 64 and not read as the flag  <-- pinned defect
...
PASS  no exempt address appears in anything printed, in any run  <-- pinned defect
...
PASS  the footer reports failures by count and by name, and exits 1  <-- pinned defect
PASS  importing the module prints nothing and exposes the core
...
--------------------------------------------------------------------
206 assertions, 0 failed
```

The full run prints all 206 assertions. This block is a cut of a real run, and each `...` line
above is where it is cut. Every `PASS` line shown is a line of that run.

## What already exists

Matching two lists is a solved problem. A join in ArcGIS, pandas or SQL matches two tables
correctly once both are in one place and spelled alike. Neither condition holds here: the list
may not travel, and the spellings differ. A hash of the raw text does not fix the second.

Parsing and standardising an address is solved better than this tool does it.
[libpostal](https://github.com/openvenues/libpostal) (MIT) parses and normalises street
addresses with a statistical model, and [usaddress](https://github.com/datamade/usaddress) (MIT)
parses unstructured United States addresses into components. Use either to clean a roster before
it is built if your data is messy. This tool does not parse. It folds a street line with a fixed
table taken from the Postal Service, so it is small, deterministic and the same on every host.

Some states run an address confidentiality program that gives a protected person a substitute
address to use in new public records. Florida's rests on Florida Statutes ss. 741.401 to 741.409.
That removes the home address at the source, and where it applies it is the better answer. It
does not clean a record that already holds the real address, which is the case here.

A search of GitHub for `exemptguard` and ten related phrases (among them address redaction,
hashed roster, exempt address, confidential address and address suppression) found no tool that
screens a dataset against a hashed address roster, on 2026-10-22. The search was repeated on
2026-10-29 with the name and nine phrases, and found only this repository. That shows only that
the search found nothing. GitHub search matches words, and a tool described in other words would
not appear.

## Requirements

Python 3.9 or newer and nothing else. No `arcpy`, no third-party package, no network, no
database. The dataset and the plain list are CSVs, which every layer and table can be exported as.

The self-test prints the same 206 assertions on Windows (Python 3.13.2) and on Ubuntu (Python
3.12.3 and Python 3.9.25). The two Ubuntu outputs are byte for byte identical. The Windows output
differs from them only in its CR LF line ends. Python 3.9 on Windows was not run.
`coverage run --branch exemptguard.py --self-test` reports 100 percent of 1064 statements and
232 branches, so no line is left unreached offline. The self-test also starts two small
programs of the operating system: `cmd /c mklink` on Windows or `ln -s` elsewhere, to build a
directory link inside its own temporary folder, and a child Python for the console-encoding
check. Nothing is installed.

```
git clone https://github.com/uhsear/exemptguard.git
```

## Usage

Three steps. The first two are done by the person who holds the plain list. The third is done by
whoever screens the dataset, and needs the roster and the key but never the plain list. That
person can rebuild the list from the roster, the key and a public address list, so give the key
only to someone you would trust with the list.

```
python exemptguard.py --make-key secret.bin --apply
python exemptguard.py --build-roster plain.csv --address-field HOME_ADDR --roster roster.txt --key-file secret.bin --apply
python exemptguard.py points.csv --roster roster.txt --key-file secret.bin --address-field SITE_ADDR
python exemptguard.py points.csv --roster roster.txt --key-file secret.bin --address-field SITE_ADDR --out clean.csv --report held.csv --apply
python exemptguard.py points.csv --roster roster.txt --key-file secret.bin --address-field ADDNUM,PREDIR,STNAME,STTYPE,POSTDIR
python exemptguard.py --self-test
```

Send the roster to whoever screens. Send the key by another route. A roster and its key together
are as sensitive as the list.

| Flag | Default | What it does |
|---|---|---|
| `DATASET` | none | The CSV to screen. Exactly one of `DATASET`, `--build-roster` and `--make-key` is needed. |
| `--roster` | none | The roster file. Read when screening, written when building. |
| `--key-file` | none | The file that holds the key. The key is never a flag value. |
| `--address-field` | none | The column that holds a street line. Join several columns with commas to read them as one line. Repeat the flag for a second address column. |
| `--build-roster` | off | Build the roster from this CSV of plain addresses. Writes only with `--apply`. |
| `--make-key` | off | Create a random 256-bit key file at this path. Writes only with `--apply`, and never replaces a file. |
| `--out` | off | Write the dataset without the held rows to this path. Needs `--apply`. |
| `--report` | off | Write the held dataset line numbers to this path. Needs `--apply`. |
| `--max-unchecked` | `0` | The percent of rows (0 to 100) that may have no street line before the run exits 4. The same limit applies to a roster build. |
| `--sample` | `10` | How many line numbers to list under each heading. `0` lists none. |
| `--apply` | off | Actually write. Without it nothing is written. |
| `--self-test` | off | Run the assertions and exit. Other flags are ignored. |

Every flag must be spelled in full. The parser sets `allow_abbrev=False`, so `--ap` is refused
with exit 64 instead of being read as `--apply`. `--appl`, `--app`, `--rost`, `--key`, `--addr`,
`--rep`, `--sel`, `--make`, `--build`, `--sam`, `--ou`, `--max`, `--max-un` and `--max-unchecke`
are refused the same way, and a refused run writes nothing.

A path for `--out` or `--report` that is also the dataset, the roster or the key is refused with
exit 64, on a dry run too. Without that check `--apply` would replace the input with its own
clean copy. So is a dataset or plain list that is also the key file or the roster, because the
tool reads it as a CSV and an error about it could print part of the key or the roster. Any other
file that already exists at `--out`, `--report` or `--roster` is replaced under `--apply`, so a
nightly run can reuse its file names. The run prints `replaced` instead of `wrote` when it does
this. Never name a file you want to keep.

## What it checks

The demo uses the synthetic files below. The plain list has four homes. The key is a random file
made by `--make-key`.

```
$ cat plain.csv
ID,HOME_ADDR
1,412 Larkspur Lane
2,"88 N. Quillfeather Street, Apt 3"
3,1500 Heron Pier Road
4,21 Tamarack Court
$ cat points.csv
PARCEL,SITE_ADDR,CITY
P01,412 Larkspur Ln,Fairview
P02,90 Birchwood Ct,Fairview
P03,"88 North Quillfeather St Unit B, Fairview FL 33000",Fairview
P04,4120 Larkspur Ln,Fairview
P05,100 Key West Ave,Fairview
P06,21 Tamarack Ct Apt 2,Fairview
P07,,Fairview
$ python exemptguard.py --make-key secret.bin --apply
wrote secret.bin, 256 random bits. Keep it out of the repository and away from the roster.
$ python exemptguard.py --build-roster plain.csv --address-field HOME_ADDR --roster roster.txt --key-file secret.bin --apply
exemptguard: plain.csv
plain rows read: 4
roster entries: 8 (rows that repeat an address count once, and each address is stored in several spellings)

wrote roster.txt
VERDICT: roster of 8 entries. Every plain row is on it, so the plain list is not needed to screen a dataset.
$ head -6 roster.txt
exemptguard-roster 1
normalizer 3
check d82621f28abb14c9fbeed2a440ba9f3bb93ec809eb41c432b86b100ba09ed5d3
count 8
044b13bc8eee220479f0319d67e39a90300c858ed8c886d07fc04f53034c90dc
253a8fbcc1cc23948a8565f33dfaebd48784d5118d493e64cb043cff244481df
```

The hashes above come from one random key, so a run with another key prints other hashes.
Without `--apply`, the same build prints `Check only.`, says the roster was not written, and
writes nothing. The `check` line is a keyed hash of a constant. It lets the tool
tell a wrong key from a right one. The `count` line lets it tell a truncated roster from a whole
one. The roster stores no date, so keep track of when it was built.

Screen the dataset:

```
$ python exemptguard.py points.csv --roster roster.txt --key-file secret.bin --address-field SITE_ADDR
exemptguard: points.csv 7 row(s), roster roster.txt
rows checked: 6 of 7, against 8 roster entries
rows held back: 3
  dataset lines: 2, 4, 7
rows with no street line (a house number, then a word) in any named field: 1
  dataset lines: 8

VERDICT: 3 row(s) carry an address on the exempt roster. Do not publish this dataset as it stands. Publish the --out file.
$ echo $?
1
```

Three rows are on the roster. `P01` spells the suffix `Ln` where the roster says `Lane`. `P03` adds
a unit, a city and a ZIP code. `P06` adds a unit. `P04` is `4120 Larkspur Ln`: the house number
differs, so it stays. `P05` is `100 Key West Ave`: `Key` is a unit word in the Postal Service
table and also a street name, and the tool keeps it as a street name. `P07` has no street line (a
house number, then a word), so it is counted apart and not called clean. The tool prints only counts and the dataset line numbers.

Add `--out` and `--report` with `--apply` to write the copy to publish:

```
$ python exemptguard.py points.csv --roster roster.txt --key-file secret.bin --address-field SITE_ADDR --out clean.csv --report held.csv --apply
...
VERDICT: 3 row(s) carry an address on the exempt roster. Do not publish this dataset as it stands. Publish the --out file.

wrote clean.csv

wrote held.csv
$ cat held.csv
dataset_line,field
2,SITE_ADDR
4,SITE_ADDR
7,SITE_ADDR
$ cat clean.csv
PARCEL,SITE_ADDR,CITY
P02,90 Birchwood Ct,Fairview
P04,4120 Larkspur Ln,Fairview
P05,100 Key West Ave,Fairview
P07,,Fairview
$ python exemptguard.py clean.csv --roster roster.txt --key-file secret.bin --address-field SITE_ADDR
...
VERDICT: TOO LITTLE CHECKED. Only 3 of 4 row(s) had a street line in a named field. The other 1 row(s) were not compared with the roster, and --max-unchecked allows 0 percent. This is not a clean dataset. Look for a wrong column, or an address column that is empty. If those rows are meant to be blank, raise --max-unchecked.
$ echo $?
4
$ python exemptguard.py clean.csv --roster roster.txt --key-file secret.bin --address-field SITE_ADDR --max-unchecked 25
...
VERDICT: CLEAN. 3 of 4 row(s) were checked and none matched the roster.
1 row(s) had no street line to check, within the 25 percent that --max-unchecked allows. This verdict does not cover them.
$ echo $?
0
```

The run still exits 1 after it writes `clean.csv`, because the input held exempt rows. Publish
`clean.csv`, and run the tool on it once more. The copy of this demo still has the blank row
`P07`, so the second run needs `--max-unchecked 25` to exit 0. Exit 0 then means that no checked
row matched. It does not cover the row with no street line. The copy keeps
the header, every other row's cell values, and a quoted line break inside a cell. It is written
again by a CSV writer, so it is not byte for byte the input: a UTF-8 byte order mark is dropped,
CR LF line ends become LF, quotes that are not needed are removed, and blank lines are dropped.
The report names a dataset line and a field. It never holds an address.

### How an address is folded

Both sides go through one function. It does these steps in order.

1. Fold accents, full-width digits and no-break spaces to plain ASCII, and upper-case the text.
   An apostrophe, a right single quotation mark and an acute accent (`O'Brien`, `O<U+2019>Brien`
   and `O<U+00B4>Brien`) are deleted, so each gives `OBRIEN`.
2. Drop everything after the first comma.
3. Treat every run of other characters as a word break. `12-14` becomes two words.
4. Fold each word through a fixed table. A street suffix goes to its Postal Service standard
   abbreviation (`ROAD` to `RD`, `BOULEVARD` to `BLVD`), using every variant that Appendix C1 of
   Publication 28 lists. A direction goes to its letters (`NORTHEAST` to `NE`). A unit word goes to
   its approved abbreviation (`SUITE` to `STE`). `FIRST` to `TENTH` go to `1` to `10`, and
   `SAINT` goes to `ST`. The ordinal and `SAINT` rows are this tool's own and are not from
   Publication 28. The self-test pins the whole table with a hash, folds every variant in it, and
   cuts every designator, so a deleted row fails the self-test.
5. Drop the ordinal ending from every word after the first (`5TH` to `5`, `22ND` to `22`), so
   `NW 5th St` and `NW 5 St` are one street. The house number is left alone.
6. Remove leading zeros from the house number.
7. Cut off the unit and everything after it.

A unit is a pound sign, or one of the approved designators in Appendix C2 (`APT`, `STE`, `UNIT`,
`LOT` and the rest). A designator is a unit only from the third word on, and only when a number,
a single letter or a pound sign follows it, or nothing does. Appendix C2 lists `KEY`, `PIER`,
`STOP` and `SIDE` as designators, and they are also common street names. So `100 Key West Ave`,
`9 N Pier St` and `1500 Heron Pier Road` stay whole.

```
$ python -c "from exemptguard import normalize as n; print(' '.join(n('100 Key West Ave')))"
100 KY W AVE
$ python -c "from exemptguard import normalize as n; print(' '.join(n('88 North Quillfeather St Unit B, Fairview FL 33000')))"
88 N QUILLFEATHER ST
```

A row counts as a street line only when it starts with a house number and a later word holds a
letter. `Main St`, `PO Box 5` and `NO SITUS ADDRESS` have no house number. A parcel number
(`2234-001-000`), a ZIP+4 and a phone number have no letter. None of them is checked.

Each address in the plain list is stored in several spellings, because the two sides do not always
write the same part of an address. The tool cuts the plain line after its first street suffix and
keeps any directions and further suffixes that follow (`12 OAK ST NE`). It then hashes every run
of the cut line that ends at a suffix or a direction, and the line before its first suffix. For
`412 Larkspur Lane` that is `412 LARKSPUR LN` and `412 LARKSPUR`. For `12 Oak Street NE` it is
`12 OAK`, `12 OAK ST` and `12 OAK ST NE`. So a dataset line with no post-direction, or with no
street type, still matches. A city or ZIP code written after the suffix with no comma
(`412 Larkspur Ln Lake City FL`) is cut off, and the street alone is always one of the spellings.
That matters when the city starts with a suffix or a direction word (`Lake City`, `St Augustine`,
`North Port`, `Port Orange`): those words are kept as part of the cut, and the shorter spellings
still hold the street. The build counts plain lines that went on after the suffix.

A house number range in the plain list (`410-414 Larkspur Ln`) is hashed as written and once per
number, up to `MAX_RANGE` (200) numbers wide. A dataset range is expanded the same way: each number
in `410-414` is tried. Two digit words before the street name are read as a range even when the
second is a numbered street, so `10 5th St` also tries `5 ST` to `10 ST`. That only holds more
rows. A house number of more than `MAX_NUMBER_DIGITS` (18) digits is never read as a range end.

The dataset side is tried one prefix at a time, from two words up to ten. This finds
`412 LARKSPUR LN` at the front of `412 LARKSPUR LN FAIRVIEW 33000` when a city and ZIP code follow
with no comma between them. It matches whole words, never text, so `4120 Larkspur Ln` and
`412 Larkspurs Ln` do not match `412 Larkspur Ln`. A longer street line that begins with a roster
line is held, for example `412 Larkspur Ln Ext`. The shorter spellings also hold a row on another
street type with the same number and name (`412 Larkspur Ct`). Holding too much is the safe error.

The hash is HMAC-SHA256 of the folded words, with the key from `--key-file`. The tool compares the
stored key check with `hmac.compare_digest`, as the Python documentation advises for a digest.

## Refusals

**A key that does not open the roster.** Checked before any row is read. Nothing is screened.

```
$ python exemptguard.py points.csv --roster roster.txt --key-file wrong.bin --address-field SITE_ADDR
REFUSED   the key does not open this roster. A wrong key matches nothing and would read as a clean run.

VERDICT: REFUSED
$ echo $?
3
```

The same exit 3 covers a roster with a line cut off or added, a header that is damaged, a line that
is not a hash, an empty roster, a roster built by another version of the folding table, and a key
file under 16 bytes. A copy of the roster that went through Windows line endings still reads. A
roster built by an earlier version of this tool (normalizer 2) is refused. Rebuild it from the
plain list.

**A dataset where too little could be checked.** A row is checked only when a named column holds
a street line, as described above. When more rows than `--max-unchecked` allows are not checked,
the run exits 4 and writes no copy, because a copy would look like a clean one. The default is
`0`, so a single row with no street line, such as a vacant parcel or a home written with its unit
first (`Unit 2 412 Larkspur Ln`), stops a run that found no match. A scheduled job that expects
blank addresses sets the share it accepts, for example `--max-unchecked 5`. When rows were read and
none was checked, the run exits 4 whatever the setting. That is a wrong column, or an empty one.
The limit is exact: with `--max-unchecked 50`, 50 unchecked rows in 100 pass and 51 do not. If any
row matched, the run exits 1 whatever the share, and the limit is not applied. Here `blank.csv` has
the header `PARCEL,SITE_ADDR` and two rows, one with an empty address and one with the word
`Vacant`.

```
$ python exemptguard.py blank.csv --roster roster.txt --key-file secret.bin --address-field SITE_ADDR --out copy.csv --apply
exemptguard: blank.csv 2 row(s), roster roster.txt
rows checked: 0 of 2, against 8 roster entries
rows held back: 0
rows with no street line (a house number, then a word) in any named field: 2
  dataset lines: 2, 3

VERDICT: NOTHING CHECKED. No row had a street line in a named field, so no row was compared with the roster. This is not a clean dataset. Look for a wrong column, or an address column that is empty.

Nothing written, because too little was checked and a copy would look like a clean one.
$ echo $?
4
```

A build that finds no usable address in the plain list also exits 4 and leaves the existing roster
alone, and so does a header-only plain list. A build where more plain rows than `--max-unchecked`
allows have no street line (`VERDICT: TOO LITTLE BUILT`) exits 4 and writes nothing, because a
roster made from a few rows would let the rest of the list through. When you allow the loss, the
build exits 0, lists the plain lines it left out, and says that those rows are not on the roster
and the plain list must be kept for them.

**A column that is wrong.** `--address-field ADDR` against a file without that column exits 64.
The error gives the number of columns and never prints the names in the file, because a file with
no header row makes its first data row the header, and a key file passed as the dataset is one
cell of key text. It offers a name only when a name in the file is one or two edits from the one
you typed and the one you typed is at least five characters. A column name that appears twice in the
header is refused too, because one of the two would be read without a word.

```
$ python exemptguard.py points.csv --roster roster.txt --key-file secret.bin --address-field ADDR
error: column 'ADDR' is not in the CSV. It has 3 column(s), and their names are not printed. Does the file have a header row?
$ echo $?
64
$ python exemptguard.py near.csv --roster roster.txt --key-file secret.bin --address-field SITE_ADDR
error: column 'SITE_ADDR' is not in the CSV. It has 2 column(s), and their names are not printed. Did you mean 'SITE_ADR'? Does the file have a header row?
```

A column that exists but holds no street lines, such as a parcel number, is exit 4 (see above).

**A file that is not UTF-8, or is empty.** Exit 2. A lossy read would turn an accented street name
into something that no longer matches the roster, and a privacy check must fail closed. In Excel,
save the file as "CSV UTF-8 (Comma delimited)". The error gives the byte offset of the first bad
byte and not the byte. A zero-byte file exits 2 and says it is empty.

**A key that already exists.** `--make-key` opens the file with exclusive create. A second run
exits 2 and leaves the old key alone, because a new key would orphan the roster built with it.

```
$ python exemptguard.py --make-key secret.bin --apply
error: secret.bin already exists. A new key would orphan the roster built with the old one, so it is not replaced.
$ echo $?
2
```

## Exit codes

| Code | Meaning |
|---|---|
| 0 | No row matched, and no more rows than `--max-unchecked` allows had no street line to check (the default allows none). A dataset with a header and no rows has nothing to check and also exits 0. |
| 1 | At least one row matched. Publish the `--out` file, not the input. |
| 2 | A file could not be read or written, is empty, or is not UTF-8, or `--make-key` would replace a file. |
| 3 | Refused. The roster is damaged, the key does not open it, or the key is too short. |
| 4 | Too little was checked, or too little was built: more rows than `--max-unchecked` allows had no street line to compare. |
| 64 | Usage error, including a column that is not in the CSV, an unknown or abbreviated flag, an output path that is an input, and two inputs that are one file. |
| 70 | An unexpected crash. This is a fault in the tool and not a finding. The traceback is on stderr. |

Exit 1 is not exit 3. A scheduled job that files "a row matched" must not file "the key is wrong"
the same way. Exit 4 is not exit 0 for the same reason: "I checked and found nothing" and "I could
not check" are different facts. The `--self-test` footer also exits 1 when an assertion fails,
which is the code for "a row matched", so read a self-test exit apart from a screening exit.

## Limits

- It decides nothing about who is exempt. The records custodian does that, and the roster is only
  as good as the list it was built from. The statute is cited for context: Florida Statutes
  s. 119.071(4)(d)2. lists groups whose home addresses are exempt from public inspection, for
  example active or former sworn law enforcement personnel (2.a.) and current or former justices
  and judges (2.e.). Whether the exemption reaches a particular published dataset is a question for counsel.
- It matches the street line only. A city, a state and a ZIP code are ignored, so `412 Larkspur
  Ln` in another town is held too. That is the safe error.
- It does not match fuzzily. A misspelled street (`Larkspar`) in either file is missed. Fix the
  spelling, or build the roster from the spelling the dataset uses. A table of street suffixes
  cannot repair a typing mistake.
- A directional in front of the street name that only one side has is a miss. A roster line
  `12 N Oak St` does not find a dataset line `12 Oak St`, and the reverse. A directional after the
  street is not a miss in either direction. Name every address column, pre-direction included.
  A roster entry of more than ten folded words can never match, because a dataset address is tried
  up to ten words.
- A dataset that omits the street type still matches, because the roster keeps the line before
  its suffix. A roster line that is missing its suffix (`88 N Quillfeather`) is matched only by
  a dataset line that is missing it too, or that begins with those words.
- A roster entry of two words, such as `12 Broadway`, matches every dataset address that starts
  with the same two words. The build report counts them. The two-word spelling before the suffix
  (`412 LARKSPUR`) does the same, and is why `412 Larkspur Ct` is held.
- Only the first address in a cell is tried. `9 Elm St; 412 Larkspur Ln` and
  `9 Elm St & 412 Larkspur Ln` match only the first. A cell that starts with its unit
  (`Apt 4, 412 Larkspur Ln`) has no street line, so the row is counted as unchecked.
- A house number written with a hyphenated unit (`412-5 Larkspur Ln`) is read as a range from 5 to
  412. That is wider than `MAX_RANGE`, so only the written form is tried, and it does not match a
  roster line `412 Larkspur Ln`. A range that is narrow enough (`410-414 Larkspur Ln`, written with
  an ASCII hyphen) is expanded on both sides, so a roster home written as a range holds a dataset
  row for any number in it, and a dataset range is held if any number in it is on the roster. A
  range written with an en dash is not a range (see below).
- The suffix table holds the variants in Appendix C1 of Publication 28. A spelling that is not in
  the Appendix passes through unchanged. A designator written with no space before its number
  (`APT4`) is split. A designator that is followed by a word that is not a range, such as `REAR`
  before `APT 2`, cuts only at the later one.
- A header-only dataset has nothing to check and exits 0 with `CLEAN. 0 of 0`, so a scheduled job
  cannot tell an empty export from a clean one without reading the text.
- With `--max-unchecked` above 0, the run exits 0 with `CLEAN` although some rows were not read.
  The verdict says it does not cover them, but a job that reads only the exit code does not see
  them. Read "exit 0" as "no checked row matched", not as "no exempt address is in the file".
- When some rows match and more rows than `--max-unchecked` allows had no street line, the run
  exits 1 and the verdict says to publish the `--out` file. The too-little check (exit 4) is
  skipped when a row matched, so the verdict does not flag the unchecked rows. Screening the copy
  exits 4 and shows them.
- A rerun that exits 3 or 4 does not touch the `--out` file of an earlier run. A job that ignores
  the exit code could publish that stale copy. Delete the old output before each run.
- Route aliases and spelling variants are not folded. `STATE ROAD 40` and `SR 40`, `COUNTY ROAD`
  and `CR`, `U.S. Highway 441` and `US 441`, and `DR` and `DOCTOR` do not match each other.
  `Mc Intosh` does not match `McIntosh`. `MEADOW` and `MEADOWS` are two Publication 28
  suffixes (`MDW` and `MDWS`) and do not match each other. Spelled-out ordinals above `TENTH`
  are not folded to their numbers. Put every spelling the dataset uses into the roster.
- A house number with a letter or a fraction (`412A Larkspur Ln`, `412-A Larkspur Ln`,
  `412 1/2 Larkspur Ln`) does not match a roster line `412 Larkspur Ln`. A thousands separator
  (`1,412 Larkspur Ln`) cuts the line at the comma, so the row is counted as having no street
  line. Build the roster from the spelling the dataset uses.
- A character that Unicode does not split into ASCII (a zero-width space, an en dash in
  `410-414`, an Arabic-Indic digit, an o with a slash) is deleted, not read as a word break. So
  `412<ZWSP>Larkspur Ln` and `410<en dash>414 Larkspur Ln` each become one word and do not match.
- `N. E.` with a space between the letters is read as two directions, `N` and `E`, and does not
  match `NE`.
- A street name that holds a unit word followed by a number or one letter (`Side 2nd`,
  `Pier A`) is cut at that word on both sides. The roster entry is then shorter than the street
  and may match other streets with the same house number. That is the safe direction.
- A house number of thousands of digits, in a cell or in a plain list, is not read as a range and
  is looked up as written. It never raises the integer conversion error that Python 3.11 and later
  give for a run of more than 4300 digits.
- The roster is not signed. The `check` line proves the key and the `count` line proves the
  length. A roster with entries swapped or removed and the count line edited to match is
  accepted.
- A key file that gained a byte order mark or trailing spaces from an editor holds a different
  key and is refused with exit 3, as a key that does not open the roster. Keep the key file byte
  for byte as `--make-key` wrote it.
- The key is read only from a file. There is no environment variable or standard input route,
  so the key is protected by file permissions alone.
- Use only a key from `--make-key`. The tool accepts any text of 16 bytes or more, and the `check`
  line lets anyone who holds the roster test guesses at the key offline. A key that a person typed
  can be guessed that way.
- The `.gitignore` keeps `*.bin`, `*.key`, `key*.txt`, `*secret*` and `*roster*` out of the
  repository. A key or roster saved under another name is not ignored. Check `git status`.
- A write to `--out` and then `--report` is not atomic. On Windows, a path written as an 8.3
  short name or an alternate data stream can pass the same-file check, but only for a file that
  does not exist yet.
- A Ctrl-C or a closed output pipe is not mapped to this tool's exit codes in every case.
  `KeyboardInterrupt` is not caught, so the exit code then comes from the interpreter.
- Only the named columns are read. A home can sit in a second address column, a free-text note,
  or the geometry. A point layer's coordinates are the address, so the held row is removed whole
  and the coordinates go with it. A rooftop point whose address cell is blank is counted as
  unchecked and stays in the copy. Name every address column, and screen every layer you publish,
  including parcels, permits and call logs. One run reads one dataset.
- A comma inside a column name cannot be used, because a comma joins column names in
  `--address-field`.
- The key is the whole defence. With the roster alone, an attacker cannot read it back, as the
  experiment above shows. With the roster and the key, an attacker who hashes the public address
  list recovers the exempt members, and the self-test shows that too. Keep the key out of the
  repository, out of the folder that holds the dataset, and out of email. `--key-file` exists so
  that the key never appears on a command line or in a shell history. A 256-bit random key is not
  guessable. A key that a person types is. The tool refuses a key under 16 bytes and nothing more.
- `--make-key` creates the file with mode 0600 where the system has modes. Windows ignores the
  mode, and the self-test does not check it there. The clean copy, the report and the roster are
  created with the default mode of the process, which is world-readable on many systems. Set the
  file permissions yourself, and keep the report as private as the roster and the key.
- The report and the printed line lists give the line number of every held row. Anyone who also
  holds the unredacted export can read the exempt rows from those numbers.
- A removed row is itself a signal. A reader who compares the published copy with another public
  list of the same parcels sees which parcels were withheld, so removing a row tells that reader
  who is exempt.
- The roster reveals how many addresses are on it, within a small factor, because each address is
  stored in a few spellings. It stores no names and no dates.
- Output is written in place, not through a temporary file. A failed write can leave a partial
  file, and the exit code is 2. With both `--out` and `--report` named, `--out` can be written and
  then `--report` can fail.
- It reads the whole CSV into memory. No script in this repository measures how long a run takes
  on a large file, so this README states no timing.
- US street addresses only. A rural route, a post office box and an address in another country
  are folded as plain words and are not understood.
- UTF-8 CSV only, with a header row. A row with extra cells is kept as it is, and a short row has
  its missing cells read as blank. A blank line is skipped and does not shift the reported line
  numbers, and neither does a quoted cell that holds a line break.
- Nothing is written without `--apply`, and a refused run or an unchecked run writes nothing.
- The tool opens no socket and imports no network module. The self-test proves this by reading
  its own imports. There is no network path to run against a stub server.
- It prints no address, hash or key. The self-test greps every printed line, the roster, the
  report and the clean copy for the synthetic addresses, the hashes and the keys. The tool never
  prints a column name from a file, except a name one or two edits from a name you typed. The one
  text from a roster that a refusal can print is a version number made of digits.

## Sources

- USPS Publication 28, Postal Addressing Standards.
  [Appendix C1, street suffix abbreviations](https://pe.usps.com/text/pub28/28apc_002.htm) and
  [Appendix C2, secondary unit designators](https://pe.usps.com/text/pub28/28apc_003.htm). Section
  233 on [directionals](https://pe.usps.com/text/pub28/28c2_014.htm) and section 213 on
  [secondary address units and the pound sign](https://pe.usps.com/text/pub28/28c2_003.htm).
  Appendix C2 notes which designators need no range number.
- Python documentation: [hmac](https://docs.python.org/3.12/library/hmac.html) (`digestmod` is
  required, `compare_digest` for digests),
  [argparse](https://docs.python.org/3.12/library/argparse.html) (`allow_abbrev`) and
  [integer string conversion length limitation](https://docs.python.org/3.12/library/stdtypes.html#int-max-str-digits)
  (the 4300 digit limit that `MAX_NUMBER_DIGITS` stays under).
- [Florida Statutes s. 119.071](https://www.leg.state.fl.us/statutes/index.cfm?App_mode=Display_Statute&URL=0100-0199/0119/Sections/0119.071.html),
  subsection (4)(d)2.
- Florida Statutes ss. 741.401 to 741.409, the Address Confidentiality Program, as described by
  the Florida Attorney General's program pages and the statute text indexed at
  [flsenate.gov](https://www.flsenate.gov/Laws/Statutes/2011/0741.401).

## Contributing

Open an issue or pull request on GitHub.

## Author

Built by [Asir Khan](https://www.linkedin.com/in/asir-khan-310317264/).

## License

MIT.

## Related

Other single-file tools in this portfolio that pair with this one:

- [idreuse](https://github.com/uhsear/idreuse) - diff two layers that share an ID and measure how
  far apart each pair is, refusing a status column that holds one value. The same habit of
  refusing to call a run clean when it did not compare what it claimed.
- [nalmatch](https://github.com/uhsear/nalmatch) - reconcile a parcel layer against the tax roll
  and name every parcel that exists on one side only.
- [geocodesift](https://github.com/uhsear/geocodesift) - audit a geocoded batch instead of
  believing its match rate. Run it on the batch you are about to screen.
- [roadmiles](https://github.com/uhsear/roadmiles) - certify centerline mileage and refuse to
  count the same road twice, the same refusal to certify a number nobody checked.
