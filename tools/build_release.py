"""Build and verify the extension ZIP without importing Blender or the addon."""

import ast
from pathlib import Path
import re
import tomllib
import zipfile


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "kn5_blender_tools"
MODULES = (
    "__init__.py", "ac_folders.py", "ac_ui.py", "addon.py", "classification.py",
    "kn5.py", "organize.py", "scene.py", "skins.py", "tracks.py",
)


def main():
    manifest_path = PACKAGE / "blender_manifest.toml"
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    expected = {
        "schema_version": "1.0.0", "id": "kn5_blender_tools",
        "name": "KN5 Blender Tools", "type": "add-on",
        "blender_version_min": "5.0.0", "license": ["SPDX:MIT"],
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ValueError(f"Unexpected manifest field: {key}")
    version = manifest["version"]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Version must use major.minor.patch")
    if not manifest.get("maintainer") or not 1 <= len(manifest["tagline"]) <= 64:
        raise ValueError("Maintainer and a tagline of at most 64 characters are required")
    if manifest.get("tags") != ["Import-Export"]:
        raise ValueError("Unexpected extension tags")
    if not 1 <= len(manifest.get("permissions", {}).get("files", "")) <= 128:
        raise ValueError("The files permission needs a concise reason")

    tree = ast.parse((PACKAGE / "__init__.py").read_text(encoding="utf-8"))
    info = next(ast.literal_eval(node.value) for node in tree.body
                if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == "bl_info"
                        for target in node.targets))
    if (info["name"] != manifest["name"]
            or info["version"] != tuple(map(int, version.split(".")))
            or info["blender"] != tuple(map(int, manifest["blender_version_min"].split(".")))):
        raise ValueError("Legacy metadata and manifest disagree")
    for name in ("README.md", "CHANGELOG.md"):
        if version not in (ROOT / name).read_text(encoding="utf-8"):
            raise ValueError(f"Version missing from {name}")

    files = {name: PACKAGE / name for name in MODULES}
    files.update({"blender_manifest.toml": manifest_path, "LICENSE": ROOT / "LICENSE",
                  "THIRD_PARTY_NOTICES.md": ROOT / "THIRD_PARTY_NOTICES.md"})
    for name, path in files.items():
        text = path.read_text(encoding="utf-8")
        if re.search(r"/Users/|/home/|[A-Za-z]:[\\/]Users[\\/]", text):
            raise ValueError(f"Local absolute path in {name}")
        if name.endswith(".py"):
            compile(text, name, "exec")

    output = ROOT / "dist" / f"{manifest['id']}-{version}.zip"
    output.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, path in sorted(files.items()):
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, path.read_bytes())
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None or sorted(archive.namelist()) != sorted(files):
            raise ValueError("Archive integrity or file allowlist check failed")
        for name, path in files.items():
            if archive.read(name) != path.read_bytes():
                raise ValueError(f"ZIP source differs: {name}")
    print(f"Built {output.name}: {len(files)} files; manifest, syntax, metadata and ZIP checks passed")


if __name__ == "__main__":
    main()
