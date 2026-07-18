"""Setuptools hook that places canonical runtime assets inside the wheel."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py


ROOT = Path(__file__).resolve().parent


class BuildPyWithAssets(build_py):
    def run(self):
        super().run()
        manifest = json.loads((ROOT / "install_manifest.json").read_text(encoding="utf-8"))
        target = Path(self.build_lib) / "sudarshan_assets"
        target.mkdir(parents=True, exist_ok=True)

        root_files = set(manifest.get("required_root_files", []))
        root_files.update({"VERSION", "install_manifest.json", "LICENSE", "README.md"})
        for relative in sorted(root_files):
            source = ROOT / relative
            if not source.is_file() or source.suffix == ".py":
                continue
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

        bundle_directories = set(manifest.get("required_bundle_directories", []))
        for relative in sorted(bundle_directories):
            source = ROOT / relative
            if source.is_dir():
                shutil.copytree(source, target / relative, dirs_exist_ok=True)

        for relative in manifest.get("required_openclaw_plugin_files", []):
            source = ROOT / relative
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)


setup(cmdclass={"build_py": BuildPyWithAssets})
