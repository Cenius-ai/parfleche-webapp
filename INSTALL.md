# Installing Parfleche

Parfleche is one Python file with no third-party dependencies. "Installing" means
having a Python 3.8+ interpreter and the project checked out.

## Prerequisites (install these yourself, the setup script never does)

| Requirement | Why | Check |
| --- | --- | --- |
| Python 3.8 or newer | the interpreter that runs `parfleche.py` | `python3 --version` |
| A POSIX shell (`bash`/`sh`) | runs `install.sh` and `demo.sh` | `bash --version` |

Nothing else: no compiler, no database, no network access, no service to start.
`pytest` is optional — the suite also runs on the standard library's `unittest`.

## 1. Set up (installs nothing, then exits)

```bash
bash install.sh
```

What it does, in order:

1. Checks `python3` exists and is 3.8 or newer.
2. Refreshes `pip`/`setuptools`/`wheel` if PyPI is reachable (it prints a note and
   continues when the machine is offline — Parfleche needs no packages).
3. Imports `parfleche.py` and asserts `SCHEMA_VERSION == 1`, so a damaged file
   fails loudly here instead of at first use.
4. Exits. The script never starts the shell and never blocks on a prompt.

Re-running it is safe and does the same thing again.

## 2. Run it

```bash
python3 parfleche.py
```

That is the whole start command: it reads stdin, writes stdout, needs no
environment variables, creates no files unless you ask it to (`project save`,
`export recipes`), and starts at the `parfleche>` prompt. `python3 parfleche.py
--help` prints usage and examples without entering the shell.

## 3. Check it works

```bash
bash demo.sh
```

The demo loads `examples/parfleche-blanket.json`, mirrors the motif, exports
recipe cards, saves the project and prints the results from a temporary
directory. It exits 0 on success and leaves no files behind.

## 4. Run the tests (optional)

```bash
python3 -m pytest -q
python3 -m unittest discover -s tests -v   # if pytest is not installed
```

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `python3: command not found` | install Python 3.8+ from your system package manager or python.org |
| `install: Parfleche needs Python 3.8 or newer` | the `python3` on PATH is too old; put a newer interpreter first on PATH |
| `Error: JSON parse error in 'file.json'` | the file is not the JSON Parfleche saved; open it in a text editor or re-save |
| `Error: unsupported schema_version N` | the file was written by a different Parfleche schema; this build reads version 1 |
| `Error: cannot save 'x/y.json': directory 'x' does not exist` | create the directory first — Parfleche never creates paths silently |
| `Error: cannot save 'x': path is outside the working directory '/work'` | run Parfleche from the directory you want to work in, or use a relative path inside it; nothing outside the workspace is read or written |
| Coloured output is not what you want | there is none: output is plain monochrome text |
