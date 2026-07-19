#!/usr/bin/env python3
"""Generate electron-updater manifest YAML files (latest*.yml) after a build.

Why this script exists
-----------------------
We removed the static `build.publish` block from package.json because
electron-builder 25.x with `publish` + `deb` target triggers a buggy
"adding autoupdate files for: deb (Beta feature)" step that crashes the
packaging with `ERR_ELECTRON_BUILDER_CANNOT_EXECUTE` (exit code null)
on all 3 CI platforms (Windows/macOS/Linux).

Without `publish`, electron-builder no longer auto-generates
`latest.yml` / `latest-mac.yml` / `latest-linux.yml` either. But
electron-updater NEEDS those files (uploaded to the GitHub Release as
assets) to discover new versions at runtime.

So we generate them manually here. The format mirrors what
electron-builder would emit:

    version: <semver>
    files:
      - url: <installer filename>
        sha512: <base64-encoded sha512>
        size: <bytes>
    path: <primary installer filename>
    sha512: <base64-encoded sha512>
    releaseDate: '<ISO-8601 UTC>'

Usage
-----
    python3 scripts/generate-update-manifests.py --version 0.1.0 \\
        --release-dir release/

The script autodetects the platform installers present in `--release-dir`
and writes the matching `latest*.yml` files next to them:

    HakusAI-Setup-*.exe           → latest.yml
    HakusAI-*-x64.dmg / arm64.dmg → latest-mac.yml
    HakusAI-*.AppImage             → latest-linux.yml

If a platform's installer is missing, that platform's yml is skipped
(prints a warning). This is intentional so a single-platform CI job can
run the script safely.

Exit codes
----------
    0  — at least one yml was written
    1  — no installers found at all (probably wrong --release-dir)
    2  — bad CLI args
"""
from __future__ import annotations

import argparse
import base64
import datetime
import glob
import hashlib
import os
import sys
from typing import Iterable


def sha512_b64(path: str) -> str:
    """Return base64-encoded sha512 of the file (matches electron-builder format)."""
    h = hashlib.sha512()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return base64.b64encode(h.digest()).decode("ascii")


def file_size(path: str) -> int:
    return os.path.getsize(path)


def iso_now() -> str:
    """ISO-8601 UTC timestamp with milliseconds, like electron-builder emits."""
    # 2024-01-15T12:34:56.789Z
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.datetime.now(datetime.timezone.utc).microsecond // 1000:03d}Z"


def write_yml(out_path: str, version: str, files: list[dict], primary_path: str, primary_sha: str,
              primary_size: int, release_date: str) -> None:
    """Write a latest*.yml file in the format electron-updater expects."""
    # electron-builder uses single quotes around the releaseDate string and
    # indents files list with 2 spaces under `files:`.
    lines = [
        f"version: {version}",
        "files:",
    ]
    for f in files:
        lines.append(f"  - url: {f['url']}")
        lines.append(f"    sha512: {f['sha512']}")
        lines.append(f"    size: {f['size']}")
    lines.append(f"path: {primary_path}")
    lines.append(f"sha512: {primary_sha}")
    lines.append(f"releaseDate: '{release_date}'")
    with open(out_path, "w", encoding="utf-8", newline="\n") as fp:
        fp.write("\n".join(lines) + "\n")
    print(f"[manifest] wrote {out_path} ({len(files)} file(s))")


def find_installers(release_dir: str) -> dict[str, list[str]]:
    """Find installer files by platform. Returns {'win': [...], 'mac': [...], 'linux': [...]}.

    Patterns supported (each tried in order, then recursive fallback):
      Windows:
        - HakusAI-Setup-*.exe     (electron-builder default, mixed-case productName)
        - HakusAI-setup-*.exe     (lowercase productName variant)
        - HakusAI Setup *.exe     (alt template with space, just in case)
        - HakusAI-*.exe           (catch-all)
      macOS:
        - HakusAI-*.dmg
      Linux:
        - HakusAI-*.AppImage
        - HakusAI-*.deb           (collected but not used as auto-update primary)
    """
    found: dict[str, list[str]] = {"win": [], "mac": [], "linux": []}

    # ─── Windows: try top-level first, then recursive ──────────────────
    win_patterns = [
        "HakusAI-Setup-*.exe",
        "HakusAI-setup-*.exe",
        "HakusAI Setup *.exe",
        "HakusAI-*.exe",
    ]
    for pat in win_patterns:
        matches = glob.glob(os.path.join(release_dir, pat))
        if matches:
            found["win"].extend(matches)
            break
    # Recursive fallback — covers nested output dirs that some CI setups produce.
    if not found["win"]:
        for p in glob.glob(os.path.join(release_dir, "**", "*.exe"), recursive=True):
            # Skip the uninstaller helper and any __uninstaller-*.exe intermediates.
            base = os.path.basename(p)
            if base.startswith("__uninstaller"):
                continue
            # Skip small helper exes (<5MB) — NSIS installers are typically 60+ MB.
            if file_size(p) < 5_000_000:
                continue
            found["win"].append(p)

    # ─── macOS ─────────────────────────────────────────────────────────
    for p in glob.glob(os.path.join(release_dir, "HakusAI-*.dmg")):
        found["mac"].append(p)
    if not found["mac"]:
        for p in glob.glob(os.path.join(release_dir, "**", "*.dmg"), recursive=True):
            found["mac"].append(p)

    # ─── Linux ─────────────────────────────────────────────────────────
    for p in glob.glob(os.path.join(release_dir, "HakusAI-*.AppImage")):
        found["linux"].append(p)
    if not found["linux"]:
        for p in glob.glob(os.path.join(release_dir, "**", "*.AppImage"), recursive=True):
            found["linux"].append(p)

    # Dedupe (recursive glob may double-count when a file is also matched by a
    # top-level pattern).
    for k in found:
        seen = set()
        uniq = []
        for p in found[k]:
            rp = os.path.realpath(p)
            if rp not in seen:
                seen.add(rp)
                uniq.append(p)
        found[k] = uniq

    return found


def dump_release_dir(release_dir: str) -> None:
    """Print every file under release/ to stderr — used when no installers found,
    so CI logs show what electron-builder actually produced."""
    print(f"[manifest] dump of {release_dir}:", file=sys.stderr)
    if not os.path.isdir(release_dir):
        print(f"  (dir does not exist)", file=sys.stderr)
        return
    file_count = 0
    for root, dirs, files in os.walk(release_dir):
        rel = os.path.relpath(root, release_dir)
        prefix = "." if rel == "." else rel
        for f in sorted(files):
            full = os.path.join(root, f)
            try:
                sz = os.path.getsize(full)
            except OSError:
                sz = -1
            print(f"  {prefix}/{f}  ({sz} bytes)", file=sys.stderr)
            file_count += 1
        if not files and not dirs:
            print(f"  {prefix}/  (empty)", file=sys.stderr)
    print(f"[manifest] total {file_count} file(s) under {release_dir}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate electron-updater latest*.yml manifests."
    )
    parser.add_argument(
        "--version",
        required=True,
        help="App version (e.g. 0.1.0). Must match package.json.",
    )
    parser.add_argument(
        "--release-dir",
        default="release",
        help="Directory containing the built installers (default: release).",
    )
    args = parser.parse_args()

    release_dir = os.path.abspath(args.release_dir)
    if not os.path.isdir(release_dir):
        print(f"[manifest] ERROR: release dir does not exist: {release_dir}", file=sys.stderr)
        return 1

    installers = find_installers(release_dir)
    if not any(installers.values()):
        print(f"[manifest] ERROR: no installers found in {release_dir}", file=sys.stderr)
        # Dump everything under release/ to stderr so CI logs show what
        # electron-builder actually produced (or didn't).
        dump_release_dir(release_dir)
        return 1

    release_date = iso_now()
    yml_written = 0

    # ─── latest.yml (Windows / NSIS) ────────────────────────────────────
    if installers["win"]:
        # Pick the largest .exe as primary (Setup is the only one we ship).
        primary = max(installers["win"], key=file_size)
        primary_name = os.path.basename(primary)
        primary_sha = sha512_b64(primary)
        primary_size = file_size(primary)
        files_list = []
        for p in installers["win"]:
            files_list.append({
                "url": os.path.basename(p),
                "sha512": sha512_b64(p),
                "size": file_size(p),
            })
        write_yml(
            os.path.join(release_dir, "latest.yml"),
            args.version,
            files_list,
            primary_name,
            primary_sha,
            primary_size,
            release_date,
        )
        yml_written += 1
    else:
        print("[manifest] skip latest.yml — no Windows installers found")

    # ─── latest-mac.yml (macOS / DMG) ───────────────────────────────────
    if installers["mac"]:
        # If both x64 and arm64 dmgs exist, list both. Primary = first sorted.
        sorted_macs = sorted(installers["mac"])
        primary = sorted_macs[0]
        primary_name = os.path.basename(primary)
        primary_sha = sha512_b64(primary)
        primary_size = file_size(primary)
        files_list = []
        for p in sorted_macs:
            files_list.append({
                "url": os.path.basename(p),
                "sha512": sha512_b64(p),
                "size": file_size(p),
            })
        write_yml(
            os.path.join(release_dir, "latest-mac.yml"),
            args.version,
            files_list,
            primary_name,
            primary_sha,
            primary_size,
            release_date,
        )
        yml_written += 1
    else:
        print("[manifest] skip latest-mac.yml — no macOS installers found")

    # ─── latest-linux.yml (Linux / AppImage) ────────────────────────────
    if installers["linux"]:
        primary = installers["linux"][0]
        primary_name = os.path.basename(primary)
        primary_sha = sha512_b64(primary)
        primary_size = file_size(primary)
        files_list = []
        for p in installers["linux"]:
            files_list.append({
                "url": os.path.basename(p),
                "sha512": sha512_b64(p),
                "size": file_size(p),
            })
        write_yml(
            os.path.join(release_dir, "latest-linux.yml"),
            args.version,
            files_list,
            primary_name,
            primary_sha,
            primary_size,
            release_date,
        )
        yml_written += 1
    else:
        print("[manifest] skip latest-linux.yml — no Linux installers found")

    if yml_written == 0:
        print("[manifest] ERROR: wrote 0 yml files", file=sys.stderr)
        return 1

    print(f"[manifest] done — {yml_written} manifest(s) written to {release_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
