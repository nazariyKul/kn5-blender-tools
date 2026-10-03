"""Direct, Blender-independent reader for Assetto Corsa KN5 files.

The record layout was independently implemented from observations in
MarvinSt/kn5-obj-converter (see README). No converter code is included.
"""

from dataclasses import dataclass, field
from pathlib import Path
import math
import struct


class KN5Error(ValueError):
    pass


@dataclass
class Material:
    name: str
    shader: str
    blend_mode: int = 0
    properties: dict[str, float] = field(default_factory=dict)
    textures: dict[str, str] = field(default_factory=dict)
    alpha_test: bool = False
    depth_mode: int = 0
    vectors: dict[str, dict[str, tuple[float, ...]]] = field(default_factory=dict)


@dataclass
class Mesh:
    positions: list[tuple[float, float, float]]
    normals: list[tuple[float, float, float]]
    uvs: list[tuple[float, float]]
    indices: tuple[int, ...]
    material_id: int
    visible: bool = True
    renderable: bool = True


@dataclass
class Node:
    name: str
    kind: int
    active: bool
    matrix: tuple[tuple[float, ...], ...] | None = None
    mesh: Mesh | None = None
    children: list["Node"] = field(default_factory=list)
    skinned: bool = False


@dataclass
class Model:
    version: int
    textures: dict[str, bytes]
    materials: list[Material]
    root: Node
    warnings: list[str] = field(default_factory=list)


class Reader:
    def __init__(self, stream, size):
        self.stream = stream
        self.size = size

    def read(self, count):
        if count < 0 or count > self.size - self.stream.tell():
            raise KN5Error(f"Truncated KN5 at offset {self.stream.tell()}")
        data = self.stream.read(count)
        if len(data) != count:
            raise KN5Error(f"Truncated KN5 at offset {self.stream.tell()}")
        return data

    def unpack(self, fmt):
        return struct.unpack("<" + fmt, self.read(struct.calcsize("<" + fmt)))

    def count(self, minimum_bytes=1):
        value = self.unpack("i")[0]
        if value < 0 or value > (self.size - self.stream.tell()) // minimum_bytes:
            raise KN5Error(f"Invalid count {value} at offset {self.stream.tell() - 4}")
        return value

    def string(self):
        length = self.count()
        if length > 1_000_000:
            raise KN5Error("Unreasonably long KN5 string")
        return self.read(length).decode("utf-8", errors="replace").rstrip("\0")


def _mesh(reader, skinned, name):
    if skinned:
        bones = reader.count(68)
        for _ in range(bones):
            reader.string()
            reader.read(64)
    vertices = reader.count(76 if skinned else 44)
    positions, normals, uvs = [], [], []
    vertex_format = struct.Struct("<3f3f2f" + ("11f" if skinned else "3f"))
    for _ in range(vertices):
        row = vertex_format.unpack(reader.read(vertex_format.size))
        if not all(math.isfinite(value) for value in (*row[:3], *row[6:8])):
            raise KN5Error(f"Non-finite position or UV in mesh {name!r}")
        positions.append(row[:3])
        normals.append(row[3:6])
        uvs.append((row[6], 1.0 - row[7]))
    index_count = reader.count(2)
    if index_count % 3:
        raise KN5Error("Mesh index count is not divisible by three")
    index_bytes = reader.read(index_count * 2)
    indices = struct.unpack("<" + str(index_count) + "H", index_bytes)
    if indices and max(indices) >= vertices:
        raise KN5Error("Mesh index exceeds vertex count")
    material_id = reader.unpack("i")[0]
    reader.read(12 if skinned else 28)
    renderable = True if skinned else bool(reader.unpack("B")[0])
    return Mesh(positions, normals, uvs, indices, material_id, renderable=renderable)


def _node(reader, depth=0):
    if depth > 256:
        raise KN5Error("KN5 hierarchy exceeds 256 levels")
    kind = reader.unpack("i")[0]
    name = reader.string()
    child_count = reader.count(9)
    active = bool(reader.unpack("B")[0])
    if kind == 1:
        values = reader.unpack("16f")
        if not all(math.isfinite(value) for value in values):
            raise KN5Error(f"Non-finite transform in node {name!r}")
        matrix = tuple(tuple(values[i:i + 4]) for i in range(0, 16, 4))
        node = Node(name, kind, active, matrix=matrix)
    elif kind in (2, 3):
        flags = reader.unpack("3B")
        node = Node(name, kind, active, mesh=_mesh(reader, kind == 3, name), skinned=kind == 3)
        node.mesh.visible = bool(flags[1])
    else:
        raise KN5Error(f"Unsupported KN5 node type {kind} ({name!r})")
    for _ in range(child_count):
        node.children.append(_node(reader, depth + 1))
    return node


def parse(path):
    """Read a KN5 file without creating Blender data or extracting textures."""
    path = Path(path)
    with path.open("rb") as stream:
        reader = Reader(stream, path.stat().st_size)
        magic, version = reader.unpack("6sI")
        if magic != b"sc6969":
            raise KN5Error("Not an Assetto Corsa KN5 file (bad magic)")
        if not 1 <= version <= 6:
            raise KN5Error(f"Unsupported KN5 version {version}")
        if version > 5:
            reader.read(4)
        textures = {}
        for _ in range(reader.count(12)):
            reader.unpack("i")  # texture type
            name = reader.string()
            size = reader.count()
            textures[name] = reader.read(size)
        materials = []
        warnings = []
        for _ in range(reader.count(22 if version > 4 else 18)):
            name, shader = reader.string(), reader.string()
            blend_mode, alpha_test = reader.unpack("2B")
            depth_mode = reader.unpack("i")[0] if version > 4 else 0
            props, vectors = {}, {}
            for _ in range(reader.count(44)):
                prop = reader.string()
                props[prop] = reader.unpack("f")[0]
                values = reader.unpack("9f")
                vectors[prop] = {"float2": values[:2], "float3": values[2:5], "float4": values[5:]}
            slots = {}
            for _ in range(reader.count(12)):
                slot = reader.string()
                reader.unpack("i")  # texture slot index
                slots[slot] = reader.string()
            materials.append(Material(name, shader, blend_mode, props, slots,
                                      bool(alpha_test), depth_mode, vectors))
        root = _node(reader)
        if stream.tell() != reader.size:
            warnings.append(f"{reader.size - stream.tell()} trailing bytes were not interpreted")
        return Model(version, textures, materials, root, warnings)
