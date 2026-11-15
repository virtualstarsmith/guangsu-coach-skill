"""Validate the bundled wordlists and the deterministic 2000/4000/6000 curriculum."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORDLIST_DIR = ROOT / "assets" / "wordlists"
STAGE_SIZE = 2000


def read_rows(path: Path) -> list[tuple[str, str]]:
    """Read a word<TAB>definition file and raise a useful error if malformed."""
    rows: list[tuple[str, str]] = []
    text = path.read_text(encoding="utf-8-sig")
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) != 2:
            raise ValueError(f"{path.name}:{lineno}: expected exactly one TAB")
        word, definition = (part.strip() for part in parts)
        if not word:
            raise ValueError(f"{path.name}:{lineno}: empty headword")
        if not definition:
            raise ValueError(f"{path.name}:{lineno}: empty definition for {word!r}")
        rows.append((word, definition))
    if not rows:
        raise ValueError(f"{path.name}: no rows")
    return rows


def unique_rows(rows: list[tuple[str, str]], limit: int | None = None) -> list[tuple[str, str]]:
    seen: set[str] = set()
    result: list[tuple[str, str]] = []
    for word, definition in rows:
        key = word.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append((word, definition))
        if limit is not None and len(result) >= limit:
            break
    return result


def validate_wordlist_files() -> dict[str, list[tuple[str, str]]]:
    paths = sorted(WORDLIST_DIR.glob("*.txt"))
    expected = {
        "cet4-4000.txt",
        "dagang-6000.txt",
        "gaokao-3500.txt",
        "kaoyan-5500.txt",
    }
    names = {path.name for path in paths}
    missing = expected - names
    if missing:
        raise ValueError(f"missing wordlists: {', '.join(sorted(missing))}")

    rows_by_file = {path.name: read_rows(path) for path in paths}
    cet_rows = rows_by_file["cet4-4000.txt"]
    if len(cet_rows) != 4000:
        raise ValueError(f"cet4-4000.txt: expected 4000 rows, got {len(cet_rows)}")
    cet_keys = [word.casefold() for word, _ in cet_rows]
    if len(set(cet_keys)) != len(cet_keys):
        raise ValueError("cet4-4000.txt: duplicate case-insensitive headwords")
    return rows_by_file


def validate_curriculum(rows_by_file: dict[str, list[tuple[str, str]]]) -> tuple[int, int, int, int]:
    stage1 = unique_rows(rows_by_file["gaokao-3500.txt"], STAGE_SIZE)
    known = {word.casefold() for word, _ in stage1}

    stage2: list[tuple[str, str]] = []
    for word, definition in rows_by_file["cet4-4000.txt"]:
        key = word.casefold()
        if key in known:
            continue
        known.add(key)
        stage2.append((word, definition))
        if len(stage2) >= STAGE_SIZE:
            break
    if len(stage2) != STAGE_SIZE:
        raise ValueError(f"stage 2 has {len(stage2)} new words; expected {STAGE_SIZE}")

    stage3: list[tuple[str, str]] = []
    for name in ("gaokao-3500.txt", "kaoyan-5500.txt", "dagang-6000.txt"):
        for word, definition in rows_by_file[name]:
            key = word.casefold()
            if key in known:
                continue
            known.add(key)
            stage3.append((word, definition))
            if len(stage3) >= STAGE_SIZE:
                break
        if len(stage3) >= STAGE_SIZE:
            break
    if len(stage3) != STAGE_SIZE:
        raise ValueError(f"stage 3 has {len(stage3)} new words; expected {STAGE_SIZE}")

    all_keys = {
        word.casefold() for rows in rows_by_file.values() for word, _ in rows
    }
    stage_keys = {word.casefold() for word, _ in stage1 + stage2 + stage3}
    overlap = len(stage1 + stage2 + stage3) - len(stage_keys)
    if overlap:
        raise ValueError(f"stage overlap detected: {overlap} words")
    if len(stage_keys) != 3 * STAGE_SIZE:
        raise ValueError(f"curriculum has {len(stage_keys)} words; expected {3 * STAGE_SIZE}")
    if not stage_keys.issubset(all_keys):
        raise ValueError("internal error: stage words not present in source files")
    return len(stage1), len(stage2), len(stage3), len(stage_keys)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--curriculum",
        action="store_true",
        help="also verify the deterministic stage-one/two/three selection",
    )
    args = parser.parse_args()

    try:
        rows_by_file = validate_wordlist_files()
        if args.curriculum:
            stage_counts = validate_curriculum(rows_by_file)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"validation failed: {exc}", file=sys.stderr)
        return 1

    for name, rows in rows_by_file.items():
        print(f"{name}: {len(rows)} rows")
    if args.curriculum:
        stage1, stage2, stage3, total = stage_counts
        print(
            "curriculum: "
            f"stage1={stage1}, stage2={stage2}, stage3={stage3}, total={total}"
        )
    print("validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())