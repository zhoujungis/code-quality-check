#!/usr/bin/env python3
"""Code quality scan helper.

Usage:
    python3 scan.py <target_dir> [--run] [--max-files N] [--timeout S]

Modes:
    default : identify languages, count files/lines, list which lint tools
              are available in PATH. Prints JSON to stdout.
    --run   : additionally execute available tools against the target and
              include their raw findings (truncated) in the JSON output.

The agent reads this JSON to decide what to analyze further with AI review.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

# ---------------------------------------------------------------- extensions
LANG_MAP = {
    ".py": "Python", ".pyi": "Python",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".c": "C", ".h": "C/C++ Header",
    ".cpp": "C++", ".cc": "C++", ".cxx": "C++", ".hpp": "C++",
    ".cs": "C#",
    ".rb": "Ruby",
    ".php": "PHP",
    ".swift": "Swift", ".kt": "Kotlin", ".kts": "Kotlin",
    ".scala": "Scala",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell",
    ".sql": "SQL",
    ".vue": "Vue", ".svelte": "Svelte",
    ".html": "HTML", ".css": "CSS", ".scss": "CSS", ".less": "CSS",
}

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "bower_components", "vendor",
    "__pycache__", ".venv", "venv", "env", ".tox", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "dist", "build", "target", "out",
    "coverage", ".next", ".nuxt", ".cache", ".idea", ".vscode", "bin", "obj",
    "site-packages", ".gradle", ".terraform",
}

# tool -> (executable probe list, languages it covers)
TOOLS = {
    "ruff":         (["ruff"], {"Python"}),
    "flake8":       (["flake8"], {"Python"}),
    "pylint":       (["pylint"], {"Python"}),
    "bandit":       (["bandit"], {"Python"}),
    "mypy":         (["mypy"], {"Python"}),
    "eslint":       (["eslint"], {"JavaScript", "TypeScript", "Vue"}),
    "tsc":          (["tsc"], {"TypeScript"}),
    "prettier":     (["prettier"], {"JavaScript", "TypeScript", "CSS", "HTML"}),
    "golangci-lint": (["golangci-lint"], {"Go"}),
    "gofmt":        (["gofmt"], {"Go"}),
    "go vet":       (["go"], {"Go"}),
    "clippy":       (["cargo-clippy", "clippy"], {"Rust"}),
    "cppcheck":     (["cppcheck"], {"C", "C++"}),
    "clang-tidy":   (["clang-tidy"], {"C", "C++"}),
    "shellcheck":   (["shellcheck"], {"Shell"}),
    "checkstyle":   (["checkstyle"], {"Java"}),
    "semgrep":      (["semgrep"], None),  # None = all languages
    "trufflehog":   (["trufflehog"], None),
}

# commands actually executed in --run mode: tool -> command template.
# {target} is replaced with the target directory. Return code != 0 is normal
# (linters exit non-zero when findings exist).
RUN_CMDS = {
    "ruff":        ["ruff", "check", "--output-format", "concise", "{target}"],
    "flake8":      ["flake8", "--max-line-length=120", "--count", "{target}"],
    "pylint":      ["pylint", "--recursive=y", "--score=y", "--disable=missing-docstring", "{target}"],
    "bandit":      ["bandit", "-r", "-f", "txt", "{target}"],
    "eslint":      ["npx", "--no-install", "eslint", "{target}"],
    "gofmt":       ["gofmt", "-l", "{target}"],
    "shellcheck":  None,  # per-file, handled specially
    "cppcheck":    ["cppcheck", "--enable=warning,style", "--quiet", "{target}"],
    "semgrep":     None,  # skipped by default: slow; agent runs on demand
    "trufflehog":  None,  # skipped by default; agent runs on demand
}

MAX_OUTPUT_CHARS = 30000


def iter_code_files(target, max_files):
    count = 0
    for root, dirs, files in os.walk(target):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in sorted(files):
            ext = os.path.splitext(f)[1].lower()
            if ext in LANG_MAP:
                count += 1
                if count > max_files:
                    return
                yield os.path.join(root, f), ext


def collect_stats(target, max_files):
    langs = {}
    big_files = []
    for path, ext in iter_code_files(target, max_files):
        lang = LANG_MAP[ext]
        try:
            with open(path, "rb") as fh:
                data = fh.read()
            lines = data.count(b"\n") + (0 if data.endswith(b"\n") or not data else 1)
        except OSError:
            lines = 0
        entry = langs.setdefault(lang, {"files": 0, "lines": 0})
        entry["files"] += 1
        entry["lines"] += lines
        if lines > 500:
            big_files.append({"file": os.path.relpath(path, target), "lines": lines})
    big_files.sort(key=lambda x: -x["lines"])
    return langs, big_files[:20]


def detect_tools(langs):
    present, missing = {}, []
    needed_langs = set(langs)
    for tool, (probes, tool_langs) in TOOLS.items():
        if tool_langs is not None and not (needed_langs & tool_langs):
            continue
        exe = next((p for p in probes if shutil.which(p)), None)
        if exe:
            present[tool] = exe
        else:
            missing.append(tool)
    return present, missing


def run_tool(tool, exe, target, files_by_lang, timeout):
    cmd = RUN_CMDS.get(tool)
    out = ""
    if tool == "shellcheck":
        for f in files_by_lang.get("Shell", [])[:50]:
            r = subprocess.run([exe, "-f", "gcc", f], capture_output=True, text=True, timeout=timeout)
            out += r.stdout + r.stderr
    elif cmd is not None:
        full = [exe if c in (tool.split()[0],) else c for c in cmd]
        # replace first element with resolved exe path
        full[0] = exe
        full = [target if a == "{target}" else a for a in full]
        try:
            r = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
            out = r.stdout + r.stderr
        except subprocess.TimeoutExpired:
            out = f"[scan.py] tool '{tool}' timed out after {timeout}s"
        except Exception as e:  # noqa: BLE001
            out = f"[scan.py] tool '{tool}' failed: {e}"
    else:
        return None
    out = out.strip()
    if len(out) > MAX_OUTPUT_CHARS:
        out = out[:MAX_OUTPUT_CHARS] + "\n...[truncated]"
    return out or "[no findings]"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target")
    ap.add_argument("--run", action="store_true", help="also execute available tools")
    ap.add_argument("--max-files", type=int, default=20000)
    ap.add_argument("--timeout", type=int, default=120, help="per-tool timeout seconds")
    args = ap.parse_args()

    target = os.path.abspath(args.target)
    if not os.path.isdir(target):
        print(json.dumps({"error": f"not a directory: {target}"}))
        sys.exit(1)

    langs, big_files = collect_stats(target, args.max_files)
    present, missing = detect_tools(langs)

    result = {
        "target": target,
        "languages": langs,
        "large_files_over_500_lines": big_files,
        "tools_available": present,
        "tools_missing": missing,
    }

    if args.run:
        files_by_lang = {}
        for path, ext in iter_code_files(target, args.max_files):
            files_by_lang.setdefault(LANG_MAP[ext], []).append(path)
        findings = {}
        for tool in present:
            out = run_tool(tool, present[tool], target, files_by_lang, args.timeout)
            if out is not None:
                findings[tool] = out
        result["tool_findings"] = findings

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
