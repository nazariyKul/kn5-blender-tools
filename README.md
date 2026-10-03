# KN5 Blender Tools

Import and work with Assetto Corsa KN5 cars and tracks directly in Blender. A free, open-source addon with optional donations.

## Features

- Import a single KN5 file, a car folder, or a track folder without an intermediate OBJ or FBX conversion.
- Preserve KN5 hierarchy, transforms, UVs and authored normals.
- Organize car and track meshes into collections while keeping helper objects in a hidden hierarchy collection.
- Discover car LODs and skins, select an initial skin, and switch or reload skins after importing.
- Load embedded and external textures, pack base textures into the Blender file, and handle DDS alpha according to material usage.
- Convert supported Assetto Corsa material properties into Blender materials.
- Validate parser records and mesh inputs, with rollback on failed scene imports.
- Use the Blender extension package format for Blender 5.x.

## Installation

1. Download `kn5_blender_tools-2.0.1.zip` from this repository's **Releases** page. Use the attached addon ZIP, not GitHub's generated source-code ZIP.
2. In Blender 5.0, open **Edit > Preferences > Get Extensions**.
3. Open the menu in the upper-right corner and select **Install from Disk**. Choose the downloaded ZIP.
4. Enable **KN5 Blender Tools** if Blender does not enable it automatically. It also appears in the **Add-ons** preferences.

If upgrading from the earlier **Assetto Corsa KN5 Importer** development addon, disable that addon first. Both packages register the same import operators.

## Usage

Open the 3D View sidebar with **N**, then choose the **Assetto Corsa** tab. Its import buttons are **KN5 File**, **Car Folder** and **Track Folder**. The same import options appear under **File > Import**.

### KN5 File

Choose **KN5 File** and select a `.kn5` file. The import dialog includes texture, material, hidden-node, scale and organization options. Helper parents remain available in the hidden `KN5_HIERARCHY` collection.

### Car Folder

Choose **Car Folder** and select a car directory, typically under `content/cars`. The addon reads `data/lods.ini` when available and defaults to the highest-quality visual LOD. Choose a different LOD or initial skin in the import dialog if needed. Without a LOD configuration, the addon attempts to identify the main KN5 file.

To change a skin, select an imported car object in the viewport, choose a skin in the **Assetto Corsa** sidebar, and click **Apply Skin**. Use **Reload Skin** after editing texture files. Choose **Base KN5 textures** to restore the original textures. Keep the source car folder available: skin overrides remain linked to files on disk.

### Track Folder

Choose **Track Folder** and select a track directory, typically under `content/tracks`. Select a discovered layout. The addon imports the visual KN5 files listed in its model configuration into an organized track collection. For nonstandard track configurations, use **KN5 File** to import individual files.

The sidebar also provides **Organize Imported KN5** and hierarchy visibility controls. Organization keeps mesh parenting and world transforms intact.

## Known limitations

- Blender materials approximate Assetto Corsa shaders. Complex track, detail and material shaders may differ from Assetto Corsa or Custom Shaders Patch (CSP).
- Packed shader channels with uncertain semantics, including unsupported `txMaps` channels, remain unsupported. CSP-specific rendering behavior is not reproduced.
- Skinned geometry imports in its bind pose. Bones, skin weights and animation are not imported.
- Physics data and game-specific effects are not recreated.
- KN5 layout versions 1–6 are recognized. Unknown versions or node records fail with an error rather than guessing their layout.
- Blender must be able to decode the texture format. Unusual DDS encodings may fail to load; check the import warnings for affected images.
- Car and track discovery relies on their folder and configuration conventions. Unrecognized meshes stay in the `OTHER` category.

## Compatibility

The current development and testing target is **Blender 5.0**. Earlier development checks used Blender 5.0.0. The manifest requires Blender 5.0.0 or newer; compatibility with later 5.x versions has not yet been validated.

Version 2.0.1 preserves the existing development version for this first public pre-release. Final installation and import checks for the extension ZIP are still pending manual testing in Blender.

## Bug reports

Use the bug-report template and include your Blender version, addon version, operating system, import type (single KN5, car folder or track folder), reproduction steps, expected and actual results, and any relevant error or traceback. Import warnings appear in Blender's console.

Do not upload copyrighted KN5 files, cars, tracks, skins or textures publicly. Prefer a small synthetic example or content you own and can legally redistribute. Remove personal paths and credentials from logs before posting them.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, tests and the custom-normal invariants. Bug fixes and small, focused pull requests are welcome.

## Support

KN5 Blender Tools is free and open source. If it saves you time and you would like to support development, donations are appreciated. All features remain available without donating.

<!-- TODO: Add the maintainer's donation URL when one is available. -->

## License

The addon is licensed under the [MIT License](LICENSE). The existing license and copyright notice are preserved. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for format references and [LICENSE_AUDIT.md](LICENSE_AUDIT.md) for the provenance review.

## Disclaimer

This is an independent community project. It is not affiliated with or endorsed by Kunos Simulazioni or Assetto Corsa. Product names and trademarks are used only to describe compatibility. No game or mod assets are included.
