#!/usr/bin/env python3
"""Generate GitHub release notes from the commits between two tags.

Used by the release workflow (`.github/workflows/release.yml`) and handy
locally for drafting what a tag will contain.

Usage:

    python scripts/generate_changelog.py --tag v0.2.0 -o release-notes.md

Behaviour:

- Finds the previous tag before ``--tag`` (``git describe --tags --abbrev=0 TAG^``).
- Lists every commit in ``PREV..TAG`` (or, if no previous tag exists, all
  commits reachable from ``TAG``), grouped by conventional-commit prefix
  (Features / Fixes / Performance / Docs / Other).
- Writes Markdown that is attached to the GitHub Release body while
  ``generate_release_notes: true`` still supplies the compare-link footer.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

# Conventional-commit prefix → release-notes section, in display order.
_SECTIONS: list[tuple[str, str]] = [
    ("feat", "🚀 Features"),
    ("fix", "🐛 Fixes"),
    ("perf", "⚡ Performance"),
    ("docs", "📚 Documentation"),
    ("test", "✅ Tests"),
    ("refactor", "♻️ Refactoring"),
    ("chore", "🔧 Chores"),
    ("ci", "👷 CI"),
]

_OTHER = "📝 Other Changes"


def _git(*args: str) -> str:
    """Run a git command, returning stdout or empty string on failure."""
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ""


def _repo_url() -> str | None:
    """Best-effort owner/repo slug from the origin remote (CI works too)."""
    repo_url = os.environ.get("GITHUB_REPOSITORY")
    if repo_url:
        return repo_url
    origin = _git("remote", "get-url", "origin")
    for prefix in ("git@github.com:", "https://github.com/"):
        if prefix in origin:
            slug = origin.split(prefix, 1)[1]
            return slug.removesuffix(".git")
    return None


def _previous_tag(tag: str) -> str | None:
    return _git("describe", "--tags", "--abbrev=0", f"{tag}^") or None


def _commits(since: str | None, tag: str) -> list[tuple[str, str]]:
    """Return (short_sha, subject) pairs for the range, oldest → latest not needed—
    we display newest → oldest (git log default order)."""
    if since:
        out = _git("log", f"{since}..{tag}", "--pretty=%H|%s")
    else:
        out = _git("log", tag, "--pretty=%H|%s")
    commits: list[tuple[str, str]] = []
    for line in out.splitlines():
        if "|" not in line:
            continue
        sha, subject = line.split("|", 1)
        commits.append((sha[:9], subject))
    return commits


def _classify(subject: str) -> tuple[str, str]:
    """Map a commit subject to (section_title, cleaned_subject)."""
    for prefix, title in _SECTIONS:
        if subject.lower().startswith(prefix):
            head, sep, tail = subject.partition(":")
            if sep:  # conventional commit: strip the "prefix(scope):" head
                return title, tail.strip()
    return _OTHER, subject


def generate(tag: str) -> str:
    """Render full release-notes Markdown for ``tag``."""
    prev = _previous_tag(tag)
    commits = _commits(prev, tag)
    slug = _repo_url()

    lines: list[str] = []

    if prev:
        lines.append(f"## Changes since `{prev}`")
    else:
        lines.append(f"## Initial release `{tag}`")
    lines.append("")

    if not commits:
        lines.append("_No commits in this range._")
    else:
        buckets: dict[str, list[str]] = {}
        for sha, subject in commits:
            title, cleaned = _classify(subject)
            entry = f"- `{sha}` {cleaned}"
            if slug:  # link straight to the commit on GitHub
                entry = f"- [`{sha}`](https://github.com/{slug}/commit/{sha}) {cleaned}"
            buckets.setdefault(title, []).append(entry)
        for prefix, title in _SECTIONS + [(_OTHER, _OTHER)]:
            entries = buckets.pop(title, None)
            if entries:
                lines.append(f"### {title}")
                lines.extend(entries)
                lines.append("")

    if slug and prev:
        lines.append(
            f"**Full Changelog**: https://github.com/{slug}/compare/{prev}...{tag}"
        )
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tag",
        default=os.environ.get("GITHUB_REF_NAME"),
        help="Tag to generate notes for (default: GITHUB_REF_NAME in CI)",
    )
    parser.add_argument("-o", "--output", default="-", help="Output file (default: stdout)")
    args = parser.parse_args()

    if not args.tag:
        print("error: no --tag given and GITHUB_REF_NAME is unset", file=sys.stderr)
        return 1

    notes = generate(args.tag)
    if args.output == "-":
        print(notes)
    else:
        with open(args.output, "w") as fh:
            fh.write(notes)
        print(f"wrote {args.output} ({len(notes.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
