# Changelog

All notable changes to the HakusAI project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- CI/CD quality gates (`.github/workflows/quality.yml`)
  - Python backend lint + type check (ruff, mypy)
  - Frontend TypeScript type check + build verification
  - Playwright E2E tests (optional)
  - File size monitoring (500 line limit)
  - Security scanning for dependencies
- Pre-commit hooks configuration (`.pre-commit-config.yaml`)
- Version management file (`VERSION.txt`)
- Refactoring plan document (`REFACTOR_PLAN.md`)
- Dead code cleanup checklist (`DEAD_CODE_CLEANUP.md`)

### Changed
- Updated `.gitignore` to exclude build artifacts and nested copies

### Deprecated
- `hakus/tui.py` — marked as legacy, use `hakus.tui_v2` instead
- `hakus/enhanced_agent.py` — deprecated, will be removed in v0.3.0
- `hakus/improved_client.py` — deprecated, will be removed in v0.3.0
- `hakus/improved_loop.py` — deprecated, will be removed in v0.3.0

### Removed
- (Pending cleanup per `DEAD_CODE_CLEANUP.md`)

### Fixed
- (To be documented)

### Security
- (To be documented)

---

## [0.2.0] - 2025-01-XX

### Added
- TUI v2 with modern Textual-based interface
- MCP (Model Context Protocol) client support
- System tray and global hotkeys (Shift+Ctrl/Cmd+H)
- Electron auto-update via GitHub Releases
- Data backup functionality (export ~/.hakus snapshot)
- New built-in tools: git_diff, apply_patch, todo_write
- Grep tool now uses ripgrep for large repository performance
- HakusAI server sidecar bundled with Electron app

### Changed
- Upgraded to Electron 25+ with electron-builder
- Improved permission system with dual-layer defense
- Refactored model client architecture

### Fixed
- Fixed race condition in nightly release uploads
- Resolved artifact storage quota issues by direct Release upload

---

## [0.1.0] - 2024-XX-XX

### Added
- Initial release
- Core Agent architecture with LLM integration
- Tool execution framework (24 built-in tools)
- Memory system (short-term + long-term + vector)
- Multi-model support (DeepSeek, GLM, Qwen, OpenAI, etc.)
- Permission system with ASK/DENY/ALLOW modes
- WebSocket VTuber integration
- Live2D avatar support
- Web UI (Vue.js based)
- Desktop client (Electron based)

---

## Version History

| Version | Date | Description |
|---------|------|-------------|
| 0.2.0 | 2025-01-XX | TUI v2, MCP, Auto-update |
| 0.1.0 | 2024-XX-XX | Initial release |

---

## Upgrade Notes

### From 0.1.x to 0.2.0
- No breaking changes expected
- Recommended: run `pre-commit install` after pulling
- Check `DEAD_CODE_CLEANUP.md` for files safe to delete

---

## Links

- **Releases**: [GitHub Releases](../../releases)
- **Roadmap**: See `REFACTOR_PLAN.md` for upcoming refactoring
- **Contributing**: See development setup below

---

## Development Notes

### How to Update This File

1. Add new entries under `[Unreleased]` section
2. When releasing a version:
   - Change `[Unreleased]` to `[version] - date`
   - Create new `[Unreleased]` section at top
   - Update `VERSION.txt`

### Version Bump Checklist

- [ ] Update `VERSION.txt`
- [ ] Update this CHANGELOG.md
- [ ] Update `frontend/client/package.json` version
- [ ] Create git tag: `git tag v0.x.x`
- [ ] Push tag: `git push origin v0.x.x`
- [ ] CI will automatically build and create Release

---

[Unreleased]: https://github.com/your-org/HakusAgent/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/your-org/HakusAgent/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/your-org/HakusAgent/releases/tag/v0.1.0
