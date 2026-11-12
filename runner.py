"""GitHub Action adapter for the pinned Pin Audit CLI; standard library only."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid


def lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def command(env: dict[str, str]) -> list[str]:
    paths = lines(env.get("PIN_AUDIT_PATHS", "code.py"))
    if not paths:
        raise ValueError("paths must contain at least one file or directory")
    strict = env.get("PIN_AUDIT_STRICT", "true").strip().lower()
    if strict not in {"true", "false"}:
        raise ValueError("strict must be 'true' or 'false'")
    # -I prevents checked-out pin_audit.py/json.py/PYTHONPATH from shadowing
    # the installed analyzer or its dependencies. No user path is shell code.
    result = [sys.executable, "-I", "-m", "pin_audit", "--format", "json"]
    if strict == "true":
        result.append("--strict")
    aliases = env.get("PIN_AUDIT_ALIASES", "").strip()
    if aliases:
        result.append(f"--aliases={aliases}")
    for pattern in lines(env.get("PIN_AUDIT_EXCLUDE", "")):
        result.append(f"--exclude={pattern}")
    # The delimiter also prevents a filename beginning with '--' becoming an option.
    return result + ["--", *paths]


def escape(text: str, prop: bool = False) -> str:
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    return text.replace(":", "%3A").replace(",", "%2C") if prop else text


def annotation(level: str, message: str, *, path: str = "", line: int = 1,
               column: int = 1, title: str = "Pin audit") -> str:
    return (f"::{level} file={escape(path, True)},line={line},col={column},"
            f"title={escape(title, True)}::{escape(message)}")


def outputs(path: str, values: dict[str, str]) -> None:
    if not path:
        return
    # Delimited outputs preserve Windows paths and avoid newline injection.
    with open(path, "a", encoding="utf-8") as stream:
        for key, value in values.items():
            delimiter = "pin_audit_" + uuid.uuid4().hex
            stream.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")


def validate_report(document: object) -> None:
    """Validate fields consumed by the adapter before emitting any results."""
    if (not isinstance(document, dict) or document.get("schema_version") != 1
            or not isinstance(document.get("files"), list)):
        raise ValueError("unexpected analyzer report schema")
    for file in document["files"]:
        if (not isinstance(file, dict) or not isinstance(file.get("path"), str)
                or type(file.get("conflicts")) is not int or file["conflicts"] < 0
                or type(file.get("incomplete")) is not bool
                or not isinstance(file.get("diagnostics"), list)):
            raise ValueError("invalid file entry in analyzer report")
        for item in file["diagnostics"]:
            if (not isinstance(item, dict)
                    or item.get("severity") not in ("error", "warning", "notice")
                    or not all(isinstance(item.get(key), str) for key in ("code", "message"))
                    or not all(type(item.get(key)) is int and item[key] >= 1
                               for key in ("line", "column"))):
                raise ValueError("invalid diagnostic in analyzer report")


def main(env: dict[str, str] | None = None) -> int:
    env = dict(os.environ if env is None else env)
    document = None
    error = None
    exit_code = 2
    try:
        invocation = command(env)
        completed = subprocess.run(invocation, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=120, env=env)
        exit_code = completed.returncode
        if exit_code not in {0, 1, 2}:
            raise ValueError(f"analyzer terminated with unexpected status {exit_code}")
        try:
            candidate = json.loads(completed.stdout)
        except json.JSONDecodeError:
            raise ValueError(completed.stderr.strip() or "analyzer returned no valid JSON report") from None
        validate_report(candidate)
        document = candidate
    except (OSError, ValueError, subprocess.TimeoutExpired) as failure:
        error = str(failure)
        exit_code = 2

    files = document["files"] if document else []
    conflicts = sum(file["conflicts"] for file in files)
    gaps = sum(bool(file["incomplete"]) for file in files)
    for file in files:
        for item in file["diagnostics"]:
            print(annotation(item["severity"], item["message"], path=file["path"],
                             line=item["line"], column=item["column"], title=item["code"]))
    if error:
        print(annotation("error", error, title="Pin Audit could not run"))

    try:
        directory = Path(tempfile.mkdtemp(prefix="pin-audit-", dir=env.get("RUNNER_TEMP") or None))
        report = directory / "report.json"
        report.write_text(json.dumps({"action_schema_version": 1, "exit_code": exit_code,
                                      "scan": document, "error": error}, indent=2) + "\n", encoding="utf-8")
        outputs(env.get("GITHUB_OUTPUT", ""), {
            "exit-code": str(exit_code), "conflicts": str(conflicts),
            "coverage-gap-files": str(gaps), "report-path": str(report),
        })
        summary_path = env.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            with open(summary_path, "a", encoding="utf-8") as summary:
                summary.write(f"### CircuitPython Pin Audit\n\n{len(files)} file(s), {conflicts} potential conflict(s), "
                              f"{gaps} file(s) with known coverage gaps. Exit code: {exit_code}.\n\n"
                              "A clean report does not establish hardware safety or compatibility.\n")
    except OSError as failure:
        print(annotation("error", str(failure), title="Cannot save audit report"))
        return 2
    print(f"Pin Audit finished: exit {exit_code}; {conflicts} potential conflict(s); {gaps} file(s) with coverage gaps.")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
