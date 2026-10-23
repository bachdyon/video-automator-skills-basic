from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "vas.py"
SPEC = importlib.util.spec_from_file_location("vas", SCRIPT)
assert SPEC and SPEC.loader
vas = importlib.util.module_from_spec(SPEC)
sys.modules["vas"] = vas
SPEC.loader.exec_module(vas)

# Built from constants so this file never contains a bare marker line itself
# (publish basic strips those from every shipped text file).
START, END = vas.MARKER_START, vas.MARKER_END
BSTART, BEND = vas.BASIC_START, vas.BASIC_END


class FilterTests(unittest.TestCase):
    def test_strips_marked_blocks_including_hash_prefixed_markers(self) -> None:
        text = f"keep 1\n{START}\nsecret rule\n{END}\nkeep 2\n# {START}\nKIE_API_KEY=\n# {END}\n"
        self.assertEqual(vas.strip_premium_blocks(text, "x.md"), "keep 1\nkeep 2\n")

    def test_rejects_unbalanced_markers(self) -> None:
        with self.assertRaises(vas.VasError):
            vas.strip_premium_blocks(f"{START}\nno end\n", "x.md")
        with self.assertRaises(vas.VasError):
            vas.strip_premium_blocks(f"{END}\n", "x.md")
        with self.assertRaises(vas.VasError):
            vas.strip_premium_blocks(f"{START}\n{START}\n{END}\n", "x.md")

    def test_basic_only_blocks(self) -> None:
        text = f"shared\n{START}\npremium intro\n{END}\n{BSTART}\nbasic intro\n{BEND}\nend\n"
        self.assertEqual(vas.strip_premium_blocks(text, "README.md"), "shared\nbasic intro\nend\n")
        self.assertEqual(
            vas.strip_basic_blocks(text, "README.md"),
            f"shared\n{START}\npremium intro\n{END}\nend\n",
        )
        with self.assertRaises(vas.VasError):
            vas.strip_basic_blocks(f"{BSTART}\nx\n{END}\n", "README.md")

    def test_premium_zip_drops_basic_only_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(f"a\n{BSTART}\nbasic only\n{BEND}\nb\n", encoding="utf-8")
            overrides = vas.basic_only_overrides(root, ["README.md"])
            self.assertEqual(overrides["README.md"], b"a\nb\n")
            manifest = vas.build_manifest(root, ["README.md"], "premium", "1.0.0", overrides)
            archive = root / "p.zip"
            vas.write_zip(root, ["README.md"], manifest, archive, overrides)
            _, read_back = vas.read_package(archive)
            self.assertEqual(read_back["files"]["README.md"]["sha256"], vas.sha256_bytes(b"a\nb\n"))

    def test_inline_marker_mentions_are_kept(self) -> None:
        text = f"Wrap Premium text with `{START}`.\n"
        self.assertEqual(vas.strip_premium_blocks(text, "x.md"), text)

    def test_drops_premium_list_lines_only(self) -> None:
        text = (
            "- `$basic-skill`: ok\n"
            "- `$paid-gen`: premium\n"
            "- `templates/paid-tpl/` → `$paid-tpl-template`\n"
            "- `templates/podcast/` → `$podcast-template`\n"
            "Plain $paid-gen mention stays for the lint to catch.\n"
        )
        out = vas.drop_premium_list_lines(
            text,
            keep_skills={"basic-skill", "podcast-template"},
            premium_skills={"paid-gen", "paid-tpl-template"},
            keep_templates={"podcast"},
            premium_templates={"paid-tpl"},
        )
        self.assertIn("$basic-skill", out)
        self.assertIn("templates/podcast/", out)
        self.assertNotIn("`$paid-gen`: premium", out)
        self.assertNotIn("templates/paid-tpl/", out)
        self.assertIn("Plain $paid-gen mention", out)

    def test_template_skill_mapping(self) -> None:
        text = (
            "- `templates/a/` → `$a-template`\n"
            "- `templates/b/` → add/use matching `$b-template` before reuse\n"
        )
        self.assertEqual(vas.template_skill_mapping(text), {"a": "a-template"})


class PathSafetyTests(unittest.TestCase):
    def test_safe_rel_rejects_traversal_and_absolute(self) -> None:
        for bad in ("../evil", "a/../../evil", "/etc/passwd", "C:/x", "a\\b", "./a", ""):
            with self.assertRaises(vas.VasError, msg=bad):
                vas.safe_rel(bad)
        self.assertEqual(vas.safe_rel("skills/a/SKILL.md"), "skills/a/SKILL.md")

    def test_symlink_must_stay_inside(self) -> None:
        self.assertTrue(vas.symlink_stays_inside(".claude/skills/a", "../../skills/a"))
        self.assertFalse(vas.symlink_stays_inside(".claude/skills/a", "../../../outside"))
        self.assertFalse(vas.symlink_stays_inside("a", "/etc"))

    def test_protected_paths(self) -> None:
        for rel in ("AGENTS.customs.md", "customs/skills/x/SKILL.md", "jobs/1/a", ".env", ".env.local", ".vas/backups/x"):
            self.assertTrue(vas.is_protected(rel), rel)
        for rel in ("AGENTS.md", "skills/a/SKILL.md", "env.example", "skills/a/.env.example"):
            self.assertFalse(vas.is_protected(rel), rel)


class LintTests(unittest.TestCase):
    def test_reports_every_premium_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            (stage / "skills/basic").mkdir(parents=True)
            (stage / "skills/basic/SKILL.md").write_text(
                "Use `$paid-gen` then python -m tools.paid_index.search.\n"
                "See templates/paid-tpl/ and skills/paid-gen/scripts.\n"
                "Shell $HOME and $paid-gen-extra are not skills.\n"
                "Bare `paid-gen` in backticks counts too.\n",
                encoding="utf-8",
            )
            sel = vas.Selection(
                files=["skills/basic/SKILL.md"], skills={"basic"}, agent_skills=set(), templates=set(),
                tools=set(), packages=set(), premium_skills={"paid-gen"}, premium_templates={"paid-tpl"},
                premium_tools={"paid_index"}, premium_packages=set(),
            )
            problems = vas.lint_references(stage, sel, sel.files)
            refs = sorted(p.rsplit(" ", 1)[-1] for p in problems)
            self.assertEqual(refs, ["$paid-gen", "`paid-gen`", "skills/paid-gen", "templates/paid-tpl", "tools/paid_index"])

    def test_template_mentions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stage = Path(tmp)
            write_tree(stage, {
                "README.md": "Use a Template here.\nplain\n",
                ".agents/skills/x/SKILL.md": "project template\n",
                "skills/a/run.py": "pattern = 1\n",
            })
            self.assertEqual(
                vas.template_mentions(stage, ["README.md", ".agents/skills/x/SKILL.md", "skills/a/run.py"]),
                ["README.md:1: mentions templates (Basic has none)"],
            )

    def test_secret_scan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "ok.py").write_text("token = request_headers_authorization_value\n", encoding="utf-8")
            (base / "bad.env.example").write_text("PAID_API_KEY=" + "abc123def456" * 3 + "\n", encoding="utf-8")
            hits = vas.secret_scan(base, ["ok.py", "bad.env.example"])
            self.assertEqual(len(hits), 1)
            self.assertIn("bad.env.example:1", hits[0])

    def test_forbidden_paths(self) -> None:
        files = ["customs/.gitkeep", "customs/skills/x/SKILL.md", "AGENTS.customs.md", ".env", ".env.example",
                 "raw_assets/README.md", "raw_assets/videos/a.mp4", "basic.toml", "skills/a/SKILL.md"]
        self.assertEqual(
            vas.forbidden_paths(files),
            ["customs/skills/x/SKILL.md", "AGENTS.customs.md", ".env", "raw_assets/videos/a.mp4", "basic.toml"],
        )


def write_tree(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def install_manifest(root: Path, edition: str, version: str, files: list[str]) -> None:
    manifest = vas.build_manifest(root, files, edition, version)
    (root / vas.MANIFEST_REL).parent.mkdir(parents=True, exist_ok=True)
    (root / vas.MANIFEST_REL).write_text(json.dumps(manifest), encoding="utf-8")


class UpgradeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.install = base / "install"
        self.source = base / "premium"

        basic_files = {
            "VERSION": 'edition = "basic"\nversion = "1.0.0"\n',
            "AGENTS.md": "basic agents\n",
            "skills/core/SKILL.md": "core v1\n",
            "skills/old/SKILL.md": "dropped in premium\n",
            "customs/.gitkeep": "",
        }
        write_tree(self.install, basic_files)
        install_manifest(self.install, "basic", "1.0.0", sorted(basic_files))
        # User data and a hand edit.
        write_tree(self.install, {
            "AGENTS.customs.md": "mine\n",
            "customs/skills/demo/SKILL.md": "demo\n",
            "jobs/j1/note.txt": "keep\n",
            ".env": "OPENAI_API_KEY=x\n",
        })
        (self.install / "skills/core/SKILL.md").write_text("core v1 + my tweak\n", encoding="utf-8")

        premium_files = {
            "VERSION": 'edition = "premium"\nversion = "1.1.0"\n',
            "AGENTS.md": "premium agents\n",
            "skills/core/SKILL.md": "core v2\n",
            "skills/paid-gen/SKILL.md": "kie\n",
            "customs/.gitkeep": "",
            "AGENTS.customs.md": "must never overwrite\n",
        }
        write_tree(self.source, premium_files)
        files = sorted(premium_files)
        self.zip_path = base / "vas-premium-1.1.0.zip"
        vas.write_zip(self.source, files, vas.build_manifest(self.source, files, "premium", "1.1.0"), self.zip_path)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def upgrade(self, *extra: str) -> int:
        args = argparse.Namespace(zip=str(self.zip_path), rollback=False, allow_downgrade=False, no_smoke=True)
        for flag in extra:
            setattr(args, flag, True)
        ok = subprocess.CompletedProcess(args=[], returncode=0)
        with patch.object(vas, "post_install"), patch.object(vas.subprocess, "run", return_value=ok), \
                redirect_stdout(StringIO()):
            return vas.cmd_upgrade(self.install, args)

    def read(self, rel: str) -> str:
        return (self.install / rel).read_text(encoding="utf-8")

    def test_upgrade_applies_premium_and_protects_user_data(self) -> None:
        self.assertEqual(self.upgrade(), 0)
        self.assertEqual(vas.read_version(self.install), {"edition": "premium", "version": "1.1.0"})
        self.assertEqual(self.read("skills/core/SKILL.md"), "core v2\n")
        self.assertEqual(self.read("skills/paid-gen/SKILL.md"), "kie\n")
        self.assertFalse((self.install / "skills/old").exists())
        self.assertEqual(self.read("AGENTS.customs.md"), "mine\n")
        self.assertEqual(self.read("customs/skills/demo/SKILL.md"), "demo\n")
        self.assertEqual(self.read("jobs/j1/note.txt"), "keep\n")
        self.assertEqual(self.read(".env"), "OPENAI_API_KEY=x\n")
        saved = list((self.install / "customs/_upgrade_backup").glob("*/skills/core/SKILL.md"))
        self.assertEqual([p.read_text(encoding="utf-8") for p in saved], ["core v1 + my tweak\n"])

    def test_rollback_restores_previous_state(self) -> None:
        self.assertEqual(self.upgrade(), 0)
        with redirect_stdout(StringIO()):
            self.assertEqual(vas.rollback(self.install), 0)
        self.assertEqual(vas.read_version(self.install), {"edition": "basic", "version": "1.0.0"})
        self.assertEqual(self.read("skills/core/SKILL.md"), "core v1 + my tweak\n")
        self.assertEqual(self.read("skills/old/SKILL.md"), "dropped in premium\n")
        self.assertFalse((self.install / "skills/paid-gen").exists())
        self.assertEqual(json.loads(self.read(vas.MANIFEST_REL))["edition"], "basic")
        self.assertEqual(self.read("AGENTS.customs.md"), "mine\n")

    def test_refuses_downgrade(self) -> None:
        self.assertEqual(self.upgrade(), 0)
        (self.install / "VERSION").write_text('edition = "premium"\nversion = "2.0.0"\n', encoding="utf-8")
        with self.assertRaises(vas.VasError):
            self.upgrade()

    def test_rejects_corrupt_and_unsafe_packages(self) -> None:
        corrupt = self.zip_path.with_name("corrupt.zip")
        with zipfile.ZipFile(self.zip_path) as zin, zipfile.ZipFile(corrupt, "w") as zout:
            for info in zin.infolist():
                data = zin.read(info.filename)
                zout.writestr(info, data + b"!" if info.filename == "AGENTS.md" else data)
        with self.assertRaises(vas.VasError):
            vas.read_package(corrupt)

        evil = self.zip_path.with_name("evil.zip")
        manifest = {"edition": "premium", "version": "9.9.9",
                    "files": {"../evil.txt": {"sha256": vas.sha256_bytes(b"x"), "size": 1}}}
        with zipfile.ZipFile(evil, "w") as zf:
            zf.writestr(vas.MANIFEST_REL, json.dumps(manifest))
            zf.writestr("../evil.txt", b"x")
        with self.assertRaises(vas.VasError):
            vas.read_package(evil)
        self.assertFalse((self.install.parent / "evil.txt").exists())

    def test_zip_keeps_symlinks_and_repair_restores_them(self) -> None:
        import os
        src = self.source
        (src / ".claude/skills").mkdir(parents=True)
        os.symlink("../../skills/core", src / ".claude/skills/core")
        files = ["skills/core/SKILL.md", ".claude/skills/core"]
        archive = self.zip_path.with_name("links.zip")
        vas.write_zip(src, files, vas.build_manifest(src, files, "premium", "1.2.0"), archive)
        with zipfile.ZipFile(archive) as zf:
            info = zf.getinfo(".claude/skills/core")
            self.assertEqual(info.external_attr >> 16 & 0o170000, 0o120000)

            # A tool that ignores symlink entries leaves a plain text file behind.
            target = self.install.parent / "plain"
            for name in zf.namelist():
                out = target / name
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(zf.read(name))
        link = target / ".claude/skills/core"
        self.assertFalse(link.is_symlink())
        with redirect_stdout(StringIO()):
            self.assertEqual(vas.cmd_repair(target, argparse.Namespace()), 0)
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), "../../skills/core")

    def test_rejects_basic_package(self) -> None:
        files = ["VERSION"]
        basic_zip = self.zip_path.with_name("basic.zip")
        vas.write_zip(self.source, files, vas.build_manifest(self.source, files, "basic", "1.1.0"), basic_zip)
        with self.assertRaises(vas.VasError):
            vas.read_package(basic_zip)


if __name__ == "__main__":
    unittest.main()
