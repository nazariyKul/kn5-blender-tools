# Contributing

Use Python 3.11 or newer for the portable tests and release tooling. Runtime development targets Blender 5.0 and uses its bundled `bpy` and `mathutils` modules. No third-party Python packages are required.

## Development setup

Clone the repository and work in `kn5_blender_tools/`. Build an extension ZIP from the repository root:

```sh
python3 -B tools/build_release.py
```

Install the ZIP from `dist/` through Blender's **Preferences > Get Extensions > Install from Disk**. Disable any earlier Assetto Corsa KN5 Importer installation before testing, because it registers the same operators. Rebuild and reinstall after source changes.

## Tests

Run the portable regression tests without launching Blender:

```sh
python3 -B -m unittest discover -s tests -p 'test_*.py' -v
```

The suite covers parser records, classification, folder discovery, material decisions and native-boundary failure handling. One optional real-sample parser check skips when its private fixture is absent. The repository does not distribute that fixture.

The release builder compiles Python sources in memory, checks the manifest and metadata, and verifies the ZIP's contents, integrity and source-byte parity. It does not launch Blender. Manually check extension installation, single-file import, car-folder import, track-folder import, skin switching and repeat imports in Blender 5.0 before releasing changes. Use assets you have permission to access; do not commit game or mod content.

## Coding expectations

Keep changes focused. Describe the concrete problem, the fix and how you checked it. Preserve working import behavior; avoid broad refactors in bug-fix pull requests. Match the existing code style and prefer the Python standard library over new dependencies.

The custom-normal pipeline is order-sensitive: **establish smooth shading before applying authored KN5 normals**. Do not reorder these operations. Preserve hierarchy transforms, geometry validation and the safeguards for invalid normals or changed topology.

Validate inputs before passing them to Blender native APIs, especially mesh creation, UV assignment and custom-normal operations. Malformed records must fail safely; failed imports must roll back their newly created resources. Preserve the first-import node-tree guard, DDS alpha interpretation and path/resource safeguards.

Do not guess unsupported packed shader-channel meanings or treat expected shader approximation as a correctness bug. Include a focused regression check when fixing a reproducible failure. Keep the version in `__init__.py`, `blender_manifest.toml` and the release documentation consistent.

## Pull requests and reports

Explain the use case before proposing new behavior. Include reproduction steps and relevant test results. Report errors with Blender and addon versions and the import type. Do not post copyrighted KN5 files, cars, tracks, skins or textures publicly. Use synthetic fixtures or assets with clear redistribution permission.
