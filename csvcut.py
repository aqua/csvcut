#!/usr/bin/env python3
"""csvcut - cut(1) for CSV files.

Selects columns from CSV files using the -f / --fields option.
"""

import argparse
import csv
import os
import re
import signal
import sys

# Safely set csv field size limit to the maximum supported on this platform
max_limit = sys.maxsize
while True:
    try:
        csv.field_size_limit(max_limit)
        break
    except OverflowError:
        max_limit = int(max_limit / 10)


def tokenize_field_spec(spec: str) -> list[str]:
    """Tokenize a field specification string into individual range tokens.

    Supports comma-separated and whitespace-separated range tokens.
    Empty tokens (e.g. from leading, trailing, or double commas) are preserved
    as empty strings so they can be flagged as parse errors matching cut(1).
    """
    if not spec:
        return [""]

    if "," in spec:
        parts = spec.split(",")
        tokens = []
        for p in parts:
            stripped = p.strip()
            if not stripped:
                tokens.append("")
            else:
                tokens.extend(stripped.split())
        return tokens
    else:
        parts = spec.split()
        if not parts:
            return [""]
        return parts


def parse_field_spec(spec: str, selection_order: bool = False):
    """Parse cut-style field specification LIST.

    If selection_order is False (default cut(1) behavior):
        Returns a sorted list of merged non-overlapping (start, end) intervals (1-indexed, inclusive).
    If selection_order is True:
        Returns a list of parsed items in the exact order specified in -f:
        ('exact', N), ('range', start, end), or ('suffix', start).

    Raises ValueError with cut(1)-compatible error messages on invalid input.
    """
    tokens = tokenize_field_spec(spec)
    items: list[tuple] = []

    for token in tokens:
        if token == "-":
            raise ValueError(f"range '{token}' was invalid: invalid range with no endpoint")

        # N-M
        m = re.fullmatch(r"(\d+)-(\d+)", token)
        if m:
            start = int(m.group(1))
            end = int(m.group(2))
            if start == 0 or end == 0:
                raise ValueError(f"range '{token}' was invalid: fields and positions are numbered from 1")
            if start > end:
                raise ValueError(f"range '{token}' was invalid: high end of range less than low end")
            items.append(("range", start, end))
            continue

        # -M (equivalent to 1-M)
        m = re.fullmatch(r"-(\d+)", token)
        if m:
            end = int(m.group(1))
            if end == 0:
                raise ValueError(f"range '{token}' was invalid: fields and positions are numbered from 1")
            items.append(("range", 1, end))
            continue

        # N- (N to end of line)
        m = re.fullmatch(r"(\d+)-", token)
        if m:
            start = int(m.group(1))
            if start == 0:
                raise ValueError(f"range '{token}' was invalid: fields and positions are numbered from 1")
            items.append(("suffix", start))
            continue

        # N
        m = re.fullmatch(r"(\d+)", token)
        if m:
            idx = int(m.group(1))
            if idx == 0:
                raise ValueError(f"range '{token}' was invalid: fields and positions are numbered from 1")
            items.append(("exact", idx))
            continue

        # Any unrecognized format or empty string
        raise ValueError(f"range '{token}' was invalid: failed to parse range")

    if selection_order:
        return items

    # Merge overlapping or adjacent intervals for default cut(1) behavior
    raw_intervals: list[tuple[int, float]] = []
    for item in items:
        if item[0] == "exact":
            raw_intervals.append((item[1], item[1]))
        elif item[0] == "range":
            raw_intervals.append((item[1], item[2]))
        elif item[0] == "suffix":
            raw_intervals.append((item[1], float("inf")))

    if not raw_intervals:
        return []

    sorted_intervals = sorted(raw_intervals, key=lambda x: (x[0], x[1]))
    merged: list[tuple[int, float]] = []
    curr_start, curr_end = sorted_intervals[0]

    for start, end in sorted_intervals[1:]:
        if start <= curr_end + 1:
            if end > curr_end:
                curr_end = end
        else:
            merged.append((curr_start, curr_end))
            curr_start, curr_end = start, end
    merged.append((curr_start, curr_end))

    return merged


def extract_fields(row: list[str], intervals: list[tuple[int, float]]) -> list[str]:
    """Extract fields from a row according to 1-indexed intervals in line order."""
    n = len(row)
    if n == 0:
        return []

    result: list[str] = []
    for start, end in intervals:
        if start > n:
            break
        s_idx = start - 1
        e_idx = min(int(end), n) if end != float("inf") else n
        result.extend(row[s_idx:e_idx])
    return result


def extract_fields_ordered(row: list[str], items: list[tuple]) -> list[str]:
    """Extract fields from a row in the order specified by field selection items."""
    n = len(row)
    if n == 0:
        return []

    result: list[str] = []
    for item in items:
        kind = item[0]
        if kind == "exact":
            idx = item[1]
            if 1 <= idx <= n:
                result.append(row[idx - 1])
        elif kind == "range":
            start, end = item[1], item[2]
            if start <= n:
                e_idx = min(end, n)
                result.extend(row[start - 1 : e_idx])
        elif kind == "suffix":
            start = item[1]
            if start <= n:
                result.extend(row[start - 1 :])
    return result


def process_stream(stream, writer, selector, selection_order: bool = False) -> None:
    """Read CSV from stream and write cut fields to writer."""
    reader = csv.reader(stream)
    if selection_order:
        for row in reader:
            writer.writerow(extract_fields_ordered(row, selector))
    else:
        for row in reader:
            writer.writerow(extract_fields(row, selector))


def main() -> int:
    # Set SIGPIPE default handler to prevent unhandled BrokenPipeError tracebacks
    if hasattr(signal, "SIGPIPE"):
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)

    # Reconfigure streams to preserve binary/surrogate sequences if possible
    if hasattr(sys.stdin, "reconfigure"):
        try:
            sys.stdin.reconfigure(errors="surrogateescape")
        except Exception:
            pass
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(errors="surrogateescape")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        prog="csvcut",
        description="Select columns from CSV files, like cut(1) but for CSV.",
        add_help=True,
    )
    parser.add_argument(
        "-f", "--fields",
        dest="fields",
        default=None,
        help="select only these fields (e.g. 1, 1-3, 2-, -3, or comma-separated combinations)",
    )
    parser.add_argument(
        "-O", "--selection-order", "--preserve-order",
        dest="selection_order",
        action="store_true",
        default=False,
        help="emit fields in the order they appeared in the -f argument",
    )
    parser.add_argument(
        "files",
        nargs="*",
        default=["-"],
        help="input CSV file(s) (default: '-' for standard input)",
    )

    args = parser.parse_args()

    if args.fields is None:
        sys.stderr.write("csvcut: invalid usage: expects --fields (-f)\n")
        return 1

    try:
        selector = parse_field_spec(args.fields, selection_order=args.selection_order)
    except ValueError as e:
        sys.stderr.write(f"csvcut: {e}\n")
        return 1

    writer = csv.writer(sys.stdout, lineterminator="\n")
    exit_code = 0

    try:
        for filename in args.files:
            if filename == "-":
                try:
                    process_stream(sys.stdin, writer, selector, selection_order=args.selection_order)
                except csv.Error as e:
                    sys.stderr.write(f"csvcut: stdin: {e}\n")
                    exit_code = 1
            else:
                try:
                    with open(filename, "r", encoding="utf-8", errors="surrogateescape", newline="") as f:
                        process_stream(f, writer, selector, selection_order=args.selection_order)
                except OSError as e:
                    sys.stderr.write(f"csvcut: {filename}: {e.strerror}\n")
                    exit_code = 1
                except csv.Error as e:
                    sys.stderr.write(f"csvcut: {filename}: {e}\n")
                    exit_code = 1
    except BrokenPipeError:
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except Exception:
            pass
        return 141

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
