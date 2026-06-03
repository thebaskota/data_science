#!/usr/bin/env python3
"""Discover author/reviewer/approver keyword variants across a PDF tree.

This is a standalone analysis helper (no Django required). It walks a folder
and its subfolders, reads the first few pages of every PDF, and reports which
role labels (the words that precede a date + name in approval blocks) actually
appear in the corpus.

The goal is to see *what else needs to be handled* beyond the labels the
ingestion pipeline currently recognizes, namely:

    created : Erstellt / Created / Prepared
    reviewed: Geprüft / Geprueft / Reviewed / Checked
    released: Freigegeben / Released / Approved

Run it like:

    python scan_role_keywords.py /path/to/pdfs
    python scan_role_keywords.py /path/to/pdfs --pages 5 --out role_keywords_report

It writes two files next to the chosen output base name:
    <out>.md    human-readable report
    <out>.json  machine-readable data (every discovered label + examples)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover - dependency guard
    sys.exit("PyMuPDF is required. Install it with: pip install PyMuPDF")


# --- Labels the ingestion pipeline already recognizes (see approval_lines.py) ---
KNOWN_LABELS: dict[str, set[str]] = {
    "created": {"erstellt", "created", "prepared"},
    "reviewed": {"geprüft", "geprueft", "reviewed", "checked"},
    "released": {"freigegeben", "released", "approved"},
}
ALL_KNOWN = {label for labels in KNOWN_LABELS.values() for label in labels}


# --- Broader vocabulary worth flagging if it shows up anywhere on the page ---
# These are candidate words that often signal author/reviewer/approver roles
# but are NOT yet handled by the pipeline. Grouped only for the report.
CANDIDATE_VOCAB: dict[str, set[str]] = {
    "author": {
        "autor",
        "verfasser",
        "author",
        "ersteller",
        "bearbeiter",
        "bearbeitet",
        "verantwortlich",
        "written",
        "issued",
        "drafted",
    },
    "reviewer": {
        "prüfer",
        "pruefer",
        "reviewer",
        "kontrolliert",
        "überprüft",
        "ueberprueft",
        "verified",
        "controlled",
        "examined",
    },
    "approver": {
        "freigabe",
        "genehmigt",
        "genehmigung",
        "approver",
        "authorized",
        "authorised",
        "signed",
        "signoff",
        "released by",
    },
}

DATE_RE = re.compile(r"\b\d{2}[.\-/]\d{2}[.\-/]\d{4}\b")
# A line that begins with a date (a date table cell, e.g. "09.11.2017").
DATE_AT_START_RE = re.compile(r"^\d{2}[.\-/]\d{2}[.\-/]\d{4}\b")
# A label is the leading word(s) on a line that come right before a date.
LABEL_BEFORE_DATE_RE = re.compile(
    r"^([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß ./-]{0,40}?)\s+\d{2}[.\-/]\d{2}[.\-/]\d{4}\b"
)
# "Label: value" style (e.g. "Author: J. Doe", "Geprüft von: ...").
LABEL_COLON_RE = re.compile(r"^([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß ./-]{0,40}?)\s*:\s*\S")
WORD_RE = re.compile(r"[A-Za-zÄÖÜäöüß]+")
# A label sitting alone on its own line (the table/vertical layout, where the
# date and name land on the following lines). No digits, short, few words.
LABEL_LINE_RE = re.compile(r"^[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß ./-]{0,38}$")


@dataclass
class Aggregate:
    pdf_count: int = 0
    read_errors: list[tuple[str, str]] = field(default_factory=list)
    files_with_known: int = 0
    files_without_known: list[str] = field(default_factory=list)
    # discovered label -> count and example lines
    label_counts: Counter[str] = field(default_factory=Counter)
    label_examples: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    # candidate vocab hits: group -> word -> count
    vocab_hits: dict[str, Counter[str]] = field(
        default_factory=lambda: defaultdict(Counter)
    )
    # how labels were laid out in the text: "inline" vs "table"
    layout_counts: Counter[str] = field(default_factory=Counter)


def normalize_label(raw: str) -> str:
    return re.sub(r"\s+", " ", raw).strip().lower()


def first_word(label: str) -> str:
    match = WORD_RE.search(label)
    return match.group(0).lower() if match else ""


def is_known(label: str) -> bool:
    if label in ALL_KNOWN:
        return True
    return first_word(label) in ALL_KNOWN


def is_label_like(line: str) -> bool:
    """A short, digit-free line of 1-4 words, e.g. a lone 'Erstellt' table cell."""
    if any(ch.isdigit() for ch in line):
        return False
    if not LABEL_LINE_RE.match(line):
        return False
    return len(line.split()) <= 4


def read_pages(file_path: Path, max_pages: int) -> list[str]:
    pages: list[str] = []
    with fitz.open(file_path) as document:
        for index, page in enumerate(document):
            if index >= max_pages:
                break
            pages.append(page.get_text("text"))
    return pages


def collapse_lines(text: str) -> list[str]:
    lines: list[str] = []
    for line in text.splitlines():
        collapsed = re.sub(r"[ \t]+", " ", line).strip()
        if collapsed:
            lines.append(collapsed)
    return lines


def scan_file(file_path: Path, max_pages: int, agg: Aggregate) -> None:
    try:
        pages = read_pages(file_path, max_pages)
    except Exception as exc:  # noqa: BLE001 - report and continue
        agg.read_errors.append((str(file_path), str(exc)))
        return

    agg.pdf_count += 1
    found_known = False

    def record(label_raw: str, example: str, method: str) -> None:
        nonlocal found_known
        label = normalize_label(label_raw)
        if not label or not WORD_RE.search(label):
            return
        agg.label_counts[label] += 1
        agg.layout_counts[method] += 1
        if is_known(label):
            found_known = True
        examples = agg.label_examples[label]
        if len(examples) < 3 and example not in examples:
            examples.append(example)

    for page_text in pages:
        lowered = page_text.lower()

        # 1) Candidate vocabulary anywhere on the page.
        for group, words in CANDIDATE_VOCAB.items():
            for word in words:
                if word in lowered:
                    agg.vocab_hits[group][word] += 1

        # 2) Label discovery, line by line, covering three layouts.
        lines = collapse_lines(page_text)
        for idx, line in enumerate(lines):
            # (a) inline: "<Label> dd.mm.yyyy <name>" on a single line.
            inline = LABEL_BEFORE_DATE_RE.match(line)
            if inline:
                record(inline.group(1), line, "inline")
                continue

            # (b) colon: "<Label>: <value>" on a single line.
            colon = LABEL_COLON_RE.match(line)
            if colon:
                record(colon.group(1), line, "inline")
                continue

            # (c) table/vertical: a lone label line, with the date (and usually
            #     the name) on the following line(s). This is the common
            #     "Datum / Name / Unterschrift" approval-table layout.
            if is_label_like(line):
                next_line = lines[idx + 1] if idx + 1 < len(lines) else ""
                date_match = DATE_AT_START_RE.match(next_line)
                if not date_match:
                    continue
                name = next_line[date_match.end():].strip()
                if (
                    not name
                    and idx + 2 < len(lines)
                    and not DATE_RE.search(lines[idx + 2])
                    and not is_label_like(lines[idx + 2])
                ):
                    name = lines[idx + 2]
                example = f"{line} | {date_match.group(0)}"
                if name:
                    example += f" | {name}"
                record(line, example, "table")

    if found_known:
        agg.files_with_known += 1
    else:
        agg.files_without_known.append(str(file_path))


def build_json(agg: Aggregate) -> dict:
    discovered = []
    for label, count in agg.label_counts.most_common():
        discovered.append(
            {
                "label": label,
                "count": count,
                "known": is_known(label),
                "examples": agg.label_examples[label],
            }
        )
    return {
        "pdf_count": agg.pdf_count,
        "files_with_known_role": agg.files_with_known,
        "files_without_known_role": agg.files_without_known,
        "read_errors": [{"file": f, "error": e} for f, e in agg.read_errors],
        "layout_counts": dict(agg.layout_counts),
        "discovered_labels": discovered,
        "candidate_vocab_hits": {
            group: dict(counter.most_common())
            for group, counter in agg.vocab_hits.items()
        },
    }


def build_markdown(agg: Aggregate) -> str:
    lines: list[str] = []
    lines.append("# Role keyword discovery report\n")
    lines.append(f"- PDFs scanned: **{agg.pdf_count}**")
    lines.append(f"- Files with a known role label: **{agg.files_with_known}**")
    lines.append(
        f"- Files with NO known role label: **{len(agg.files_without_known)}**"
    )
    lines.append(f"- Read errors: **{len(agg.read_errors)}**")
    lines.append(
        f"- Label layouts: inline=**{agg.layout_counts.get('inline', 0)}**, "
        f"table=**{agg.layout_counts.get('table', 0)}**\n"
    )

    unknown = [
        (label, count)
        for label, count in agg.label_counts.most_common()
        if not is_known(label)
    ]
    known = [
        (label, count)
        for label, count in agg.label_counts.most_common()
        if is_known(label)
    ]

    lines.append("## Unknown labels to consider handling")
    lines.append("(label-before-date or `Label:` patterns not yet recognized)\n")
    if unknown:
        lines.append("| count | label | example |")
        lines.append("| ---: | --- | --- |")
        for label, count in unknown:
            example = (agg.label_examples[label] or [""])[0].replace("|", "\\|")
            lines.append(f"| {count} | `{label}` | {example} |")
    else:
        lines.append("_None found._")
    lines.append("")

    lines.append("## Known labels (already handled)\n")
    if known:
        lines.append("| count | label |")
        lines.append("| ---: | --- |")
        for label, count in known:
            lines.append(f"| {count} | `{label}` |")
    else:
        lines.append("_None found._")
    lines.append("")

    lines.append("## Candidate role vocabulary seen on pages\n")
    for group, counter in agg.vocab_hits.items():
        if not counter:
            continue
        hits = ", ".join(f"{word} ({count})" for word, count in counter.most_common())
        lines.append(f"- **{group}**: {hits}")
    if not any(agg.vocab_hits.values()):
        lines.append("_None found._")
    lines.append("")

    if agg.files_without_known:
        lines.append("## Files with no known role label\n")
        for path in agg.files_without_known:
            lines.append(f"- {path}")
        lines.append("")

    if agg.read_errors:
        lines.append("## Read errors\n")
        for path, error in agg.read_errors:
            lines.append(f"- {path}: {error}")
        lines.append("")

    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path, help="Root folder to scan (recursively)")
    parser.add_argument(
        "--pages",
        type=int,
        default=3,
        help="Number of leading pages to read per PDF (default: 3)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("role_keywords_report"),
        help="Output base name; writes <out>.md and <out>.json",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root: Path = args.folder
    if not root.exists() or not root.is_dir():
        sys.exit(f"Not a directory: {root}")

    agg = Aggregate()
    pdf_paths = sorted(p for p in root.rglob("*.pdf") if p.is_file())
    if not pdf_paths:
        sys.exit(f"No PDF files found under: {root}")

    for index, path in enumerate(pdf_paths, start=1):
        print(f"[{index}/{len(pdf_paths)}] {path}", file=sys.stderr)
        scan_file(path, args.pages, agg)

    md_path = args.out.with_suffix(".md")
    json_path = args.out.with_suffix(".json")
    md_path.write_text(build_markdown(agg), encoding="utf-8")
    json_path.write_text(
        json.dumps(build_json(agg), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(
        f"\nDone. Scanned {agg.pdf_count} PDFs.\n"
        f"  {len(agg.files_without_known)} file(s) had no known role label.\n"
        f"  Report: {md_path}\n"
        f"  Data:   {json_path}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
