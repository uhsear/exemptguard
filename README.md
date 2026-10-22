# exemptguard

Hold back every row of a dataset whose street address is on a hashed roster of exempt addresses,
before the dataset is published. The roster holds keyed hashes and no address text, so the people
who run the check never see the list. Refuses a roster that the key does not open, refuses a
dataset it could not check, and writes a clean copy only under `--apply`.

Some people have a home address that the law keeps out of public records: certain officers,
judges and prosecutors, for example. The records office knows who they are. The GIS group does
not, and the list cannot go to the GIS group, because the list is the secret. So the check does
not happen. An analyst exports address points for the open data site. The file holds a few
hundred thousand rows, and a few of them are homes that the law says to withhold. Nobody looks,
because nobody can look. The file goes up, search engines index it, and the first anyone hears
of it is a phone call.

The defence everybody reaches for first is a hashed list. Hash every exempt address, send the
hashes, and compare. It looks safe, and it is not. Every address in a county is public, so an
attacker hashes every address and reads the roster back. On this workstation, one plain SHA-256
search over 1,000,000 candidate addresses found the planted address in 1.44 seconds. On an Ubuntu
server it took 0.72 seconds. The same search against a keyed hash (HMAC-SHA256) of the same
address found nothing, because the key was not known. The key is what makes the roster safe to
hand over. This tool uses the key and keeps the key out of the roster.

Hashing raw text fails the other way. The roster says `412 Larkspur Lane`. The dataset says
`412 Larkspur Ln`. The two hashes differ, and every row passes. In the demo below, a keyed hash
of the raw text, even after upper-casing and trimming it, matched 0 of 7 dataset rows, and three
of them are on the roster. This tool
folds both sides to one spelling first: case, punctuation, `Lane` and `Ln`, `North` and `N`,
`Apt 4` and `#4`, and a trailing city and ZIP code.

The quietest failure is a check that ran and compared nothing. The wrong key matches no row. A
roster cut short in transit matches only part of the list. An address column with the wrong name,
or empty, gives nothing to compare. Each of them reads as a clean dataset to a scheduled job.
This tool refuses the first two with exit 3 and the last with exit 4.

```
$ python exemptguard.py --self-test
exemptguard self-test: temporary files only, no network, no real credentials
--------------------------------------------------------------------
PASS  case, punctuation and the suffix spellings fold to one street line
...
PASS  every unit spelling is cut off, including #4 and APT4  <-- pinned defect
PASS  KEY, PIER, SIDE and STOP in a street name are not read as a unit  <-- pinned defect
...
PASS  the hash depends on the key, so it is not a plain SHA-256 that anyone could compute from the public address list  <-- pinned defect
...
PASS  a wrong key is refused, because it would match nothing and read as clean  <-- pinned defect
PASS  a roster with a line cut off is refused, not half-applied  <-- pinned defect
...
PASS  a street line followed by a city and a ZIP code with no comma is still found  <-- pinned defect
PASS  a different house number or street is not held: the match is on whole words, not on text  <-- pinned defect
...
PASS  rows read and none checked is exit 4, not a clean run  <-- pinned defect
...
PASS  the roster file holds no address text, only hashes  <-- pinned defect
PASS  the dataset screens at exit 1 with the lines of the 4 rows the roster holds, counted past a blank line and a quoted line break  <-- pinned defect
...
PASS  a prefix of a long flag, such as --ap for --apply, is refused with exit 64 and not read as the flag  <-- pinned defect
...
PASS  no exempt address appears in anything printed, in any run  <-- pinned defect
...
PASS  the footer reports failures by count and by name, and exits 1  <-- pinned defect
PASS  importing the module prints nothing and exposes the core
--------------------------------------------------------------------
126 assertions, 0 failed
```

The full run prints all 126 assertions. Each `...` line above is where this block is cut.

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
screens a dataset against a hashed address roster, on the day it was run (2026-10-22). That shows
only that the search found nothing.

## Requirements

Python 3.9 or newer and nothing else. No `arcpy`, no third-party package, no network, no
database. The dataset and the plain list are CSVs, which every layer and table can be exported as.

The self-test prints the same 126 assertions on Windows (Python 3.13.2), on Python 3.9.25 and on
Ubuntu (Python 3.12.3). All three outputs are identical line for line.
`coverage run --branch exemptguard.py --self-test` reports 100 percent of 758 statements and
172 branches, so no line is left unreached offline.

```
git clone https://github.com/uhsear/exemptguard.git
```

## Usage

Three steps. The first two are done by the person who holds the plain list. The third is done by
the GIS group, and needs the roster and the key but never the plain list.

```
python exemptguard.py --make-key secret.bin --apply
python exemptguard.py --build-roster plain.csv --address-field HOME_ADDR --roster roster.txt --key-file secret.bin --apply
python exemptguard.py points.csv --roster roster.txt --key-file secret.bin --address-field SITE_ADDR
python exemptguard.py points.csv --roster roster.txt --key-file secret.bin --address-field SITE_ADDR --out clean.csv --report held.csv --apply
python exemptguard.py points.csv --roster roster.txt --key-file secret.bin --address-field ADDNUM,STNAME,STTYPE
python exemptguard.py --self-test
```

Send the roster to the GIS group. Send the key by another route. A roster and its key together
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
| `--sample` | `10` | How many line numbers to list under each heading. `0` lists none. |
| `--apply` | off | Actually write. Without it nothing is written. |
| `--self-test` | off | Run the assertions and exit. Other flags are ignored. |

Every flag must be spelled in full. The parser sets `allow_abbrev=False`, so `--ap` is refused
with exit 64 instead of being read as `--apply`. `--appl`, `--app`, `--rost`, `--key`, `--addr`,
`--rep`, `--sel`, `--make`, `--build`, `--sam` and `--ou` are refused the same way, and a refused
run writes nothing.

`--out` and `--report` must name new files. A path that is also the dataset, the roster or the key
is refused with exit 64, on a dry run too. Without that check `--apply` would replace the input
with its own clean copy.

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
roster entries: 4 (rows that repeat an address count once)

wrote roster.txt
VERDICT: roster of 4 entries. The plain list is not needed to screen a dataset.
$ head -6 roster.txt
exemptguard-roster 1
normalizer 1
check e349fce5cd3755e44b3a297427e8ac9a3cc899d955d32dc5089cba9be6445110
count 4
41d90db4d000431bf315d7016dec73c0e02b524e5dcf660483f4f3d5020979a4
56b03dc2a031d13cee602bf34f3bc3bb8723b2b609cec72ceb65a55d09e90452
```

Without `--apply`, the same build prints `Check only.`, says the roster was not written, and
writes nothing. The `check` line is a keyed hash of a constant. It lets the tool
tell a wrong key from a right one. The `count` line lets it tell a truncated roster from a whole
one. The roster stores no date, so keep track of when it was built.

Screen the dataset:

```
$ python exemptguard.py points.csv --roster roster.txt --key-file secret.bin --address-field SITE_ADDR
exemptguard: points.csv 7 row(s), roster roster.txt
rows checked: 6 of 7, against 4 roster entries
rows held back: 3
  dataset lines: 2, 4, 7
rows with no address of two or more words in any named field: 1
  dataset lines: 8

VERDICT: 3 row(s) carry an address on the exempt roster. Do not publish this dataset as it stands. Publish the --out file.
$ echo $?
1
```

Three rows are on the roster. `P01` spells the suffix `Ln` where the roster says `Lane`. `P03` adds
a unit, a city and a ZIP code. `P06` adds a unit. `P04` is `4120 Larkspur Ln`: the house number
differs, so it stays. `P05` is `100 Key West Ave`: `Key` is a unit word in the Postal Service
table and also a street name, and the tool keeps it as a street name. `P07` has no address, so it
is counted apart and not called clean. The tool prints only counts and the dataset line numbers.

Add `--out` and `--report` with `--apply` to write the copy to publish:

```
$ python exemptguard.py points.csv --roster roster.txt --key-file secret.bin --address-field SITE_ADDR --out clean.csv --report held.csv --apply
...
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
VERDICT: CLEAN. 3 of 4 row(s) were checked and none matched the roster.
$ echo $?
0
```

The run still exits 1 after it writes `clean.csv`, because the input held exempt rows. Publish
`clean.csv`, and run the tool on it once more. Exit 0 on the copy is the proof. The copy keeps
the header, every other row exactly as it came, and a quoted line break inside a cell. The report
names a dataset line and a field. It never holds an address.

### How an address is folded

Both sides go through one function. It does these steps in order.

1. Fold accents, full-width digits and no-break spaces to plain ASCII, and upper-case the text.
2. Drop everything after the first comma.
3. Treat every run of other characters as a word break. `12-14` becomes two words.
4. Fold each word through a fixed table. A street suffix goes to its Postal Service standard
   abbreviation (`ROAD` to `RD`, `BOULEVARD` to `BLVD`), using every variant that Appendix C1 of
   Publication 28 lists. A direction goes to its letters (`NORTHEAST` to `NE`). A unit word goes to
   its approved abbreviation (`SUITE` to `STE`). `FIFTH` goes to `5TH` and `SAINT` goes to `ST`.
   The ordinal and `SAINT` rows are this tool's own and are not from Publication 28.
5. Remove leading zeros from the house number.
6. Cut off the unit and everything after it.

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

The dataset side is then tried one prefix at a time, from two words up to ten. This finds
`412 LARKSPUR LN` at the front of `412 LARKSPUR LN FAIRVIEW 33000` when a city and ZIP code follow
with no comma between them. It matches whole words, never text, so `4120 Larkspur Ln` and
`412 Larkspurs Ln` do not match `412 Larkspur Ln`. A longer street line that begins with a roster
line is held, for example `412 Larkspur Ln Ext`. Holding too much is the safe error.

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
file under 16 bytes. A copy of the roster that went through Windows line endings still reads.

**A dataset where nothing could be checked.** Rows were read, and no row had an address of two or
more words in a named column. That is a wrong column, or an empty one. Exit 4, and no copy is
written, because a copy would look like a clean one. Here `blank.csv` has the header
`PARCEL,SITE_ADDR` and two rows, one with an empty address and one with the word `Vacant`.

```
$ python exemptguard.py blank.csv --roster roster.txt --key-file secret.bin --address-field SITE_ADDR --out copy.csv --apply
exemptguard: blank.csv 2 row(s), roster roster.txt
rows checked: 0 of 2, against 4 roster entries
rows held back: 0
rows with no address of two or more words in any named field: 2
  dataset lines: 2, 3

VERDICT: NOTHING CHECKED. No row had an address of two or more words in a named field, so no row was compared with the roster. This is not a clean dataset. Look for a wrong column, or an address column that is empty.

Nothing written, because nothing was checked and a copy would look like a clean one.
$ echo $?
4
```

A build that finds no usable address in the plain list also exits 4 and leaves the existing roster
alone.

**A column that is wrong.** `--address-field ADDR` against a file without that column exits 64 and
lists the columns the file has. A column name that appears twice in the header is refused too,
because one of the two would be read without a word.

```
$ python exemptguard.py points.csv --roster roster.txt --key-file secret.bin --address-field ADDR
error: column 'ADDR' is not in the CSV. It has: PARCEL, SITE_ADDR, CITY
$ echo $?
64
```

**A file that is not UTF-8.** Exit 2. A lossy read would turn an accented street name into
something that no longer matches the roster, and a privacy check must fail closed. In Excel, save
the file as "CSV UTF-8 (Comma delimited)".

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
| 0 | At least one row was checked and none matched the roster. |
| 1 | At least one row matched. Publish the `--out` file, not the input. |
| 2 | A file could not be read or written, a file is not UTF-8, or `--make-key` would replace a file. |
| 3 | Refused. The roster is damaged, the key does not open it, or the key is too short. |
| 4 | Nothing was checked, or nothing was built. No row had an address to compare. |
| 64 | Usage error, including a column that is not in the CSV, an unknown or abbreviated flag, and an output path that is an input. |
| 70 | An unexpected crash. This is a fault in the tool and not a finding. The traceback is on stderr. |

Exit 1 is not exit 3. A scheduled job that files "a row matched" must not file "the key is wrong"
the same way. Exit 4 is not exit 0 for the same reason: "I checked and found nothing" and "I could
not check" are different facts.

## Limits

- It decides nothing about who is exempt. The records custodian does that, and the roster is only
  as good as the list it was built from. The statute is cited for context: Florida Statutes
  s. 119.071(4)(d)2. lists groups whose home addresses are exempt from public inspection, for
  example active or former sworn law enforcement personnel (2.a.) and current or former judges
  (2.e.). Whether the exemption reaches a particular published dataset is a question for counsel.
- It matches the street line only. A city, a state and a ZIP code are ignored, so `412 Larkspur
  Ln` in another town is held too. That is the safe error.
- It does not match fuzzily. A misspelled street (`Larkspar`) in either file is missed. Fix the
  spelling, or build the roster from the spelling the dataset uses. A table of street suffixes
  cannot repair a typing mistake.
- The match runs one way. The dataset side is tried by prefix, and the roster side is whole. A
  roster line `12 Oak St NE` does not find a dataset line `12 Oak St`, but a roster line
  `12 Oak St` does find `12 Oak St NE`. Put the shortest form of each address in the roster.
- A roster entry of two words, such as `12 Broadway`, matches every dataset address that starts
  with the same two words. The build report counts them. A roster line that is missing its street
  suffix, `12 Oak`, does the same.
- The suffix table holds the variants in Appendix C1 of Publication 28. A spelling that is not in
  the Appendix passes through unchanged. A designator written with no space before its number
  (`APT4`) is split. A designator that is followed by a word that is not a range, such as `REAR`
  before `APT 2`, cuts only at the later one.
- Only the named columns are read. A home can sit in a second address column, a free-text note,
  or the geometry. A point layer's coordinates are the address, so the held row is removed whole
  and the coordinates go with it. A rooftop point whose address cell is blank is counted as
  unchecked and stays in the copy. Name every address column, and screen every layer you publish,
  including parcels, permits and call logs. One run reads one dataset.
- A comma inside a column name cannot be used, because a comma joins column names in
  `--address-field`.
- The key is the whole defence. With the roster alone, an attacker cannot read it back, as the
  experiment above shows. With the roster and the key, an attacker who hashes the public address
  list recovers the exempt members. Keep the key out of the repository, out of the folder that
  holds the dataset, and out of email. `--key-file` exists so that the key never appears on a
  command line or in a shell history. A 256-bit random key is not guessable. A key that a person
  types is. The tool refuses a key under 16 bytes and nothing more.
- `--make-key` creates the file with mode 0600 where the system has modes. Windows ignores the
  mode, and the self-test does not check it there. Set the file permissions yourself.
- The roster reveals how many addresses are on it. It stores no names and no dates.
- Output is written in place, not through a temporary file. A failed write can leave a partial
  file, and the exit code is 2. With both `--out` and `--report` named, `--out` can be written and
  then `--report` can fail.
- It reads the whole CSV into memory. One run over 200,000 synthetic rows against a roster of
  about 3,000 entries took 2.98 seconds on a Windows workstation and 1.77 seconds on an Ubuntu
  server. Those figures come from one workstation and one server.
- US street addresses only. A rural route, a post office box and an address in another country
  are folded as plain words and are not understood.
- UTF-8 CSV only, with a header row. A row with extra cells is kept as it is, and a short row has
  its missing cells read as blank. A blank line is skipped and does not shift the reported line
  numbers, and neither does a quoted cell that holds a line break.
- Nothing is written without `--apply`, and a refused run or an unchecked run writes nothing.
- The tool opens no socket and imports no network module. The self-test proves this by reading
  its own imports. There is no network path to run against a stub server.
- It prints no address, hash or key. The self-test greps every printed line, the roster, the
  report and the clean copy for the synthetic addresses, the hashes and the keys.

## Sources

- USPS Publication 28, Postal Addressing Standards.
  [Appendix C1, street suffix abbreviations](https://pe.usps.com/text/pub28/28apc_002.htm) and
  [Appendix C2, secondary unit designators](https://pe.usps.com/text/pub28/28apc_003.htm). Section
  233 on [directionals](https://pe.usps.com/text/pub28/28c2_014.htm) and section 213 on
  [secondary address units and the pound sign](https://pe.usps.com/text/pub28/28c2_003.htm).
  Appendix C2 notes which designators need no range number.
- Python documentation: [hmac](https://docs.python.org/3.12/library/hmac.html) (`digestmod` is
  required, `compare_digest` for digests) and
  [argparse](https://docs.python.org/3.12/library/argparse.html) (`allow_abbrev`).
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

- [idreuse](https://github.com/uhsear/idreuse) - refuse a join on an ID that two layers use for
  different objects. The same habit of refusing to call a run clean when it compared nothing.
- [nalmatch](https://github.com/uhsear/nalmatch) - reconcile two tables on an identifier and
  refuse a rule that would merge two records into one key. Use it when the dataset spells an
  address differently from anything this tool folds.
- [geocodesift](https://github.com/uhsear/geocodesift) - find the records stacked on one
  coordinate in a geocoded batch. A stack of addresses on one point is where a protected home
  hides in a large building.
- [roadmiles](https://github.com/uhsear/roadmiles) - the same refusal to certify a number nobody
  checked.
