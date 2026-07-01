"""Text quality checker — detects UTF-8 decode errors, mojibake, and broken Chinese.

Usage: python scripts/check_text_quality.py [--fix]
  --check (default): report issues only
  --fix: attempt to fix detected issues (NOT IMPLEMENTED in v1 — manual review needed)
"""

import os
import re
import sys
from pathlib import Path

# Force UTF-8 output on Windows (PowerShell/cmd default to GBK)
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent

# Directories to scan
SCAN_DIRS = ["src", "tests", "scripts", "docs"]

# File extensions to check
SCAN_EXTS = {".py", ".ts", ".tsx", ".md", ".json", ".html", ".css", ".ps1", ".sh", ".txt", ".yml", ".yaml", ".toml"}

# Patterns that indicate encoding problems
MOJIBAKE_PATTERNS = [
    (re.compile(r"锟斤拷|銆�|鈥�|鈥檙|鍚�|鏄�"), "common mojibake (GBK->UTF-8 misdecode)"),
    (re.compile(r"Ã©|â|â|â"), "Latin-1 mojibake (UTF-8 bytes in Latin-1)"),
    (re.compile(r"ç§»å¨|ææ¥"), "Chinese mojibake"),
]

# Unicode replacement character
REPLACEMENT_CHAR = "�"

# Minimum expected Chinese character content for UI files
CHINESE_CHAR_RE = re.compile(r"[一-鿿]+")


def check_file(filepath: Path) -> list[dict]:
    """Check a single file for encoding and text quality issues."""
    issues = []
    try:
        content = filepath.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        issues.append({
            "file": str(filepath.relative_to(ROOT)),
            "line": 0,
            "type": "utf8_decode_error",
            "detail": str(e),
        })
        return issues

    # Check for replacement character
    lines = content.split("\n")
    for i, line in enumerate(lines, 1):
        if REPLACEMENT_CHAR in line:
            issues.append({
                "file": str(filepath.relative_to(ROOT)),
                "line": i,
                "type": "replacement_char",
                "detail": line.strip()[:120],
            })

        # Check for mojibake patterns
        for pattern, desc in MOJIBAKE_PATTERNS:
            if pattern.search(line):
                issues.append({
                    "file": str(filepath.relative_to(ROOT)),
                    "line": i,
                    "type": "mojibake",
                    "detail": f"{desc}: {line.strip()[:120]}",
                })
                break  # one mojibake per line is enough

    # Check for suspiciously short/empty user-facing strings
    # Only for .tsx/.html files
    if filepath.suffix in {".tsx", ".html"}:
        for i, line in enumerate(lines, 1):
            # Empty placeholder or TODO markers
            if re.search(r"(?:placeholder|title|label|alt)\s*=\s*[\"']\s*[\"']", line):
                issues.append({
                    "file": str(filepath.relative_to(ROOT)),
                    "line": i,
                    "type": "empty_ui_string",
                    "detail": line.strip()[:120],
                })

    return issues


def main():
    check_only = "--fix" not in sys.argv

    all_issues = []
    for scan_dir in SCAN_DIRS:
        dir_path = ROOT / scan_dir
        if not dir_path.exists():
            continue
        for filepath in dir_path.rglob("*"):
            if filepath.suffix.lower() not in SCAN_EXTS:
                continue
            # Skip node_modules, dist, .vite, __pycache__, .pytest_cache
            parts = filepath.parts
            skip = False
            for skip_dir in ("node_modules", "dist", ".vite", "__pycache__", ".pytest_cache", ".runtime"):
                if skip_dir in parts:
                    skip = True
                    break
            if skip:
                continue

            issues = check_file(filepath)
            all_issues.extend(issues)
            for issue in issues:
                print(f"{issue['file']}:{issue['line']} [{issue['type']}] {issue['detail']}")

    # Summary
    by_type = {}
    for issue in all_issues:
        by_type.setdefault(issue["type"], 0)
        by_type[issue["type"]] += 1

    print(f"\n=== 编码质量检查完成 ===")
    print(f"共发现 {len(all_issues)} 个问题")
    for t, count in sorted(by_type.items()):
        print(f"  [{t}]: {count}")

    if check_only:
        print("(仅检查模式，未修改文件。使用 --fix 需人工审核。)")
    else:
        print("(自动修复未实现，请手动修复后重新运行检查。)")

    return 0 if not all_issues else 1


if __name__ == "__main__":
    sys.exit(main())
