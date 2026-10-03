# Changelog

## 2.0.2 — Extension manifest correction

- Distribute this version under GPL-3.0-or-later and declare `SPDX:GPL-3.0-or-later` in the Blender manifest.
- Preserve the original MIT copyright and permission notice in `LICENSES/MIT.txt`, including it in the installation ZIP alongside the GPL license and existing reference acknowledgments.
- Shorten the file-access permission reason to fit Blender's 64-character limit, and enforce that limit in the release builder.
- Synchronize addon, manifest and release metadata at 2.0.2. Runtime addon behavior is unchanged.

## 2.0.1 — First public pre-release

This release retains the version already used by the development addon. It packages the existing implementation as KN5 Blender Tools; it does not introduce new import features.

- Direct KN5, car-folder and track-folder imports.
- KN5 hierarchy and transform preservation, authored normals and automatic scene organization.
- Car LOD and skin discovery, skin switching and texture reloads.
- Embedded and external texture handling, DDS alpha handling and supported Blender material conversion.
- Parser and geometry validation, native-input safeguards and rollback on import failures.
- Existing first-import crash protection and resource/path fixes.
- Blender 5.0 extension manifest, installable ZIP, licensing notices, documentation and issue templates.

Materials remain approximations of Assetto Corsa shaders. Bones, skin weights, animation and CSP-specific rendering are outside the supported feature set.
