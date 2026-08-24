# HakusAgent Skills

This directory is the workspace-local skill library for HakusCLI. It is not a
desktop application asset directory: the Tauri desktop client does not load
these files directly.

HakusCLI recursively discovers any directory containing `SKILL.md`, so skills
are grouped by purpose while each skill keeps its own scripts, references,
templates, and other companion files.

## Categories

| Directory | Contents |
| --- | --- |
| `core/` | Skill authoring, planning, task review, tracking, and workflow helpers |
| `development/` | Coding, full-stack work, and browser automation |
| `research/` | Academic search, news, web search/reading, and research reports |
| `documents/` | Charts, DOCX, PDF, PPTX, and spreadsheet workflows |
| `media/` | Image, video, audio, language-model, and shader workflows |
| `education/` | College admissions, quizzes, and study workflows |
| `content/` | Blog, SEO, marketing, market reports, and storyboard workflows |
| `career/` | Interview, resume, job-search, and profile workflows |
| `lifestyle/` | Finance, investing, wellness, gift, fortune, and dream workflows |
| `design/` | Design system, template, style, and UI/UX workflows |

## Which Client Uses What?

- `skills/`: workspace-local skills visible to CLI/TUI when HakusCLI is run
  with this repository as its workspace.
- `frontend/terminal/crates/tui/assets/skills/`: the smaller skill pack bundled
  into the CLI binary.
- `frontend/desktop-tauri/`: currently has no direct skill loader; desktop and
  CLI do not share this directory automatically.

The skill manager can still import selected skills into the CLI-owned project
or global roots. This repository copy remains read-only from the manager's
perspective and is intended to be versioned with the project.
