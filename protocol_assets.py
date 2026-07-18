#!/usr/bin/env python3
"""Shared release/install/template assets for Sudarshan."""

from __future__ import annotations

import json
import os
import shutil
from importlib.resources import files
from pathlib import Path
from typing import Any, Dict


_CODE_ROOT = Path(__file__).resolve().parent


def _find_asset_root() -> Path:
    if (_CODE_ROOT / "VERSION").is_file() and (_CODE_ROOT / "templates").is_dir():
        return _CODE_ROOT
    packaged = files("sudarshan_assets")
    packaged_path = Path(str(packaged))
    if not (packaged_path / "VERSION").is_file():
        raise RuntimeError("Sudarshan runtime assets are missing from this installation")
    return packaged_path


_ASSET_ROOT = _find_asset_root()


def repo_root() -> str:
    return str(_ASSET_ROOT)


def repo_path(*parts: str) -> str:
    return str(_ASSET_ROOT.joinpath(*parts))


def templates_root() -> str:
    return repo_path("templates")


def load_version() -> str:
    return _ASSET_ROOT.joinpath("VERSION").read_text(encoding="utf-8").strip()


def load_install_manifest() -> Dict[str, Any]:
    path = _ASSET_ROOT / "install_manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != load_version():
        raise ValueError("install_manifest.json version does not match VERSION")
    return data


def template_path(relative_path: str) -> str:
    clean = relative_path.replace("\\", "/")
    if clean.startswith("templates/"):
        clean = clean.split("templates/", 1)[1]
    return repo_path("templates", *clean.split("/"))


def _render_text(raw: str) -> str:
    return raw.replace("{{VERSION}}", load_version())


def load_template_text(relative_path: str) -> str:
    path = Path(template_path(relative_path))
    return _render_text(path.read_text(encoding="utf-8"))


def load_template_json(relative_path: str) -> Dict[str, Any]:
    return json.loads(load_template_text(relative_path))


def write_text(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Path(path).write_text(content, encoding="utf-8")


def write_json(path: str, data: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def install_template(relative_path: str, destination_path: str, overwrite: bool = False) -> bool:
    if os.path.exists(destination_path) and not overwrite:
        return False
    if relative_path.endswith(".json"):
        write_json(destination_path, load_template_json(relative_path))
    else:
        write_text(destination_path, load_template_text(relative_path))
    return True


def install_required_templates(workspace_root: str, overwrite: bool = False) -> Dict[str, bool]:
    manifest = load_install_manifest()
    results: Dict[str, bool] = {}
    for relative_path in manifest["required_template_files"]:
        relative_template = relative_path.split("templates/", 1)[1]
        if relative_template.startswith("enterprise_state/"):
            destination = os.path.join(workspace_root, relative_template)
        elif relative_template.startswith("workspace/"):
            destination = os.path.join(workspace_root, relative_template.split("workspace/", 1)[1])
        else:
            destination = os.path.join(workspace_root, relative_template)
        results[relative_template] = install_template(relative_template, destination, overwrite=overwrite)
    return results


def copy_required_root_files(destination_root: str, overwrite: bool = False) -> Dict[str, bool]:
    manifest = load_install_manifest()
    copied: Dict[str, bool] = {}
    for relative_path in manifest["required_root_files"]:
        code_source = _CODE_ROOT / relative_path
        asset_source = _ASSET_ROOT / relative_path
        source = str(code_source if code_source.is_file() else asset_source)
        destination = os.path.join(destination_root, relative_path)
        if os.path.exists(destination) and not overwrite:
            copied[relative_path] = False
            continue
        os.makedirs(os.path.dirname(destination) or destination_root, exist_ok=True)
        shutil.copy2(source, destination)
        copied[relative_path] = True
    return copied


def copy_required_plugin_files(destination_root: str, overwrite: bool = False) -> Dict[str, bool]:
    manifest = load_install_manifest()
    copied: Dict[str, bool] = {}
    for relative_path in manifest["required_openclaw_plugin_files"]:
        source = os.path.join(repo_root(), relative_path)
        destination = os.path.join(destination_root, relative_path)
        if os.path.exists(destination) and not overwrite:
            copied[relative_path] = False
            continue
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copy2(source, destination)
        copied[relative_path] = True
    return copied


def copy_required_bundle_directories(destination_root: str, overwrite: bool = True) -> Dict[str, bool]:
    manifest = load_install_manifest()
    copied: Dict[str, bool] = {}
    for relative_path in manifest.get("required_bundle_directories", []):
        source = os.path.join(repo_root(), relative_path)
        destination = os.path.join(destination_root, relative_path)
        if os.path.exists(destination) and not overwrite:
            copied[relative_path] = False
            continue
        shutil.copytree(source, destination, dirs_exist_ok=True)
        copied[relative_path] = True
    return copied


def ensure_required_directories(destination_root: str) -> None:
    manifest = load_install_manifest()
    for relative_path in manifest["required_directories"]:
        os.makedirs(os.path.join(destination_root, relative_path), exist_ok=True)
