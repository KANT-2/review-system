#!/usr/bin/env python3
"""Render a production env file without printing secret values."""

import argparse
import os
import re
from pathlib import Path

SECRET_RULES = {
    "DJANGO_SECRET_KEY": 64,
    "POSTGRES_PASSWORD": 48,
    "DJANGO_EMAIL_HOST_PASSWORD": 32,
}
SAFE_SECRET = re.compile(r"^[A-Za-z0-9_-]+$")


def read_secrets() -> dict[str, str]:
    secrets = {}
    for name, minimum_length in SECRET_RULES.items():
        value = os.environ.get(name, "")
        if len(value) < minimum_length or not SAFE_SECRET.fullmatch(value):
            raise SystemExit(f"{name} must contain at least {minimum_length} URL-safe characters")
        secrets[name] = value
    return secrets


def render(template: Path, output: Path) -> None:
    secrets = read_secrets()
    rendered = []
    replaced = set()

    for line in template.read_text(encoding="utf-8").splitlines():
        key, separator, _ = line.partition("=")
        if separator and key in secrets:
            rendered.append(f"{key}={secrets[key]}")
            replaced.add(key)
        else:
            rendered.append(line)

    missing = set(secrets) - replaced
    if missing:
        raise SystemExit(f"template is missing secret keys: {', '.join(sorted(missing))}")

    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output_file:
        output_file.write("\n".join(rendered) + "\n")
    output.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    render(arguments.template, arguments.output)


if __name__ == "__main__":
    main()
