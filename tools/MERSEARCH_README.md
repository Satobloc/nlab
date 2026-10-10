# nLab Mersearch (standalone)

**Scope:** This is a separate, read-only, repository-local search tool for
[Satobloc/nlab](https://github.com/Satobloc/nlab). It requires no other
repository, GitHub connector, shared index, remote search bridge, network
connection, Rails runtime, or running wiki database.

**Important:** This checkout contains the **nLab wiki software**, not the
mathematical wiki's page-content database. Mersearch indexes the source and
documentation present in this checkout. To search legitimately acquired wiki
article exports, put them in a non-excluded directory inside this repository.
Do not commit private exports or database credentials to this public repository.

## Getting started

Python 3.10+; no additional dependencies for ordinary text searching.

~~~bash
python3 tools/mersearch.py --capabilities
python3 tools/mersearch.py --examples
python3 tools/mersearch.py --coverage
python3 tools/mersearch.py --query "category"
python3 tools/mersearch.py --expr '"functor" NEAR/12 "category"'
python3 tools/mersearch.py --expr '(revision OR author) AND ext:rb'
python3 tools/mersearch.py --scope script/src --query renderer
~~~

The default result directory is `.mersearch/results/`. Results are written in
four formats: JSON, JSONL, CSV and Markdown. This directory is ignored by
git. To keep searches separate use `--out .mersearch/another-query`.

The tool always searches within **this nlab checkout**, independent of your
current working directory.

## Features

- Boolean AND, OR, NOT; parentheses; quoted phrases; implicit AND; NEAR/n token proximity.
- Fields `body:`, `math:`, `path:`, `name:`, `ext:`, `type:`, `title:`, `date:`, `role:`, `author:`, `status:` and related record fields.
- Source-located results, file SHA-256, provenance and match explanation.
- JSON content detection even for files with `.txt`, `.md` or unusual extensions.
- ChatGPT-compatible JSON messages treated as structured records when such exports are present.
- Skipped oversized files, output pagination limits and exclusions reported explicitly.
- By default excludes vendored dependencies, generated data, cached pages, secret configuration, `PRIOR_ART` and `QUARANTINE`.
- An explicit `--include-vendor` option permits dependency source searches without broadening beyond nlab.
- Self-describing `--capabilities` and `--examples` for LLM workers.

The repository's Ruby, Python, Rails templates, SQL, documentation, TeX and
other readable text files are searchable. Wiki database content is **not**
automatically part of the corpus.

## Optional symbolic mathematics

~~~bash
python3 -m pip install -r tools/requirements-mersearch.txt
python3 tools/mersearch.py --expr 'equiv:"a+b=c"'
python3 tools/mersearch.py --expr 'contains:"a+b"'
python3 tools/mersearch.py --expr 'value:"x=0.25;atol=0.01"'
python3 tools/mersearch.py --inventory-only --math-genealogy --out .mersearch/mathematics
~~~

`math:` means notation-normalized text search, not an equivalence proof.

`equiv:` proves only a deliberately restricted class of **exact polynomial
equalities** with the same named variables and supported constant-denominator
assumptions. It does not establish equivalence between different physical
quantities or arbitrary mathematical domains.

`contains:` matches supported symbolic syntax trees.

`value:` checks numerical proximity with an explicit absolute tolerance.
Numerically consistent is **not** the same as mathematically identical.

`--math-inventory` writes source-located equation candidates in JSONL.
`--math-genealogy` adds nlab-local recurrence families and separately labeled
numeric proximity links. This is not proof of a historical causal derivation.

The parser does not handle general unbounded LaTeX, arbitrary CAS identities,
symbolic tensor calculus, missing domain assumptions, unit conversion, or OCR
of scanned PDFs. SymPy is optional for ordinary searching, but required for
these bounded mathematical modes. Extractable PDFs require optional pypdf.

## Strict independence and safety

The implementation:

1. Has a **fixed repository root**, determined from the installed script.
   There is no cross-repository default or multi-root discovery.
2. Rejects absolute paths, parent path traversal, symlinked scope/output
   paths, and output destinations outside `.mersearch/`.
3. Imports only its own vendored modules. It has **no network or GitHub API**
   operations, no remote source fetch and no database connector.
4. Excludes secrets and production/generated Rails paths from scanning.
5. Does **not** modify the nLab application's routes, wiki search, database,
   page-rendering behavior, or running services.
6. Writes repo-relative source locations and optional links into **nlab
   alone**, without linking or querying another archive.

Exported mathematical wiki pages, if supplied, should be treated as a
separate source collection with their own documented copyright and provenance.
Do not infer historical page revisions from the checkout's Git timestamps.

## Test

~~~bash
python3 -m unittest discover -s tools/tests -p 'test_mersearch.py' -v
~~~

A dedicated GitHub Actions workflow tests parsing, mathematical queries,
JSON stored in text files, local provenance, and rejection of path escape.

**Code provenance:** Query grammar and mathematical subsets were adapted from
an earlier Mersearch implementation into a fully independent local copy.
No runtime dependency, shared cache, synchronization process, or
interoperability exists between the implementations.

**Initial nlab port:** 2026-10-09.
