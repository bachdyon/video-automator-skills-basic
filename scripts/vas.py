#!/usr/bin/env python3
"""VAS edition tooling.

Commands:
  publish basic        Export the basic.toml allowlist and push it to the public Basic repository.
  publish              Publish Premium: push this repository and build the upgrade ZIP.
  upgrade <zip>        Upgrade Basic to Premium (or update Premium) from a Premium ZIP.
  upgrade --rollback   Restore the state before the latest upgrade.
  doctor               Check that the installation works.

Standard library only (Python 3.11+).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

if sys.version_info < (3, 11):
    sys.exit("VAS needs Python 3.11 or newer (for tomllib).")

import tomllib

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_REL = ".vas/manifest.json"
BASIC_CONFIG = "basic.toml"
VERSION_FILE = "VERSION"
CUSTOMS_FILE = "AGENTS.customs.md"
MARKER_START = "<!-- premium:start -->"
MARKER_END = "<!-- premium:end -->"
# Basic-only text: kept (markers removed) in the Basic export, cut from the Premium ZIP.
BASIC_START = "<!-- basic:start -->"
BASIC_END = "<!-- basic:end -->"

# Never written or deleted by an upgrade (created only when missing).
PROTECTED_PREFIXES = (
    "customs/",
    "jobs/",
    "raw_assets/",
    ".asset_index/",
    "voice_profiles/",
    "sfx/",
    "exports/",
    "node_modules/",
    ".git/",
    ".vas/",
    ".venv/",
)
PROTECTED_FILES = (CUSTOMS_FILE,)

# Generated or local-only folder names that never ship.
EXCLUDED_DIR_NAMES = {"node_modules", "build", "out", "output", ".remotion", "dist", "__pycache__", ".pytest_cache"}
EXCLUDED_FILE_NAMES = {".DS_Store"}

# Folders whose symlinks mirror skills for agent auto-discovery.
SYMLINK_MIRRORS = (".claude/skills", ".junie/skills")

# Files where Premium-only list lines (`- `$skill``, `- `templates/<id>/``) are dropped for Basic.
ROUTER_FILES = {"AGENTS.md", "README.md"}

TEXT_SUFFIXES = {
    ".md", ".mdc", ".py", ".sh", ".toml", ".ts", ".tsx", ".js", ".mjs", ".cjs",
    ".json", ".yaml", ".yml", ".txt", ".example", ".bat", ".command", ".css", ".html",
}
LINT_SKIP_NAMES = {"package-lock.json", "skills-lock.json", "manifest.json", ".gitignore"}

SECRET_PATTERNS = [
    ("OpenAI key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}")),
    ("Anthropic key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{50,}")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Hugging Face token", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b")),
    ("Notion token", re.compile(r"\b(?:secret|ntn)_[A-Za-z0-9]{40,}\b")),
    ("Private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("Assigned credential", re.compile(r"\b[A-Z0-9_]*(?:API_KEY|TOKEN|SECRET)\s*=\s*['\"]?(?=[A-Za-z_\-]*\d)[A-Za-z0-9_\-]{24,}")),
]


class VasError(Exception):
    pass


# --------------------------------------------------------------------------- helpers


def run(cmd: list[str], cwd: Path, check: bool = True, timeout: int | None = None) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if check and result.returncode != 0:
        raise VasError(f"command failed: {' '.join(cmd)}\n{result.stderr.strip() or result.stdout.strip()}")
    return result


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_version(root: Path) -> dict:
    path = root / VERSION_FILE
    if not path.exists():
        return {"edition": "basic", "version": "0.0.0"}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return {"edition": str(data.get("edition", "basic")), "version": str(data.get("version", "0.0.0"))}


def version_tuple(value: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", value)
    if not parts:
        raise VasError(f"invalid version: {value!r}")
    return tuple(int(part) for part in parts[:3])


def is_protected(rel: str) -> bool:
    if rel in PROTECTED_FILES:
        return True
    if "/" not in rel and (rel == ".env" or rel.startswith(".env.")):
        return True
    return any(rel.startswith(prefix) for prefix in PROTECTED_PREFIXES)


def has_excluded_part(rel: str) -> bool:
    parts = PurePosixPath(rel).parts
    return any(part in EXCLUDED_DIR_NAMES for part in parts[:-1]) or parts[-1] in EXCLUDED_FILE_NAMES


def safe_rel(rel: str) -> str:
    """Validate a manifest path: relative, POSIX, no traversal."""
    if not rel or rel.startswith("/") or "\\" in rel or re.match(r"^[A-Za-z]:", rel):
        raise VasError(f"unsafe path in package: {rel!r}")
    parts = PurePosixPath(rel).parts
    if any(part in ("..", "") for part in parts) or rel.startswith("./"):
        raise VasError(f"unsafe path in package: {rel!r}")
    return rel


def symlink_stays_inside(rel: str, target: str) -> bool:
    if target.startswith("/") or "\\" in target:
        return False
    resolved = PurePosixPath(rel).parent
    for part in PurePosixPath(target).parts:
        if part == "..":
            if not resolved.parts:
                return False
            resolved = resolved.parent
        elif part != ".":
            resolved = resolved / part
    return True


def git_files(root: Path, *args: str) -> list[str]:
    out = run(["git", "ls-files", "-z", *args], cwd=root).stdout
    return [item for item in out.split("\0") if item]


def gitlinks(root: Path) -> set[str]:
    out = run(["git", "ls-files", "-s"], cwd=root).stdout
    return {line.split("\t", 1)[1] for line in out.splitlines() if line.startswith("160000 ")}


def is_text(rel: str) -> bool:
    name = PurePosixPath(rel).name
    return PurePosixPath(rel).suffix in TEXT_SUFFIXES or name in {"VERSION", ".gitignore", "env.example", "LICENSE"}


def prompt_yes(question: str) -> bool:
    try:
        return input(f"{question} [y/N] ").strip().lower() in {"y", "yes"}
    except EOFError:
        return False


def copy_entry(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.is_symlink() or dst.is_file():
        dst.unlink()
    elif dst.is_dir():
        shutil.rmtree(dst)
    if src.is_symlink():
        os.symlink(os.readlink(src), dst)
    else:
        shutil.copy2(src, dst)


def remove_empty_parents(path: Path, stop: Path) -> None:
    current = path.parent
    while current != stop and stop in current.parents:
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


# --------------------------------------------------------------------------- AGENTS.md parsing

MAPPING_RE = re.compile(r"^\s*-\s*`templates/([^/`]+)/`\s*→\s*`\$([a-z0-9][a-z0-9-]*)`")
SKILL_LINE_RE = re.compile(r"^\s*-\s*`\$([a-z0-9][a-z0-9-]*)`")
TEMPLATE_LINE_RE = re.compile(r"^\s*-\s*`templates/([^/`]+)/`")


def template_skill_mapping(agents_text: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for line in agents_text.splitlines():
        match = MAPPING_RE.match(line)
        if match:
            mapping[match.group(1)] = match.group(2)
    return mapping


def listed_skills(agents_text: str) -> set[str]:
    return {m.group(1) for line in agents_text.splitlines() if (m := SKILL_LINE_RE.match(line))}


# --------------------------------------------------------------------------- filtering


def filter_marked_blocks(text: str, rel: str, drop: str, unwrap: str | None) -> str:
    """Handle `<!-- <kind>:start/end -->` blocks: cut `drop` blocks, keep `unwrap` contents without markers.

    Markers of any other kind stay as they are. Markers may be prefixed with `#` (env files, scripts).
    """
    kinds = {"premium": (MARKER_START, MARKER_END), "basic": (BASIC_START, BASIC_END)}
    starts = {start: kind for kind, (start, _) in kinds.items()}
    ends = {end: kind for kind, (_, end) in kinds.items()}
    out: list[str] = []
    open_kind: str | None = None
    for number, line in enumerate(text.splitlines(keepends=True), start=1):
        marker = line.strip().lstrip("#").strip()
        if marker in starts:
            if open_kind:
                raise VasError(f"{rel}:{number}: nested {marker} inside a {open_kind} block")
            open_kind = starts[marker]
            if open_kind not in (drop, unwrap):
                out.append(line)
            continue
        if marker in ends:
            if ends[marker] != open_kind:
                raise VasError(f"{rel}:{number}: {marker} without a matching start")
            if open_kind not in (drop, unwrap):
                out.append(line)
            open_kind = None
            continue
        if open_kind != drop:
            out.append(line)
    if open_kind:
        raise VasError(f"{rel}: unclosed {kinds[open_kind][0]}")
    return "".join(out)


def strip_premium_blocks(text: str, rel: str) -> str:
    """Basic export: cut Premium blocks, keep Basic-only contents."""
    return filter_marked_blocks(text, rel, drop="premium", unwrap="basic")


def strip_basic_blocks(text: str, rel: str) -> str:
    """Premium ZIP: cut Basic-only blocks, leave Premium markers in place."""
    return filter_marked_blocks(text, rel, drop="basic", unwrap=None)


def drop_premium_list_lines(text: str, keep_skills: set[str], premium_skills: set[str],
                            keep_templates: set[str], premium_templates: set[str]) -> str:
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        skill = SKILL_LINE_RE.match(line)
        if skill and skill.group(1) in premium_skills and skill.group(1) not in keep_skills:
            continue
        template = TEMPLATE_LINE_RE.match(line)
        if template and template.group(1) in premium_templates and template.group(1) not in keep_templates:
            continue
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "".join(out))


# --------------------------------------------------------------------------- Basic selection


@dataclass
class Selection:
    files: list[str]                      # repo-relative files to ship (no symlink mirrors)
    skills: set[str]                      # skills/ folder names
    agent_skills: set[str]                # .agents/skills folder names
    templates: set[str]
    tools: set[str]
    packages: set[str]
    premium_skills: set[str] = field(default_factory=set)
    premium_templates: set[str] = field(default_factory=set)
    premium_tools: set[str] = field(default_factory=set)
    premium_packages: set[str] = field(default_factory=set)
    config: dict = field(default_factory=dict)


def list_dir_names(path: Path, marker: str | None = None) -> set[str]:
    """Entry names in a folder; with `marker`, only folders containing that file."""
    if not path.is_dir():
        return set()
    return {
        item.name for item in path.iterdir()
        if not item.name.startswith(".") and (marker is None or (item / marker).exists())
    }


def load_basic_selection(root: Path) -> Selection:
    config_path = root / BASIC_CONFIG
    if not config_path.exists():
        raise VasError(f"{BASIC_CONFIG} not found; publish basic runs only in the Premium source workspace")
    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    agents_text = (root / "AGENTS.md").read_text(encoding="utf-8")
    mapping = template_skill_mapping(agents_text)

    templates = set(config.get("templates", []))
    skills = set(config.get("skills", []))
    errors: list[str] = []
    for template_id in sorted(templates):
        if not (root / "templates" / template_id / "template.toml").exists():
            errors.append(f"template not found: templates/{template_id}/template.toml")
        skill = mapping.get(template_id)
        if not skill:
            errors.append(f"no AGENTS.md mapping for templates/{template_id}/")
        elif (root / "skills" / skill / "SKILL.md").exists():
            skills.add(skill)
        else:
            errors.append(f"matching skill not found: skills/{skill}/SKILL.md")
    agent_skills = set(config.get("agent_skills", []))
    tools = set(config.get("tools", []))
    packages = set(config.get("packages", []))

    roots: list[str] = []
    roots += [f"skills/{name}" for name in skills]
    roots += [f".agents/skills/{name}" for name in agent_skills]
    roots += [f"templates/{name}" for name in templates]
    roots += [f"tools/{name}" for name in tools]
    roots += [f"packages/{name}" for name in packages]
    roots += list(config.get("files", []))
    if not skills or not config.get("files"):
        errors.append("allowlist is empty: `skills` and `files` must be top-level keys placed before [publish]")
    for rel in roots:
        if not (root / rel).exists() and not (root / rel).is_symlink():
            errors.append(f"allowlisted path does not exist: {rel}")
    if errors:
        raise VasError("basic.toml problems:\n  " + "\n  ".join(errors))

    links = gitlinks(root)
    candidates = git_files(root, "-c", "-o", "--exclude-standard", "--", *roots)
    files = sorted({
        rel for rel in candidates
        if rel not in links
        and not has_excluded_part(rel)
        and not any(rel.startswith(f"{mirror}/") for mirror in SYMLINK_MIRRORS)
        and rel not in (BASIC_CONFIG, CUSTOMS_FILE, MANIFEST_REL)
        and (root / rel).exists()
    })

    all_skills = list_dir_names(root / "skills", "SKILL.md") | list_dir_names(root / ".agents" / "skills", "SKILL.md")
    return Selection(
        files=files,
        skills=skills,
        agent_skills=agent_skills,
        templates=templates,
        tools=tools,
        packages=packages,
        premium_skills=all_skills - skills - agent_skills,
        premium_templates=list_dir_names(root / "templates", "template.toml") - templates,
        premium_tools=list_dir_names(root / "tools") - tools,
        premium_packages=list_dir_names(root / "packages") - packages,
        config=config,
    )


# --------------------------------------------------------------------------- lint + scans


def lint_references(stage: Path, sel: Selection, files: list[str]) -> list[str]:
    """Report references from shipped Basic files to Premium-only items."""
    def name_pattern(names: set[str]) -> str:
        return "|".join(sorted((re.escape(n) for n in names), key=len, reverse=True)) or r"(?!x)x"

    skills = name_pattern(sel.premium_skills)
    templates = name_pattern(sel.premium_templates)
    tools = name_pattern({PurePosixPath(n).stem if n.endswith(".py") else n for n in sel.premium_tools})
    packages = name_pattern(sel.premium_packages)
    end = r"(?![A-Za-z0-9_-])"
    start = r"(?<![A-Za-z0-9_-])"
    checks = [
        ("${}", re.compile(rf"\$({skills}){end}")),
        ("`{}`", re.compile(rf"`({skills})`")),
        ("skills/{}", re.compile(rf"{start}skills/({skills}){end}")),
        ("templates/{}", re.compile(rf"{start}templates/({templates}){end}")),
        ("tools/{}", re.compile(rf"{start}tools[/.]({tools}){end}")),
        ("packages/{}", re.compile(rf"{start}packages/({packages}){end}")),
    ]
    problems: list[str] = []
    for rel in files:
        if not is_text(rel) or PurePosixPath(rel).name in LINT_SKIP_NAMES:
            continue
        path = stage / rel
        if path.is_symlink():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            for label, pattern in checks:
                for match in pattern.finditer(line):
                    problems.append(f"{rel}:{number}: Premium-only reference {label.format(match.group(1))}")
    return problems


def secret_scan(base: Path, files: list[str]) -> list[str]:
    hits: list[str] = []
    for rel in files:
        path = base / rel
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 5 * 1024 * 1024:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            for label, pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    hits.append(f"{rel}:{number}: possible {label}")
    if shutil.which("gitleaks"):
        result = subprocess.run(
            ["gitleaks", "dir", str(base), "--no-banner", "--redact", "--exit-code", "1"],
            capture_output=True, text=True,
        )
        if result.returncode == 1:
            hits.append("gitleaks reported findings:\n" + (result.stdout or result.stderr).strip())
    return hits


TEMPLATE_WORD_RE = re.compile(r"template", re.IGNORECASE)
# Third-party skills and the edition tooling itself may say "template"; nothing else in Basic may.
TEMPLATE_LINT_EXEMPT = (".agents/", "scripts/vas.py", "scripts/tests/", "package-lock.json")


def template_mentions(stage: Path, files: list[str]) -> list[str]:
    """Basic has no templates: report every first-party text line that mentions one."""
    problems: list[str] = []
    for rel in files:
        if rel.startswith(TEMPLATE_LINT_EXEMPT) or not is_text(rel) or (stage / rel).is_symlink():
            continue
        try:
            lines = (stage / rel).read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        problems += [f"{rel}:{n}: mentions templates (Basic has none)"
                     for n, line in enumerate(lines, start=1) if TEMPLATE_WORD_RE.search(line)]
    return problems


def forbidden_paths(files: list[str]) -> list[str]:
    allowed_placeholders = {"customs/.gitkeep", "raw_assets/.gitkeep", "raw_assets/README.md",
                            "raw_assets/images/.gitkeep", "raw_assets/videos/.gitkeep", "raw_assets/audio/.gitkeep"}
    bad: list[str] = []
    for rel in files:
        if rel in allowed_placeholders:
            continue
        if rel in (CUSTOMS_FILE, BASIC_CONFIG) or rel.startswith(("customs/", "jobs/", "raw_assets/", ".vas/backups/")):
            bad.append(rel)
        elif "/" not in rel and (rel == ".env" or (rel.startswith(".env.") and rel != ".env.example")):
            bad.append(rel)
    return bad


AUDITED_KINDS = ("remotion", "generation", "capcut")


def audit_templates(root: Path, template_ids: list[str], mapping: dict[str, str]) -> tuple[list[str], list[str]]:
    """Run job-to-template's audit. Returns (failures, skipped) — skipped kinds the audit does not support."""
    script = root / "skills" / "job-to-template" / "scripts" / "audit_template.py"
    if not script.exists():
        return [f"missing {script.relative_to(root)}"], []
    failures: list[str] = []
    skipped: list[str] = []
    for template_id in template_ids:
        contract = tomllib.loads((root / "templates" / template_id / "template.toml").read_text(encoding="utf-8"))
        if not any(kind in contract for kind in AUDITED_KINDS):
            skipped.append(template_id)
            continue
        cmd = [sys.executable, str(script), "--template-id", template_id]
        if template_id in mapping:
            cmd += ["--template-skill", mapping[template_id]]
        result = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().splitlines()
            failures.append(f"templates/{template_id}: {detail[-1] if detail else 'audit failed'}")
    return failures, skipped


# --------------------------------------------------------------------------- manifest + mirrors


def build_manifest(base: Path, files: list[str], edition: str, version: str,
                   overrides: dict[str, bytes] | None = None) -> dict:
    entries: dict[str, dict] = {}
    for rel in sorted(files):
        path = base / rel
        if overrides and rel in overrides:
            entries[rel] = {"sha256": sha256_bytes(overrides[rel]), "size": len(overrides[rel])}
        elif path.is_symlink():
            entries[rel] = {"symlink": os.readlink(path)}
        else:
            entries[rel] = {"sha256": sha256_file(path), "size": path.stat().st_size}
    return {
        "edition": edition,
        "version": version,
        "created": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": entries,
    }


def mirror_links(root: Path, shipped_dirs: set[str]) -> list[tuple[str, str]]:
    """Symlinks in SYMLINK_MIRRORS whose target is a shipped skill folder."""
    links: list[tuple[str, str]] = []
    for mirror in SYMLINK_MIRRORS:
        folder = root / mirror
        if not folder.is_dir():
            continue
        for entry in sorted(folder.iterdir()):
            if not entry.is_symlink():
                continue
            target = os.readlink(entry)
            resolved = os.path.normpath(os.path.join(mirror, target))
            if resolved in shipped_dirs:
                links.append((f"{mirror}/{entry.name}", target))
    return links


PATH_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_.-])((?:packages|skills|labs|tools|templates)/[A-Za-z0-9_.-]+)")


def prune_node_manifests(stage: Path, shipped_packages: set[str]) -> None:
    """Drop local `file:packages/<x>` dependencies and npm scripts whose paths do not ship in Basic."""
    def ships(rel: str) -> bool:
        return (stage / rel).exists()

    package_json = stage / "package.json"
    if package_json.exists():
        data = json.loads(package_json.read_text(encoding="utf-8"))
        for key in ("dependencies", "devDependencies", "optionalDependencies"):
            deps = data.get(key, {})
            for name, spec in list(deps.items()):
                if isinstance(spec, str) and spec.startswith("file:packages/") and \
                        spec.removeprefix("file:packages/").split("/")[0] not in shipped_packages:
                    del deps[name]
        scripts = data.get("scripts", {})
        for name, command in list(scripts.items()):
            if any(not ships(token) for token in PATH_TOKEN_RE.findall(command)):
                del scripts[name]
        package_json.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lock_path = stage / "package-lock.json"
    if lock_path.exists():
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        packages = lock.get("packages", {})
        removed_names: set[str] = set()
        for key, entry in list(packages.items()):
            local = key.removeprefix("packages/").split("/")[0] if key.startswith("packages/") else None
            linked = entry.get("resolved", "") if entry.get("link") else ""
            linked_pkg = linked.removeprefix("packages/").split("/")[0] if linked.startswith("packages/") else None
            if (local and local not in shipped_packages) or (linked_pkg and linked_pkg not in shipped_packages):
                del packages[key]
                if key.startswith("node_modules/"):
                    removed_names.add(key.removeprefix("node_modules/"))
        root_entry = packages.get("", {})
        for key in ("dependencies", "devDependencies", "optionalDependencies"):
            for name in removed_names:
                root_entry.get(key, {}).pop(name, None)
        lock_path.write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_version(path: Path, edition: str, version: str) -> None:
    path.write_text(f'edition = "{edition}"\nversion = "{version}"\n', encoding="utf-8")


# --------------------------------------------------------------------------- publish basic


def build_basic_stage(root: Path, stage: Path) -> tuple[Selection, list[str], dict]:
    sel = load_basic_selection(root)
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    version = read_version(root)["version"]
    keep_skills = sel.skills | sel.agent_skills

    for rel in sel.files:
        src, dst = root / rel, stage / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            os.symlink(os.readlink(src), dst)
            continue
        if is_text(rel):
            try:
                text = src.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                shutil.copy2(src, dst)
                continue
            text = strip_premium_blocks(text, rel)
            if rel in ROUTER_FILES:
                text = drop_premium_list_lines(text, keep_skills, sel.premium_skills, sel.templates, sel.premium_templates)
            dst.write_text(text, encoding="utf-8")
            shutil.copymode(src, dst)
        else:
            shutil.copy2(src, dst)

    write_version(stage / VERSION_FILE, "basic", version)
    prune_node_manifests(stage, sel.packages)
    lock = stage / "skills-lock.json"
    if lock.exists():
        data = json.loads(lock.read_text(encoding="utf-8"))
        data["skills"] = {k: v for k, v in data.get("skills", {}).items() if k in sel.agent_skills}
        lock.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    shipped_dirs = {f"skills/{n}" for n in sel.skills} | {f".agents/skills/{n}" for n in sel.agent_skills}
    files = list(sel.files)
    for rel, target in mirror_links(root, shipped_dirs):
        (stage / rel).parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, stage / rel)
        files.append(rel)
    if VERSION_FILE not in files:
        files.append(VERSION_FILE)
    files = sorted(set(files))

    manifest = build_manifest(stage, files, "basic", version)
    (stage / MANIFEST_REL).parent.mkdir(parents=True, exist_ok=True)
    (stage / MANIFEST_REL).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return sel, files, manifest


def check_basic_stage(root: Path, stage: Path, sel: Selection, files: list[str]) -> list[str]:
    problems = lint_references(stage, sel, files)
    problems += template_mentions(stage, files)
    problems += [f"forbidden path in Basic: {rel}" for rel in forbidden_paths(files)]
    problems += secret_scan(stage, files)
    mapping = template_skill_mapping((root / "AGENTS.md").read_text(encoding="utf-8"))
    failures, skipped = audit_templates(root, sorted(sel.templates), mapping)
    if skipped:
        print(f"  template audit not applicable (custom renderer): {', '.join(skipped)}")
    return problems + failures


def sync_tree(stage: Path, checkout: Path) -> None:
    for entry in checkout.iterdir():
        if entry.name == ".git":
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    for src in sorted(stage.rglob("*")):
        rel = src.relative_to(stage)
        dst = checkout / rel
        if src.is_symlink():
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(os.readlink(src), dst)
        elif src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def cmd_publish_basic(root: Path, args: argparse.Namespace) -> int:
    stage = Path(args.out).resolve() if args.out else root / ".vas" / "staging" / "basic"
    sel, files, manifest = build_basic_stage(root, stage)
    total = sum(entry.get("size", 0) for entry in manifest["files"].values())
    print(f"Basic staging: {stage}")
    print(f"  {len(files)} files, {total / 1048576:.1f} MB")
    print(f"  {len(sel.skills)} skills, {len(sel.agent_skills)} third-party skills, {len(sel.templates)} templates")
    if args.list:
        for rel in files:
            print(f"    {rel}")

    problems = check_basic_stage(root, stage, sel, files)
    if problems:
        print("\nBasic export blocked:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("  checks: references, forbidden paths, secrets, template audits all passed")
    if args.dry_run:
        print("\nDry run: nothing pushed.")
        return 0

    publish = sel.config.get("publish", {})
    repo_url = publish.get("repo_url")
    branch = publish.get("branch", "main")
    checkout = root / publish.get("checkout", ".vas/basic-repo")
    if not repo_url:
        raise VasError("basic.toml [publish].repo_url is missing")
    if not (checkout / ".git").exists():
        checkout.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "clone", repo_url, str(checkout)], cwd=root)
    run(["git", "fetch", "origin"], cwd=checkout)
    remote_has_branch = run(["git", "ls-remote", "--heads", "origin", branch], cwd=checkout).stdout.strip()
    if remote_has_branch:
        run(["git", "checkout", "-B", branch, f"origin/{branch}"], cwd=checkout)
    else:
        run(["git", "checkout", "--orphan", branch], cwd=checkout, check=False)
    tag = f"v{manifest['version']}"
    if run(["git", "ls-remote", "--tags", "origin", tag], cwd=checkout).stdout.strip():
        raise VasError(f"{tag} is already published to Basic; bump {VERSION_FILE} first")

    sync_tree(stage, checkout)
    run(["git", "add", "-A"], cwd=checkout)
    status = run(["git", "status", "--porcelain"], cwd=checkout).stdout.splitlines()
    if not status:
        print("\nBasic repository already matches this export; nothing to push.")
        return 0
    added = sum(1 for line in status if line.startswith("A"))
    deleted = sum(1 for line in status if line.startswith("D"))
    modified = len(status) - added - deleted
    print(f"\nBasic {tag} → {repo_url} ({branch}): {added} added, {modified} modified, {deleted} deleted")
    if not args.yes and not prompt_yes("Push this snapshot to the PUBLIC Basic repository?"):
        print("Not pushed. The prepared commit stays staged in", checkout)
        return 1
    run(["git", "commit", "-m", f"VAS {tag}"], cwd=checkout)
    run(["git", "tag", tag], cwd=checkout)
    run(["git", "push", "origin", branch], cwd=checkout)
    run(["git", "push", "origin", tag], cwd=checkout)
    print(f"Published Basic {tag}.")
    return 0


# --------------------------------------------------------------------------- publish premium


def premium_files(root: Path, include_untracked: bool) -> list[str]:
    links = gitlinks(root)
    files = set(git_files(root, "-c"))
    if include_untracked:
        tops = {PurePosixPath(rel).parts[0] for rel in files} | {"templates", VERSION_FILE}
        files |= {rel for rel in git_files(root, "-o", "--exclude-standard") if PurePosixPath(rel).parts[0] in tops}
    kept = sorted(
        rel for rel in files
        if rel not in links
        and rel not in (BASIC_CONFIG, CUSTOMS_FILE, MANIFEST_REL)
        and not has_excluded_part(rel)
        and ((root / rel).exists() or (root / rel).is_symlink())
    )
    shipped = set(kept)
    dangling = []
    for rel in kept:
        path = root / rel
        if path.is_symlink():
            target = os.path.normpath(os.path.join(os.path.dirname(rel), os.readlink(path)))
            if not any(item == target or item.startswith(target + "/") for item in shipped):
                dangling.append(rel)
    if dangling:
        print("Skipping symlinks whose target does not ship (clean these up): " + ", ".join(dangling))
    return [rel for rel in kept if rel not in set(dangling)]


def basic_only_overrides(root: Path, files: list[str]) -> dict[str, bytes]:
    """Premium copies of text files with their Basic-only blocks removed."""
    overrides: dict[str, bytes] = {}
    for rel in files:
        path = root / rel
        if path.is_symlink() or not is_text(rel):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if BASIC_START in text:
            overrides[rel] = strip_basic_blocks(text, rel).encode("utf-8")
    return overrides


def write_zip(base: Path, files: list[str], manifest: dict, archive: Path,
              overrides: dict[str, bytes] | None = None) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    tmp = archive.with_suffix(".zip.tmp")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr(MANIFEST_REL, json.dumps(manifest, indent=2) + "\n")
        for rel in files:
            path = base / rel
            if overrides and rel in overrides:
                zf.writestr(rel, overrides[rel])
            elif path.is_symlink():
                zf.writestr(rel, os.readlink(path))
            else:
                zf.write(path, rel)
    tmp.replace(archive)
    archive.with_name(archive.name + ".sha256").write_text(f"{sha256_file(archive)}  {archive.name}\n", encoding="utf-8")


def cmd_publish_premium(root: Path, args: argparse.Namespace) -> int:
    tracked_customs = [rel for rel in git_files(root, "-c", "--", "customs", CUSTOMS_FILE) if rel != "customs/.gitkeep"]
    problems = [f"user customization is tracked by git: {rel}" for rel in tracked_customs]
    dirty = run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=root).stdout.strip()
    if dirty and not args.include_untracked:
        problems.append("working tree has uncommitted changes; commit them first so the ZIP matches the pushed commit")
    files = premium_files(root, args.include_untracked)
    templates = sorted({PurePosixPath(rel).parts[1] for rel in files if rel.startswith("templates/") and rel.count("/") >= 2})
    mapping = template_skill_mapping((root / "AGENTS.md").read_text(encoding="utf-8"))
    failures, _ = audit_templates(root, templates, mapping)
    if failures:
        # Generated folders never ship (EXCLUDED_DIR_NAMES); contract issues are reported, not blocking.
        print("Template audit warnings (not blocking Premium):")
        for failure in failures:
            print(f"  - {failure}")
    problems += secret_scan(root, files)
    if problems:
        print("Premium publish blocked:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    info = read_version(root)
    if info["edition"] != "premium":
        raise VasError(f"{VERSION_FILE} edition must be premium in the source workspace")
    if not args.no_push and not args.include_untracked:
        print(f"Push Premium v{info['version']} ({len(files)} files) to the private repository?")
        if args.yes or prompt_yes("Push now?"):
            run(["git", "push", "origin", "HEAD"], cwd=root)
            print("Pushed.")
        else:
            print("Not pushed.")

    overrides = basic_only_overrides(root, files)
    manifest = build_manifest(root, files, "premium", info["version"], overrides)
    archive = Path(args.zip_out).resolve() if args.zip_out else root / "exports" / "releases" / f"vas-premium-{info['version']}.zip"
    write_zip(root, files, manifest, archive, overrides)
    print(f"Upgrade ZIP: {archive} ({archive.stat().st_size / 1048576:.1f} MB, {len(files)} files)")
    return 0


# --------------------------------------------------------------------------- upgrade


def read_package(archive: Path) -> tuple[zipfile.ZipFile, dict]:
    if not archive.is_file():
        raise VasError(f"ZIP not found: {archive}")
    try:
        zf = zipfile.ZipFile(archive)
    except zipfile.BadZipFile as exc:
        raise VasError(f"not a valid ZIP file: {archive}") from exc
    names = set(zf.namelist())
    if MANIFEST_REL not in names:
        raise VasError("this ZIP is not a VAS Premium package (missing .vas/manifest.json)")
    manifest = json.loads(zf.read(MANIFEST_REL))
    if manifest.get("edition") != "premium":
        raise VasError(f"this ZIP is a {manifest.get('edition')!r} package, not Premium")
    for rel, entry in manifest.get("files", {}).items():
        safe_rel(rel)
        if rel not in names:
            raise VasError(f"package is incomplete: {rel} missing")
        data = zf.read(rel)
        if "symlink" in entry:
            target = entry["symlink"]
            if data.decode("utf-8") != target or not symlink_stays_inside(rel, target):
                raise VasError(f"unsafe or corrupt symlink in package: {rel} -> {target}")
        elif sha256_bytes(data) != entry.get("sha256"):
            raise VasError(f"package is corrupt: checksum mismatch for {rel}")
    for name in names:
        safe_rel(name.rstrip("/"))
    return zf, manifest


def load_manifest(root: Path) -> dict | None:
    path = root / MANIFEST_REL
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def current_matches(path: Path, entry: dict) -> bool:
    if "symlink" in entry:
        return path.is_symlink() and os.readlink(path) == entry["symlink"]
    return path.is_file() and not path.is_symlink() and sha256_file(path) == entry["sha256"]


def git_state(root: Path) -> dict | None:
    if not (root / ".git").exists() or not shutil.which("git"):
        return None
    branch = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root, check=False).stdout.strip()
    head = run(["git", "rev-parse", "HEAD"], cwd=root, check=False).stdout.strip()
    remotes = {}
    for line in run(["git", "remote", "-v"], cwd=root, check=False).stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            remotes[parts[0]] = parts[1]
    return {"branch": branch, "head": head, "remotes": remotes}


def post_install(root: Path, changed: set[str], report: list[str]) -> None:
    if ("package-lock.json" in changed or "package.json" in changed or not (root / "node_modules").exists()):
        if shutil.which("npm"):
            result = subprocess.run(["npm", "install", "--no-audit", "--no-fund"], cwd=root, capture_output=True, text=True)
            report.append("npm install: " + ("ok" if result.returncode == 0 else f"FAILED\n{result.stderr[-2000:]}"))
        else:
            report.append("npm not found: install Node.js, then run `npm install` in the repository root")
    requirements = sorted(rel for rel in changed if PurePosixPath(rel).name == "requirements.txt")
    venv_python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if requirements:
        if venv_python.exists():
            for rel in requirements:
                result = subprocess.run([str(venv_python), "-m", "pip", "install", "-q", "-r", rel],
                                        cwd=root, capture_output=True, text=True)
                report.append(f"pip install -r {rel}: " + ("ok" if result.returncode == 0 else "FAILED"))
        else:
            report.append("no .venv: create it with `python3 -m venv .venv` before using tools with Python requirements")
    ensure = root / "scripts" / "ensure-remotion-skill.sh"
    if ensure.exists() and shutil.which("bash"):
        result = subprocess.run(["bash", str(ensure)], cwd=root, capture_output=True, text=True)
        report.append("ensure-remotion-skill.sh: " + ("ok" if result.returncode == 0 else "FAILED"))


def env_keys(path: Path) -> dict[str, str]:
    keys: dict[str, str] = {}
    if not path.exists():
        return keys
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*)$", line)
        if match:
            keys[match.group(1)] = match.group(2).strip().strip("'\"")
    return keys


def cmd_upgrade(root: Path, args: argparse.Namespace) -> int:
    if args.rollback:
        return rollback(root)
    if not args.zip:
        raise VasError("usage: vas.py upgrade <path-to-premium.zip>")
    archive = Path(args.zip).expanduser().resolve()
    zf, new_manifest = read_package(archive)
    current = read_version(root)
    new_version = new_manifest["version"]
    if version_tuple(new_version) < version_tuple(current["version"]) and not args.allow_downgrade:
        raise VasError(f"package v{new_version} is older than installed v{current['version']} (use --allow-downgrade)")
    if (root / BASIC_CONFIG).exists():
        raise VasError("this is the Premium source workspace; upgrade runs only in an installed copy")
    print(f"Upgrading {current['edition']} v{current['version']} → premium v{new_version}")

    old_manifest = load_manifest(root)
    old_files = old_manifest["files"] if old_manifest else {}
    new_files = new_manifest["files"]
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = root / ".vas" / "backups" / stamp
    notes: list[str] = []

    # Preflight: official files the user edited by hand.
    edited = [rel for rel, entry in old_files.items()
              if not is_protected(rel) and ((root / rel).exists() or (root / rel).is_symlink())
              and not current_matches(root / rel, entry)]
    if edited:
        keep = root / "customs" / "_upgrade_backup" / stamp
        for rel in edited:
            copy_entry(root / rel, keep / rel)
        notes.append(f"{len(edited)} official file(s) had manual edits; copies saved in customs/_upgrade_backup/{stamp}/ "
                     "(move real customizations into customs/)")
    if not old_manifest:
        notes.append("no previous manifest found; every overwritten file is still backed up for rollback")

    # Plan the change set.
    writes: list[str] = []
    overwritten: list[str] = []
    added: list[str] = []
    for rel, entry in new_files.items():
        path = root / rel
        exists = path.exists() or path.is_symlink()
        if is_protected(rel) and exists:
            continue
        if exists and current_matches(path, entry):
            continue
        writes.append(rel)
        (overwritten if exists else added).append(rel)
    deleted = [rel for rel in old_files
               if rel not in new_files and not is_protected(rel) and ((root / rel).exists() or (root / rel).is_symlink())]

    # Backup for rollback.
    files_backup = backup_dir / "files"
    for rel in overwritten + deleted + [MANIFEST_REL]:
        if (root / rel).exists() or (root / rel).is_symlink():
            copy_entry(root / rel, files_backup / rel)
    git_before = git_state(root)
    record = {
        "created": stamp,
        "from": current,
        "to": {"edition": "premium", "version": new_version},
        "overwritten": overwritten,
        "deleted": deleted,
        "added": added,
        "had_manifest": old_manifest is not None,
        "git": git_before,
        "env_before": sorted(env_keys(root / "env.example")),
    }
    backup_dir.mkdir(parents=True, exist_ok=True)
    (backup_dir / "backup.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")

    # Apply.
    for rel in writes:
        entry = new_files[rel]
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
        if "symlink" in entry:
            try:
                os.symlink(entry["symlink"], path)
            except OSError:
                notes.append(f"could not create symlink {rel} (enable Developer Mode on Windows)")
        else:
            path.write_bytes(zf.read(rel))
            if rel.endswith((".sh", ".command")) or rel.startswith("scripts/"):
                path.chmod(path.stat().st_mode | 0o111)
    for rel in deleted:
        path = root / rel
        path.unlink() if (path.is_symlink() or path.is_file()) else shutil.rmtree(path, ignore_errors=True)
        remove_empty_parents(path, root)
    (root / MANIFEST_REL).parent.mkdir(parents=True, exist_ok=True)
    (root / MANIFEST_REL).write_bytes(zf.read(MANIFEST_REL))
    zf.close()
    print(f"  files: {len(added)} added, {len(overwritten)} updated, {len(deleted)} removed")

    # Git: keep the clone usable without pulling Basic over Premium.
    if git_before:
        try:
            if git_before["branch"] != "premium":
                run(["git", "checkout", "-B", "premium"], cwd=root)
            pathspec = backup_dir / "pathspec.txt"
            pathspec.write_text("\n".join(sorted(set(writes + deleted + [MANIFEST_REL]))) + "\n", encoding="utf-8")
            run(["git", "--literal-pathspecs", "add", "-A", f"--pathspec-from-file={pathspec}"], cwd=root)
            identity = [] if run(["git", "config", "user.email"], cwd=root, check=False).stdout.strip() else \
                ["-c", "user.name=VAS upgrade", "-c", "user.email=vas-upgrade@localhost"]
            run(["git", *identity, "commit", "-q", "-m", f"Upgrade to VAS Premium v{new_version}"], cwd=root, check=False)
            if "origin" in git_before["remotes"] and "basic" not in git_before["remotes"] and \
                    "basic" in git_before["remotes"]["origin"]:
                run(["git", "remote", "rename", "origin", "basic"], cwd=root)
            print("  git: committed on local branch 'premium'")
        except VasError as exc:
            notes.append(f"git step skipped: {exc}")

    report: list[str] = []
    post_install(root, set(writes), report)
    for line in report:
        print(f"  {line}")
    missing = [k for k in env_keys(root / "env.example") if not env_keys(root / ".env").get(k)]
    if missing:
        print("  API keys to add in .env (only for the features you use): " + ", ".join(missing))
    for note in notes:
        print(f"  note: {note}")

    print("\nRunning doctor...")
    doctor = subprocess.run([sys.executable, str(root / "scripts" / "vas.py"), "doctor"]
                            + ([] if args.no_smoke else ["--smoke"]), cwd=root)
    if doctor.returncode != 0:
        print("\nDoctor reported FAIL. To undo this upgrade run: python3 scripts/vas.py upgrade --rollback")
        return 1
    print(f"\nVAS Premium v{new_version} is installed and verified.")
    return 0


def rollback(root: Path) -> int:
    backups = sorted(p for p in (root / ".vas" / "backups").glob("*") if (p / "backup.json").exists()) \
        if (root / ".vas" / "backups").exists() else []
    if not backups:
        raise VasError("no upgrade backup found")
    backup = backups[-1]
    record = json.loads((backup / "backup.json").read_text(encoding="utf-8"))
    files_backup = backup / "files"
    print(f"Rolling back to {record['from']['edition']} v{record['from']['version']} (backup {backup.name})")

    for rel in record["added"]:
        path = root / rel
        if path.is_symlink() or path.is_file():
            path.unlink()
            remove_empty_parents(path, root)
    for rel in record["overwritten"] + record["deleted"]:
        if (files_backup / rel).exists() or (files_backup / rel).is_symlink():
            copy_entry(files_backup / rel, root / rel)
    manifest_backup = files_backup / MANIFEST_REL
    if manifest_backup.exists():
        copy_entry(manifest_backup, root / MANIFEST_REL)
    elif (root / MANIFEST_REL).exists():
        (root / MANIFEST_REL).unlink()

    git_before = record.get("git")
    if git_before:
        if "basic" in run(["git", "remote"], cwd=root, check=False).stdout.split() and \
                "origin" in git_before["remotes"]:
            run(["git", "remote", "rename", "basic", "origin"], cwd=root, check=False)
        old_branch = git_before["branch"]
        if old_branch and old_branch not in ("premium", "HEAD"):
            # Point HEAD back at the old branch without touching the restored working tree,
            # so uncommitted edits that existed before the upgrade survive.
            result = run(["git", "symbolic-ref", "HEAD", f"refs/heads/{old_branch}"], cwd=root, check=False)
            if result.returncode == 0:
                run(["git", "reset", "-q"], cwd=root, check=False)
            else:
                print(f"  note: could not switch back to git branch {old_branch}: {result.stderr.strip()}")
    backup.rename(backup.with_name(backup.name + "-rolled-back"))
    print("Rollback complete.")
    return 0


# --------------------------------------------------------------------------- doctor


@dataclass
class Report:
    items: list[tuple[str, str, str]] = field(default_factory=list)

    def add(self, level: str, check: str, detail: str) -> None:
        self.items.append((level, check, detail))

    @property
    def failed(self) -> bool:
        return any(level == "FAIL" for level, _, _ in self.items)


def resolve_skill(root: Path, name: str) -> Path | None:
    for base in (root / "customs" / "skills", root / "skills", root / ".agents" / "skills"):
        if (base / name / "SKILL.md").exists():
            return base / name
    return None


def resolve_template(root: Path, template_id: str) -> Path | None:
    for base in (root / "customs" / "templates", root / "templates"):
        if (base / template_id / "template.toml").exists():
            return base / template_id
    return None


def doctor_integrity(root: Path, rep: Report) -> None:
    info = read_version(root)
    rep.add("INFO", "edition", f"{info['edition']} v{info['version']}")
    manifest = load_manifest(root)
    if manifest is None:
        level = "INFO" if (root / BASIC_CONFIG).exists() else "WARN"
        rep.add(level, "integrity", "no .vas/manifest.json (source workspace or manual install)")
        return
    if manifest.get("edition") != info["edition"] or manifest.get("version") != info["version"]:
        rep.add("FAIL", "integrity", f"VERSION ({info['edition']} v{info['version']}) does not match manifest "
                f"({manifest.get('edition')} v{manifest.get('version')})")
    missing, edited = [], []
    for rel, entry in manifest["files"].items():
        path = root / rel
        if not (path.exists() or path.is_symlink()):
            if "symlink" in entry and os.name == "nt":
                continue
            missing.append(rel)
        elif not current_matches(path, entry):
            edited.append(rel)
    if missing:
        rep.add("FAIL", "integrity", f"{len(missing)} file(s) missing, e.g. {', '.join(missing[:5])}")
    if edited:
        rep.add("WARN", "integrity", f"{len(edited)} official file(s) edited by hand (upgrades overwrite them; "
                f"use customs/), e.g. {', '.join(edited[:5])}")
    if not missing and not edited:
        rep.add("PASS", "integrity", f"{len(manifest['files'])} files match the manifest")


def doctor_skills(root: Path, rep: Report) -> None:
    agents = root / "AGENTS.md"
    if not agents.exists():
        rep.add("FAIL", "skills", "AGENTS.md missing")
        return
    text = agents.read_text(encoding="utf-8")
    mapping = template_skill_mapping(text)
    missing_skills = sorted(name for name in listed_skills(text) | set(mapping.values()) if not resolve_skill(root, name))
    missing_templates = sorted(t for t in mapping if not resolve_template(root, t))
    if missing_skills:
        rep.add("FAIL", "skills", "listed in AGENTS.md but missing: " + ", ".join(missing_skills))
    if missing_templates:
        rep.add("FAIL", "templates", "mapped in AGENTS.md but missing template.toml: " + ", ".join(missing_templates))
    broken = []
    for mirror in SYMLINK_MIRRORS:
        folder = root / mirror
        if folder.is_dir():
            broken += [f"{mirror}/{e.name}" for e in folder.iterdir() if e.is_symlink() and not e.exists()]
    if broken:
        rep.add("FAIL", "skill links", "broken: " + ", ".join(sorted(broken)[:10]))
    if not (missing_skills or missing_templates or broken):
        templates = f" and {len(mapping)} templates" if mapping else ""
        rep.add("PASS", "skills", f"{len(listed_skills(text))} skills{templates} resolve")


def doctor_dependencies(root: Path, rep: Report) -> None:
    rep.add("PASS", "python", sys.version.split()[0])
    if not shutil.which("node"):
        rep.add("FAIL", "node", "Node.js not found")
    elif not (root / "node_modules").exists():
        rep.add("FAIL", "node_modules", "missing; run `npm install` in the repository root")
    else:
        result = subprocess.run(["node", "-e", "require.resolve('remotion'); require.resolve('@remotion/cli')"],
                                cwd=root, capture_output=True, text=True)
        rep.add("PASS" if result.returncode == 0 else "FAIL", "remotion",
                "resolves from root node_modules" if result.returncode == 0 else "cannot resolve; run `npm install`")
    ensure = root / "scripts" / "ensure-remotion-skill.sh"
    if ensure.exists() and shutil.which("bash"):
        result = subprocess.run(["bash", str(ensure)], cwd=root, capture_output=True, text=True)
        rep.add("PASS" if result.returncode == 0 else "FAIL", "remotion skills",
                "complete" if result.returncode == 0 else (result.stdout + result.stderr).strip()[-300:])
    for tool in ("ffmpeg", "ffprobe"):
        rep.add("PASS" if shutil.which(tool) else "WARN", tool, "found" if shutil.which(tool) else "not on PATH")
    venv_python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if venv_python.exists():
        result = subprocess.run([str(venv_python), "-m", "pip", "check"], cwd=root, capture_output=True, text=True)
        rep.add("PASS" if result.returncode == 0 else "WARN", ".venv",
                "dependencies consistent" if result.returncode == 0 else result.stdout.strip()[-300:])


def doctor_customs(root: Path, rep: Report) -> None:
    customs = root / "customs"
    registry = (root / CUSTOMS_FILE).read_text(encoding="utf-8") if (root / CUSTOMS_FILE).exists() else ""
    registered_paths = set(re.findall(r"customs/(?:skills|templates|tools)/[A-Za-z0-9_.-]+", registry))
    for ref in sorted(registered_paths):
        if not (root / ref).exists():
            rep.add("FAIL", "customs", f"{CUSTOMS_FILE} registers {ref}/ but it does not exist")
    items = []
    for kind in ("skills", "templates", "tools"):
        folder = customs / kind
        if folder.is_dir():
            items += [(kind, entry) for entry in sorted(folder.iterdir()) if entry.is_dir() and not entry.name.startswith((".", "_"))]
    for kind, entry in items:
        ref = f"customs/{kind}/{entry.name}"
        if ref not in registered_paths:
            rep.add("WARN", "customs", f"{ref}/ is not registered in {CUSTOMS_FILE}")
        if kind == "skills" and not (entry / "SKILL.md").exists():
            rep.add("WARN", "customs", f"{ref}/ has no SKILL.md")
        if kind == "templates" and not (entry / "template.toml").exists():
            rep.add("WARN", "customs", f"{ref}/ has no template.toml")
        official = [root / kind / entry.name] + ([root / ".agents" / "skills" / entry.name] if kind == "skills" else [])
        if any(path.exists() for path in official):
            rep.add("INFO", "customs", f"{ref}/ overrides the official {kind[:-1]} {entry.name}")
    if items and not any(level in ("FAIL", "WARN") and check == "customs" for level, check, _ in rep.items):
        rep.add("PASS", "customs", f"{len(items)} customs item(s) registered")


def doctor_env(root: Path, rep: Report) -> None:
    expected = env_keys(root / "env.example")
    present = env_keys(root / ".env")
    missing = [key for key in expected if not present.get(key)]
    if missing:
        rep.add("WARN", ".env", "not set (needed only by features that use them): " + ", ".join(missing))
    elif expected:
        rep.add("PASS", ".env", "all keys from env.example are set")


def doctor_smoke(root: Path, rep: Report) -> None:
    candidates = []
    for base in (root / "templates",):
        if base.is_dir():
            candidates += sorted(p for p in base.iterdir() if (p / "remotion" / "src" / "index.ts").exists())
    preferred = ["podcast-karaoke-frame", "agency-life-template", "typography-data-explainer"]
    candidates.sort(key=lambda p: (preferred.index(p.name) if p.name in preferred else len(preferred), p.name))
    if not candidates:
        rep.add("INFO", "smoke render", "skipped: nothing to render in this edition")
        return
    template = candidates[0]
    contract = tomllib.loads((template / "template.toml").read_text(encoding="utf-8"))
    composition = contract.get("remotion", {}).get("composition_id", "MainVideo")
    work = Path(tempfile.mkdtemp(prefix="vas-smoke-", dir=root / ".vas" if (root / ".vas").exists() else None))
    try:
        shutil.copytree(template / "remotion", work / "remotion",
                        ignore=shutil.ignore_patterns(*EXCLUDED_DIR_NAMES), symlinks=True)
        (work / "remotion" / "node_modules").symlink_to(root / "node_modules", target_is_directory=True)
        out = work / "still.png"
        cli = root / "node_modules" / ".bin" / ("remotion.cmd" if os.name == "nt" else "remotion")
        result = subprocess.run([str(cli), "still", "src/index.ts", composition, str(out), "--frame=0", "--scale=0.25"],
                                cwd=work / "remotion", capture_output=True, text=True, timeout=600)
        if result.returncode == 0 and out.exists() and out.stat().st_size > 0:
            rep.add("PASS", "smoke render", f"rendered a still of {template.name}/{composition}")
        else:
            tail = (result.stderr or result.stdout).strip().splitlines()[-3:]
            rep.add("FAIL", "smoke render", f"{template.name}: " + " | ".join(tail))
    except (OSError, subprocess.TimeoutExpired) as exc:
        rep.add("FAIL", "smoke render", f"{template.name}: {exc}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


def cmd_doctor(root: Path, args: argparse.Namespace) -> int:
    rep = Report()
    doctor_integrity(root, rep)
    doctor_skills(root, rep)
    doctor_dependencies(root, rep)
    doctor_customs(root, rep)
    doctor_env(root, rep)
    if args.smoke:
        doctor_smoke(root, rep)
    width = max(len(check) for _, check, _ in rep.items)
    for level, check, detail in rep.items:
        print(f"  [{level:4}] {check:<{width}}  {detail}")
    counts = {level: sum(1 for item in rep.items if item[0] == level) for level in ("PASS", "WARN", "FAIL")}
    print(f"\nDoctor: {counts['PASS']} pass, {counts['WARN']} warn, {counts['FAIL']} fail")
    (root / ".vas").mkdir(exist_ok=True)
    (root / ".vas" / "doctor-report.json").write_text(
        json.dumps([{"level": l, "check": c, "detail": d} for l, c, d in rep.items], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return 1 if rep.failed else 0


# --------------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    publish = sub.add_parser("publish", help="publish Premium, or `publish basic` for the public Basic repository")
    publish.add_argument("target", nargs="?", choices=["basic"], help="omit to publish Premium")
    publish.add_argument("--dry-run", action="store_true", help="basic: build and check the export only")
    publish.add_argument("--list", action="store_true", help="basic: print every exported file")
    publish.add_argument("--out", help="basic: staging folder (default .vas/staging/basic)")
    publish.add_argument("--yes", action="store_true", help="push without asking")
    publish.add_argument("--no-push", action="store_true", help="premium: build the ZIP only")
    publish.add_argument("--include-untracked", action="store_true",
                         help="premium: include untracked, non-ignored files (local testing; never pushes)")
    publish.add_argument("--zip-out", help="premium: ZIP path (default exports/releases/vas-premium-<version>.zip)")

    upgrade = sub.add_parser("upgrade", help="upgrade to Premium from a ZIP, or roll back")
    upgrade.add_argument("zip", nargs="?")
    upgrade.add_argument("--rollback", action="store_true")
    upgrade.add_argument("--allow-downgrade", action="store_true")
    upgrade.add_argument("--no-smoke", action="store_true", help="skip the smoke render in the final doctor run")

    doctor = sub.add_parser("doctor", help="check that the installation works")
    doctor.add_argument("--smoke", action="store_true", help="also render a still of one template")

    parser.add_argument("--root", default=str(REPO_ROOT), help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    sys.stdout.reconfigure(line_buffering=True)
    try:
        if args.command == "publish":
            return cmd_publish_basic(root, args) if args.target == "basic" else cmd_publish_premium(root, args)
        if args.command == "upgrade":
            return cmd_upgrade(root, args)
        return cmd_doctor(root, args)
    except VasError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
