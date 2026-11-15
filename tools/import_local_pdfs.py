"""Parse local Guangsu PDFs into headword-only, source-attributed indexes.

The importer deliberately stores English headwords and file fingerprints, not PDF
definitions, IPA, mnemonics, or prose. This keeps derived files small and avoids
turning the skill into a bulk copy of the source book/PDF text.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "PyMuPDF is required. Install with: python -m pip install pymupdf"
    ) from exc

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "assets" / "pdf-derived"
CANONICAL_DIR = ROOT / "assets" / "wordlists"

POS_WORDS = (
    "n", "v", "a", "adj", "adv", "vi", "vt", "prep", "conj", "pron", "art",
    "num", "interj", "aux", "abbr", "ad", "pl",
)
PURE_HEADWORD_RE = re.compile(r"^[A-Za-z][A-Za-z\u2019'\-\. \(\)/&;0-9]*$")
POS_DELIM_RE = re.compile(
    r"(?:(?<=\s)|^)(?=[nva]t?\.|adj\.|adv\.|"
    + "|".join(re.escape(word) + r"\." for word in POS_WORDS if word not in {"n", "v", "a", "adj", "adv"})
    + r")",
    re.I,
)
OTHER_DELIM_RE = re.compile(r"[\u4e00-\u9fff]|\[|\(|\"|/")
POS_ONLY_RE = re.compile(r"^(?:" + "|".join(re.escape(word) + r"\." for word in POS_WORDS) + r")$", re.I)
POS_ARTIFACT_RE = re.compile(
    r"^(?:" + "|".join(re.escape(word) + r"\." for word in POS_WORDS) + r")"
    r"(?:\s*(?:&|/|\.|[A-Za-z]{1,4}\.?))*$",
    re.I,
)
NUMBERED_RE = re.compile(r"^(\d+)\.\s*(.*)$")
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z\u2019'-]*")

SOURCE_RULES = (
    ("stage2-mindmap", ("阶段二", "思维导图")),
    ("outline-6000", ("1天搞定6000单词大纲",)),
    ("cet4-source", ("大学四级英语考试考纲词汇",)),
    ("kaoyan-5500-source", ("考研5500词大纲",)),
    ("gaokao-3500-source", ("高中英语考纲3500词汇",)),
    ("method-declaration", ("彻底根治单词难题",)),
    ("guided-course", ("畅读导学课",)),
    ("grammar-summary", ("英语语法资料",)),
)


def normalize_line(value: str) -> str:
    value = value.replace("\u200e", "").replace("\u200f", "").replace("\ufeff", "")
    value = unicodedata.normalize("NFKC", value)
    return " ".join(value.split())


def read_pdf(path: Path) -> tuple[int, list[str], str]:
    with fitz.open(path) as doc:
        pages = doc.page_count
        raw_lines: list[str] = []
        chunks: list[str] = []
        for page in doc:
            text = page.get_text("text")
            chunks.append(text)
            raw_lines.extend(text.splitlines())
    return pages, [normalize_line(line) for line in raw_lines if normalize_line(line)], "\n".join(chunks)


def is_pos_only(value: str) -> bool:
    if value.lower() in {"n", "v", "vt", "vi", "adj", "adv", "prep", "conj", "pron", "art", "num", "interj", "aux", "abbr", "pl", "ad"}:
        return True
    return bool(POS_ONLY_RE.fullmatch(value) or POS_ARTIFACT_RE.fullmatch(value))


def clean_headword(value: str) -> str:
    value = value.strip().strip("\"'\u2019").strip()
    value = " ".join(value.split())
    value = re.sub(r"\s*-\s*", "-", value)
    if value.lower().endswith(" modal"):
        value = value[:-6].strip()
    if value.lower().endswith("v") and len(value) > 2 and value[-2].isalpha():
        # Handles a small PDF extraction error such as "troopv vi.".
        value = value[:-1]
    return value.strip()


def valid_headword(value: str) -> bool:
    value = clean_headword(value)
    if not value or len(value) > 70:
        return False
    if not PURE_HEADWORD_RE.fullmatch(value):
        return False
    if re.search(r"[\u4e00-\u9fff]", value):
        return False
    if not re.search(r"[A-Za-z]", value):
        return False
    if len(value) == 1 and value.upper() not in {"A", "I"}:
        return False
    if is_pos_only(value):
        return False
    if value.lower() in {"the"}:
        return False
    return True


def split_headword(line: str) -> str | None:
    """Take the leading English headword before POS, CJK, IPA, or quote markers."""
    if PURE_HEADWORD_RE.fullmatch(line) and not POS_DELIM_RE.search(line) and not OTHER_DELIM_RE.search(line):
        return line
    positions: list[int] = []
    match = POS_DELIM_RE.search(line)
    if match:
        positions.append(match.start())
    match = OTHER_DELIM_RE.search(line)
    if match:
        positions.append(match.start())
    if not positions:
        return None
    candidate = line[: min(positions)].strip()
    if not PURE_HEADWORD_RE.fullmatch(candidate):
        return None
    return candidate


def parse_plain_lines(lines: list[str]) -> tuple[list[str], int]:
    """Parse lists where extracted headwords usually begin a line."""
    output: list[str] = []
    seen: set[str] = set()
    records = 0
    for line in lines:
        candidate = clean_headword(split_headword(line) or "")
        if not valid_headword(candidate):
            continue
        records += 1
        key = candidate.casefold()
        if key not in seen:
            seen.add(key)
            output.append(candidate)
    return output, records


def ipaish(value: str) -> bool:
    if not value or re.search(r"[\u4e00-\u9fff]", value):
        return False
    has_marker = bool(
        re.search(r"[\u0250-\u02ff\u0370-\u04ff'.,:/;\[\]()\-]", value)
        or re.fullmatch(r"[A-Za-z,\.\'\-:/\[\]\(\)0-9 ]+", value)
    )
    return has_marker and len(value) <= 100


def parse_cet_pairs(lines: list[str]) -> tuple[list[str], int]:
    """The CET PDF emits headword / phonetic lines in separate PDF rows."""
    output: list[str] = []
    seen: set[str] = set()
    records = 0
    for current, following in zip(lines, lines[1:]):
        candidate = clean_headword(current)
        if not PURE_HEADWORD_RE.fullmatch(candidate) or not valid_headword(candidate):
            continue
        if not ipaish(following):
            continue
        records += 1
        key = candidate.casefold()
        if key not in seen:
            seen.add(key)
            output.append(candidate)
    return output, records


def parse_numbered(lines: list[str]) -> tuple[list[str], int]:
    """Parse `1. word` lists; some PDF rows split the number and word."""
    output: list[str] = []
    seen: set[str] = set()
    records = 0
    for index, line in enumerate(lines):
        match = NUMBERED_RE.fullmatch(line)
        if not match:
            continue
        records += 1
        rest = match.group(2).strip()
        candidate = split_headword(rest) if rest else None
        if not candidate and index + 1 < len(lines):
            candidate = split_headword(lines[index + 1])
        candidate = clean_headword(candidate or "")
        if not valid_headword(candidate):
            continue
        key = candidate.casefold()
        if key not in seen:
            seen.add(key)
            output.append(candidate)
    return output, records


def parse_stage2_mindmap(lines: list[str]) -> tuple[list[str], int]:
    """Parse the numbered node markers in the one-page stage-two map."""
    output: list[str] = []
    seen: set[str] = set()
    records = 0
    for index, line in enumerate(lines):
        match = NUMBERED_RE.fullmatch(line)
        if not match:
            continue
        rest = match.group(2).strip()
        candidate = split_headword(rest) if rest else None
        if not candidate and index + 1 < len(lines):
            candidate = split_headword(lines[index + 1])
        candidate = clean_headword(candidate or "")
        if not valid_headword(candidate):
            continue
        records += 1
        key = candidate.casefold()
        if key not in seen:
            seen.add(key)
            output.append(candidate)
    return output, records


def extract_tokens(text: str) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for token in TOKEN_RE.findall(text):
        key = token.casefold().replace("\u2019", "'")
        if key not in seen:
            seen.add(key)
            output.append(token)
    return sorted(output, key=lambda token: token.casefold())


STRUCTURED_IDS = {"outline-6000", "cet4-source", "kaoyan-5500-source", "gaokao-3500-source", "stage2-mindmap"}


def classify(filename: str) -> tuple[str, str]:
    for source_id, needles in SOURCE_RULES:
        if all(needle in filename for needle in needles):
            role = "structured_wordlist" if source_id in STRUCTURED_IDS else "indexed_method_or_list"
            return source_id, role
    for source_id, needles in SOURCE_RULES:
        if any(needle in filename for needle in needles):
            return source_id, "indexed_method_or_list"
    return "unknown-" + hashlib.sha256(filename.encode("utf-8")).hexdigest()[:8], "indexed_document"


def canonical_keys() -> set[str]:
    keys: set[str] = set()
    for path in CANONICAL_DIR.glob("*.txt"):
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            word = line.split("\t", 1)[0].strip()
            if word:
                keys.add(word.casefold())
    return keys


def relative_paths(paths: list[Path], root: Path) -> list[str]:
    result = []
    for path in paths:
        try:
            result.append(str(path.relative_to(root)))
        except ValueError:
            result.append(str(path))
    return sorted(result)


def write_tsv(path: Path, rows: list[tuple[str, ...]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        for row in rows:
            handle.write("\t".join(row) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="directory containing the Guangsu PDF collection")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="output directory under the skill")
    parser.add_argument("--store-source-paths", action="store_true", help="store copy paths in manifest.json")
    args = parser.parse_args()

    source_root = Path(args.source).expanduser().resolve()
    out_dir = Path(args.out).expanduser().resolve()
    if not source_root.is_dir():
        raise SystemExit(f"source directory does not exist: {source_root}")
    if ROOT not in out_dir.parents:
        raise SystemExit(f"--out must stay inside the skill workspace: {ROOT}")

    pdf_files = sorted(path for path in source_root.rglob("*.pdf") if path.is_file())
    if not pdf_files:
        raise SystemExit("no PDF files found")

    by_hash: dict[str, list[Path]] = defaultdict(list)
    for path in pdf_files:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        by_hash[digest].append(path)

    sources: list[dict[str, object]] = []
    word_sources: dict[str, set[str]] = defaultdict(set)
    word_forms: dict[str, set[str]] = defaultdict(set)
    canonical = canonical_keys()
    token_totals: dict[str, int] = {}

    headword_dir = out_dir / "headwords"
    token_dir = out_dir / "tokens"
    headword_dir.mkdir(parents=True, exist_ok=True)
    token_dir.mkdir(parents=True, exist_ok=True)

    for digest, copies in by_hash.items():
        first = copies[0]
        source_id, role = classify(first.name)
        pages, lines, text = read_pdf(first)
        records = 0
        headwords: list[str] = []
        if source_id == "outline-6000":
            headwords, records = parse_plain_lines(lines)
        elif source_id == "cet4-source":
            headwords, records = parse_cet_pairs(lines)
        elif source_id == "kaoyan-5500-source":
            headwords, records = parse_numbered(lines)
        elif source_id == "gaokao-3500-source":
            headwords, records = parse_plain_lines(lines)
        elif source_id == "stage2-mindmap":
            headwords, records = parse_stage2_mindmap(lines)

        tokens = extract_tokens(text)
        token_totals[source_id] = len(tokens)
        token_path = token_dir / f"{source_id}.txt"
        token_path.write_text("\n".join(tokens) + "\n", encoding="utf-8", newline="\n")

        if headwords:
            (headword_dir / f"{source_id}.txt").write_text(
                "\n".join(headwords) + "\n", encoding="utf-8", newline="\n"
            )
            for word in headwords:
                key = word.casefold()
                word_sources[key].add(source_id)
                word_forms[key].add(word)

        canonical_hits = sum(1 for word in headwords if word.casefold() in canonical)
        source_record: dict[str, object] = {
            "source_id": source_id,
            "role": role,
            "filename": first.name,
            "sha256": digest,
            "pages": pages,
            "copies": len(copies),
            "headword_records": records,
            "unique_headwords": len(set(word.casefold() for word in headwords)),
            "headwords_in_canonical_wordlists": canonical_hits,
            "headwords_new_vs_canonical": len(set(word.casefold() for word in headwords) - canonical),
            "indexed_english_tokens": len(tokens),
            "definition_or_prose_stored": False,
        }
        if args.store_source_paths:
            source_record["copy_paths"] = relative_paths(copies, source_root)
        sources.append(source_record)

    # Stable manifest order: known course list first, then indexed docs.
    known_order = {source_id: index for index, (source_id, _) in enumerate(SOURCE_RULES)}
    sources.sort(key=lambda item: (known_order.get(str(item["source_id"]), 99), str(item["filename"])))

    keys = sorted(word_sources)
    write_tsv(
        out_dir / "word-index.tsv",
        [
            (
                "|".join(sorted(word_forms[key], key=lambda form: form.casefold())),
                key,
                ",".join(sorted(word_sources[key])),
            )
            for key in keys
        ],
    )
    (out_dir / "all-headwords.txt").write_text(
        "\n".join(next(iter(sorted(word_forms[key], key=lambda form: form.casefold()))) for key in keys)
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    missing = [key for key in keys if key not in canonical]
    write_tsv(
        out_dir / "missing-from-canonical.tsv",
        [
            (
                "|".join(sorted(word_forms[key], key=lambda form: form.casefold())),
                key,
                ",".join(sorted(word_sources[key])),
            )
            for key in missing
        ],
    )

    total_records = sum(int(item.get("headword_records", 0)) for item in sources)
    total_unique = sum(int(item.get("unique_headwords", 0)) for item in sources)
    manifest = {
        "schema_version": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "extractor": {
            "pdf_library": "PyMuPDF/fitz",
            "scope": "deduplicated local PDFs; English headword candidates only",
            "stores_definitions_ipa_mnemonics_or_prose": False,
        },
        "source_root": str(source_root),
        "scan": {
            "pdf_files": len(pdf_files),
            "unique_by_sha256": len(by_hash),
            "duplicate_copies": len(pdf_files) - len(by_hash),
        },
        "totals": {
            "headword_records": total_records,
            "unique_headword_instances_across_sources": total_unique,
            "unique_normalized_headwords": len(keys),
            "new_vs_canonical_wordlists": len(missing),
            "indexed_english_token_files": len(token_totals),
        },
        "sources": sources,
        "files": {
            "source_headwords": "headwords/{source_id}.txt",
            "english_token_indexes": "tokens/{source_id}.txt",
            "all_headwords": "all-headwords.txt",
            "word_index": "word-index.tsv",
            "missing_vs_canonical": "missing-from-canonical.tsv",
        },
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )

    # Generate a concise README from the actual manifest.
    readme = [
        "# 本地 PDF 解析索引",
        "",
        f"- 来源根目录：`{source_root}`",
        f"- 扫描 PDF：**{len(pdf_files)}** 个，SHA-256 去重后：**{len(by_hash)}** 个",
        f"- 解析出的规范化词头：**{len(keys)}** 个",
        f"- 相对现有考纲词表新增：**{len(missing)}** 个",
        "",
        "## 边界",
        "",
        "- 这些文件只存英文词头、来源 ID 和文件指纹；**不复制 PDF 释义、音标、谐音或讲解正文**。",
        "- 四份考纲 PDF 与阶段二导图解析为 `headwords/*.txt`。",
        "- 方法/语法 PDF 生成 `tokens/*.txt`，它们是英文词例索引，不是课程词表，也不代表全部中文内容已被复制。",
        "- 想重建时运行：",
        "",
        "```powershell",
        f'python tools/import_local_pdfs.py "{source_root}"',
        "```",
        "",
        "## 来源摘要",
        "",
        "| source_id | PDF | 页数 | 副本数 | 词头 | 新词头 | 英文token |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for item in sources:
        readme.append(
            "| {source_id} | {filename} | {pages} | {copies} | {unique_headwords} | "
            "{headwords_new_vs_canonical} | {indexed_english_tokens} |".format(**item)
        )
    readme.extend(
        [
            "",
            "## 主要文件",
            "",
            "- `all-headwords.txt`：全部结构化 PDF 词头（去重后）",
            "- `word-index.tsv`：词头变体、规范化键、来源 ID",
            "- `missing-from-canonical.tsv`：PDF 有但现有四份考纲词表没有的词头",
            "- `manifest.json`：扫描统计、SHA-256 和解析边界",
            "- `headwords/`：按 PDF 来源拆分的词头",
            "- `tokens/`：方法/语法 PDF 的英文词例索引",
        ]
    )
    (out_dir / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8", newline="\n")

    print(f"scanned={len(pdf_files)} unique_pdfs={len(by_hash)} unique_headwords={len(keys)} new_vs_canonical={len(missing)}")
    print(f"output={out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

