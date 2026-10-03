"""Assetto Corsa KN5 direct importer for Blender."""

bl_info = {
    "name": "KN5 Blender Tools",
    "author": "KN5 Importer contributors",
    "version": (2, 0, 2),
    "blender": (5, 0, 0),
    "location": "File > Import > Assetto Corsa",
    "description": "Import Assetto Corsa KN5 files, car folders, skins and tracks",
    "category": "Import-Export",
}


def register():
    from .addon import register as do_register
    do_register()


def unregister():
    from .addon import unregister as do_unregister
    do_unregister()
