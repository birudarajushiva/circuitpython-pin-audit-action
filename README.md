# CircuitPython Pin Audit Action

Check firmware pin ownership in a pull request without connecting a board or
executing the firmware. This composite GitHub Action installs a pinned revision
of [CircuitPython Pin Audit](https://github.com/birudarajushiva/circuitpython-pin-audit),
annotates potential conflicts, and saves a JSON report for later workflow steps.

It is an integration for the existing analyzer, not a separate analysis engine.

## Use it

```yaml
name: Firmware checks
on: [push, pull_request]
permissions:
  contents: read
jobs:
  pins:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262
        with:
          persist-credentials: false
      - uses: birudarajushiva/circuitpython-pin-audit-action@v1.0.0
        with:
          paths: firmware/code.py
```

For stronger supply-chain control, replace the action tag with the reviewed full
commit SHA of this repository. The analyzer revision and setup-python action are
already pinned inside `action.yml`; analyzer upgrades require a code change.

The action sets up Python 3.12 and uses network access to install the pinned
analyzer and its build requirements. It needs no model API, board connection,
secret, or write permission. It runs on GitHub-hosted Linux, Windows, and macOS;
self-hosted runners need Git, a working setup-python environment, and bash.

## Inputs

- `paths`: one file/directory per line; default `code.py`. A path containing spaces
  stays one path. Globs are not expanded. Each file is an independent entrypoint,
  not part of an automatically analyzed module graph.
- `strict`: `true` by default. Set `false` to keep recognized coverage gaps
  advisory; detected pin conflicts still fail.
- `aliases`: optional JSON alias-group file for your actual board.
- `exclude`: optional exclusion patterns, one per line, used for directory scans.

```yaml
- uses: birudarajushiva/circuitpython-pin-audit-action@v1.0.0
  id: pins
  with:
    paths: |
      firmware/code.py
      alternate demo/code.py
    aliases: config/board-aliases.json
    strict: 'true'
```

## Results and reports

Outputs are `exit-code`, `conflicts`, `coverage-gap-files`, and `report-path`.
Exit 0 means no findings under the selected policy, 1 means pin conflicts or
strict-mode coverage gaps, and 2 means an operational/analysis error. The report
is saved in a newly created directory under `RUNNER_TEMP`, including on findings.
It is not uploaded automatically and expires with the runner.

Use the normal workflow `continue-on-error: true` setting for an advisory rollout.
GitHub records that step's outcome as failure when findings exist; the underlying
exit code is preserved in the report. Do not interpret advisory success as an
absence of findings.

The report envelope has `action_schema_version: 1`, `exit_code`, `scan` (the
analyzer's JSON schema 1 report, or null), and `error` (or null). A job summary
contains counts, not source files. Annotations identify source paths, line
numbers, and pin names. Review diagnostic reports before sharing them outside
your repository. Runner provisioning failures can happen before a report exists.

## Execution boundaries

Inputs pass through environment variables and argument arrays, not shell
interpolation. Both the adapter and analyzer run with Python's isolated mode to
prevent a checked-out `pin_audit.py`/`json.py` or `PYTHONPATH` from shadowing the
installed modules. Tests exercise these cases as well as filenames with spaces,
option-looking input, explicit aliases, exit codes, and failure reports.

This does not make the analyzer a hardened sandbox. It parses untrusted source
and has the upstream size/path limits and a two-minute process timeout. See the
[analyzer's limitations](https://github.com/birudarajushiva/circuitpython-pin-audit/blob/ae455d5d4887373d2b33d7c72b2c6c52c99b5098/docs/limitations.md):
helper functions, imported user modules, dynamic driver internals, and some
control flow are outside its model. No result certifies electrical correctness,
board compatibility, or physical hardware operation.

## Contribute

Run adapter tests with the pinned analyzer installed:

```sh
python -m pip install 'git+https://github.com/birudarajushiva/circuitpython-pin-audit.git@ae455d5d4887373d2b33d7c72b2c6c52c99b5098'
python -m unittest discover -s tests -v
```

Report workflow/annotation/output bugs here. Report missed pin conflicts and
false positives in the analyzer repository with a minimal reproducer. Keep
analyzer-version upgrades separate from adapter behavior changes.

MIT licensed; not affiliated with or endorsed by GitHub, Adafruit, or CircuitPython.
