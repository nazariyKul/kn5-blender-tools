# License and provenance audit

Reviewed on 2026-10-03 for version 2.0.1, with distribution licensing updated for version 2.0.2.

## Decision

Distribute version 2.0.2 under the GNU General Public License, version 3 or (at the recipient's option) any later version. The extension declares `SPDX:GPL-3.0-or-later`. LICENSE contains the explicit grant and full GPLv3 text. This corrects the addon's Blender Extensions licensing requirement; the initial 2.0.1 manifest's MIT declaration did not satisfy that requirement.

The existing MIT terms permit sublicensing and distribution subject to preserving their copyright and permission notice. The complete original MIT LICENSE is preserved byte-for-byte in LICENSES/MIT.txt and included in the installation ZIP. The existing `Copyright (c) 2026 KN5 Importer contributors` attribution is unchanged. Earlier MIT grants, including version 2.0.1, are not revoked. No new license is assigned to reference-project code or game assets, and no third-party ownership is claimed.

The owner explicitly confirmed during release preparation: “Only format facts were used; no code copied, translated, or adapted.” The reviewed code and existing provenance statements support that account. No unresolved licensing publication blocker was identified on this basis. This is a source/provenance review, not a legal opinion or a guarantee about undocumented history.

## Evidence and scope

- The development workspace had no Git repository or commit history. Both existing LICENSE files used MIT; the parser header and README described an independent implementation using observed KN5 record layout.
- The local MarvinSt reference file was byte-identical to upstream `convert.py` at revision `5de5ccdb0a7ade3a8dac8583d4558397b3045b14`.
- All ten addon Python modules were compared with that reference. No identical function or class AST definitions were found. The longest identical sequence of stripped, nonblank, noncomment source lines was one line, consisting of common Python statements. These checks support the review but cannot independently prove absence of translation or adaptation.
- The addon uses a bounded reader, dataclass records, recursive hierarchy parsing, record/geometry validation and direct Blender scene construction. The reference uses converter-specific model classes, flat node lists, NumPy transformation helpers and OBJ/FBX output. Shared field order, record sizes, shader names and UV conventions describe the file format.
- The owner confirmation supplies the historical provenance that a source comparison and an unversioned workspace cannot establish alone.
- Imports were reviewed across the addon. Runtime dependencies are Blender APIs and Python's standard library. No bundled third-party libraries or assets were found in the release allowlist.

## Upstream licenses and obligations

GitHub metadata and complete source trees were checked for MarvinSt/kn5-obj-converter at `5de5ccdb0a7ade3a8dac8583d4558397b3045b14` and RaduMC/kn5-converter at `79c126a07d8307d8477a99a1df241d1434838dc3`. Both returned no detected license; neither reviewed tree contained a license file. MarvinSt's README credits the RaduMC project, and RaduMC's main source did not contain a permission grant. Do not copy code from either project without resolving permission.

The previous reliability investigation also cited AcTools for visibility/renderability field meanings. AcTools declares MS-PL in `LICENSE.txt`. No AcTools source was identified in the addon. If its code were incorporated later, its license would need to be evaluated: MS-PL requires retaining applicable notices, and distribution of covered source must use that license. No such source is included in this release.

On the confirmed facts-only reference use, no upstream code-license obligations were identified for the current addon. References remain acknowledged in THIRD_PARTY_NOTICES.md. The installation ZIP includes the GPL LICENSE and the original MIT copyright and permission notice in LICENSES/MIT.txt. Distribution of this GPL-covered version must comply with GPL-3.0-or-later, including its corresponding-source obligations; the matching source is published in this repository. Preserve the original MIT notice in copies or substantial portions as its terms require.

## Distribution boundary

The public repository was assembled from an explicit source/test/documentation selection in a separate directory. Downloaded reference projects, private KN5 samples, cars, tracks, skins, textures, Blender files, reports, renders and local caches stay outside it. The installation ZIP uses a fixed allowlist of runtime modules, manifest and license notices.

If later evidence contradicts the owner confirmation, stop distributing affected code until its permission or independent replacement is established. Do not infer a license grant from an upstream project's public visibility.
