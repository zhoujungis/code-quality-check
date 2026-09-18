# Code Quality Check

A two-level code analysis skill (linting tools + AI review) that produces Markdown quality reports with a 0-100 score.

## Supported Languages

Python, JavaScript/TypeScript, Java, Go, Rust, C/C++, Shell, and more — automatically detected by file type.

## Workflow

1. **Scan** — `scripts/scan.py` identifies languages, counts files/lines, detects and runs available lint tools
2. **Install missing tools** (optional) — install recommended tools and re-run
3. **AI deep review** — AI reads code to catch what tools miss (security, correctness, maintainability, style, engineering)
4. **Score & report** — weighted 5-dimension scoring with A-F rating and prioritized issue list

## Usage

Designed as a [Command Code](https://commandcode.ai) Skill. Trigger phrases:

- "code quality check"
- "lint this project"
- "code review"
- "check my code for issues"
- "code scoring"

## Project Structure

```
.
├── SKILL.md                    # Skill definition and workflow
├── scripts/
│   └── scan.py                 # Scanner (language detection, tool execution)
└── references/
    ├── rubric.md               # Scoring rubric and grade mapping
    └── report-template.md      # Report output template
```

## Notes

- Read-only by default — does not modify code unless explicitly asked
- Every issue includes `file:line` location
- Hardcoded secrets are reported by location/type only, never by value
