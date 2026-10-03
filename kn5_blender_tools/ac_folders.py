"""Assetto Corsa folder discovery. No Blender dependency."""

from configparser import ConfigParser, Error as ConfigError
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re


@dataclass(frozen=True)
class CarLOD:
    key: str
    label: str
    path: Path


@dataclass(frozen=True)
class TrackPart:
    path: Path
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class TrackLayout:
    key: str
    label: str
    parts: tuple[TrackPart, ...]


def _ini(path):
    config = ConfigParser(interpolation=None, strict=False, inline_comment_prefixes=(";", "#"))
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeError:
        text = path.read_text(encoding="cp1252")
    try:
        config.read_string(text)
    except ConfigError as exc:
        raise ValueError(f"Invalid Assetto Corsa INI {path}: {exc}") from exc
    return config


def _kn5(folder, filename, *, root=None):
    root = (root or folder).resolve()
    path = (folder / filename.strip().strip('"').replace("\\", "/")).resolve()
    if path.suffix.lower() != ".kn5" or not path.is_relative_to(root):
        raise ValueError(f"Invalid KN5 path: {filename}")
    if not path.is_file():
        candidate = root
        for part in path.relative_to(root).parts:
            if not candidate.is_dir():
                return None
            candidate = next((p for p in candidate.iterdir() if p.name.casefold() == part.casefold()), None)
            if candidate is None:
                return None
        path = candidate.resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"Invalid KN5 path: {filename}")
    return path if path.is_file() else None


def car_lods(folder):
    """Return available visual LODs, best quality first."""
    folder = Path(folder).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError(f"Car folder does not exist: {folder}")
    ini = folder / "data" / "lods.ini"
    if ini.is_file():
        config = _ini(ini)
        result = []
        sections = sorted((s for s in config.sections() if re.fullmatch(r"LOD_\d+", s, re.I)),
                          key=lambda s: int(s.split("_")[-1]))
        for section in sections:
            path = _kn5(folder, config.get(section, "FILE", fallback="")) if config.has_option(section, "FILE") else None
            if path and path.stem.lower() not in {"collider", "collision"}:
                result.append(CarLOD(section.upper(), section.upper().replace("_", " "), path))
        if result:
            return tuple(result)
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".kn5"
             and p.stem.lower() not in {"collider", "collision"}]
    main = next((p for p in files if p.stem.casefold() == folder.name.casefold()), None)
    if main:
        return (CarLOD("MAIN", "Main", main),)
    primary = [p for p in files if not re.search(r"[_-]lod[_-]?[a-z0-9]+$", p.stem, re.I)]
    if len(primary) == 1:
        return (CarLOD("MAIN", "Main", primary[0]),)
    if not primary and files and all(re.search(r"[_-]lod[_-]?[a-z0-9]+$", p.stem, re.I) for p in files):
        return tuple(CarLOD(p.stem, p.stem, p) for p in sorted(files, key=lambda p: p.stem.casefold()))
    if not files:
        raise ValueError(f"No visual KN5 found in {folder}")
    raise ValueError(f"Multiple visual KN5 files in {folder}; add data/lods.ini to identify the main model")


def car_skins(folder):
    folder = Path(folder)
    skins = (folder.parent if folder.suffix.lower() == ".kn5" else folder) / "skins"
    if not skins.is_dir():
        return ()
    result = []
    for path in sorted((p for p in skins.iterdir() if p.is_dir()), key=lambda p: p.name.casefold()):
        label = path.name
        info = path / "ui_skin.json"
        if info.is_file():
            try:
                metadata = json.loads(info.read_text(encoding="utf-8-sig"))
                if isinstance(metadata, dict):
                    label = metadata.get("skinname") or label
            except (OSError, UnicodeError, ValueError):
                pass
        result.append((path.name, str(label), path))
    return tuple(result)


def _triple(value):
    try:
        parts = tuple(float(v.strip()) for v in value.split(","))
    except ValueError as exc:
        raise ValueError(f"Invalid track model transform: {value}") from exc
    if len(parts) != 3 or not all(math.isfinite(value) for value in parts):
        raise ValueError(f"Invalid track model transform: {value}")
    return parts


def track_layouts(folder):
    """Use models*.ini to identify visual track parts; never import stray KN5s."""
    folder = Path(folder).expanduser().resolve()
    if not folder.is_dir():
        raise ValueError(f"Track folder does not exist: {folder}")
    configs = sorted(folder.glob("models*.ini"), key=lambda p: (p.name != "models.ini", p.name))
    configs += sorted((p for p in folder.glob("*/models.ini") if p.is_file()), key=lambda p: str(p))
    layouts = []
    for ini in configs:
        config = _ini(ini)
        parts = []
        sections = sorted((s for s in config.sections() if re.fullmatch(r"MODEL_\d+", s, re.I)),
                          key=lambda s: int(s.split("_")[-1]))
        for section in sections:
            filename = config.get(section, "FILE", fallback="")
            if Path(filename.strip().strip('"').replace("\\", "/")).stem.casefold() in {"collider", "collision"}:
                continue
            path = _kn5(ini.parent, filename, root=folder) if filename else None
            if path is None and ini.parent != folder and filename:
                path = _kn5(folder, filename)
            if filename and path is None:
                raise FileNotFoundError(f"Missing track model {filename!r} in {ini} [{section}]")
            if path and path.stem.casefold() not in {"collider", "collision"}:
                parts.append(TrackPart(path,
                    _triple(config.get(section, "POSITION", fallback="0,0,0")),
                    _triple(config.get(section, "ROTATION", fallback="0,0,0"))))
        if parts:
            key = "DEFAULT" if ini == folder / "models.ini" else ini.stem.removeprefix("models_")
            if ini.parent != folder:
                key = ini.parent.name
            layouts.append(TrackLayout(key, "Default" if key == "DEFAULT" else key,
                                       tuple(parts)))
    if layouts:
        return tuple(layouts)
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".kn5"
             and p.stem.casefold() not in {"collider", "collision"}]
    if len(files) == 1:
        return (TrackLayout("DEFAULT", "Default", (TrackPart(files[0]),)),)
    if not files:
        raise ValueError(f"No visual KN5 or models.ini found in {folder}")
    raise ValueError(f"Multiple KN5 files in {folder}; models.ini is needed to identify visual track parts")
