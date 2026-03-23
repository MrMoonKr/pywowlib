from __future__ import annotations

import csv
import io
import os
import queue
import struct
import sys
import threading
import traceback
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageTk

if __package__ in (None, ""):
    from pywowlib.archives.pycasc.blte_handler import BLTEDecoderException
    from pywowlib.archives.pycasc import CASCHandler, LocaleFlags
    from pywowlib.archives.pycasc.db_table_preview import DBTablePreview, DBTablePreviewParser
    from pywowlib.blp import inspect_blp, load_blp_image
    from pywowlib.file_formats import m2_chunks
    from pywowlib.file_formats.m2_chunks import MD20, MD21
    from pywowlib.file_formats.skin_format import M2SkinProfile
    from pywowlib.file_formats.wmo_format_group import MOGP
    from pywowlib.file_formats.wmo_format_root import MOHD
    from pywowlib.file_formats.wow_common_types import M2Versions, M2VersionsManager
    from pywowlib.wdbx.definitions import wotlk as wotlk_definitions
else:
    from .archives.pycasc.blte_handler import BLTEDecoderException
    from .archives.pycasc import CASCHandler, LocaleFlags
    from .archives.pycasc.db_table_preview import DBTablePreview, DBTablePreviewParser
    from .blp import inspect_blp, load_blp_image
    from .file_formats import m2_chunks
    from .file_formats.m2_chunks import MD20, MD21
    from .file_formats.skin_format import M2SkinProfile
    from .file_formats.wmo_format_group import MOGP
    from .file_formats.wmo_format_root import MOHD
    from .file_formats.wow_common_types import M2Versions, M2VersionsManager
    from .wdbx.definitions import wotlk as wotlk_definitions


APP_TITLE = "pywowlib Asset Explorer"
LISTFILE_PATH = Path(__file__).resolve().parent / "archives" / "listfile.csv"
HEX_PREVIEW_LIMIT = 256 * 1024
TEXT_PREVIEW_LIMIT = 256 * 1024
IMAGE_PREVIEW_SIZE = (640, 640)
DB_COLUMN_HINTS = {
    "creaturedisplayinfo": list(wotlk_definitions.CreatureDisplayInfo.keys()),
    "creaturedisplayinfoextra": list(wotlk_definitions.CreatureDisplayInfoExtra.keys()),
    "creaturemodeldata": list(wotlk_definitions.CreatureModelData.keys()),
    "itemdisplayinfo": list(wotlk_definitions.ItemDisplayInfo.keys()),
    "chrraces": list(wotlk_definitions.ChrRaces.keys()),
}

ADT_MHDR_OFFSETS = (
    "mcin",
    "mtex",
    "mmdx",
    "mmid",
    "mwmo",
    "mwid",
    "mddf",
    "modf",
    "mfbo",
    "mh2o",
    "mtxf",
)


def decode_null_terminated_strings(data: bytes) -> list[str]:
    return [part.decode("utf-8", errors="replace") for part in data.split(b"\0") if part]


def extract_missing_key_name(exc: Exception) -> str | None:
    if not isinstance(exc, BLTEDecoderException):
        return None
    message = str(exc)
    prefix = "unknown keyname "
    if not message.startswith(prefix):
        return None
    return message[len(prefix) :].strip()


def summarize_sequence(values: list[object], limit: int = 4) -> str:
    if not values:
        return "<none>"
    preview = ", ".join(str(value) for value in values[:limit])
    if len(values) > limit:
        preview += f", ... ({len(values):,} total)"
    return preview


def get_db_table_stem(file_name: str) -> str:
    return Path(file_name).stem.lower()


def apply_db_column_hints(file_name: str, preview: DBTablePreview) -> DBTablePreview:
    column_hints = DB_COLUMN_HINTS.get(get_db_table_stem(file_name))
    if not column_hints:
        return preview

    renamed_columns = [
        column_hints[index] if index < len(column_hints) else preview.columns[index]
        for index in range(len(preview.columns))
    ]
    return replace(preview, columns=renamed_columns)


def derive_skin_paths(file_name: str, skin_profiles: int) -> list[str]:
    if skin_profiles <= 0:
        return []
    base = file_name.rsplit(".", 1)[0]
    return [f"{base}{index:02d}.skin" for index in range(skin_profiles)]


def parse_m2_aux_chunks(stream: io.BytesIO, root) -> dict[str, object]:
    result: dict[str, object] = {}
    while stream.tell() + 8 <= len(stream.getbuffer()):
        magic_bytes = stream.read(4)
        if len(magic_bytes) != 4:
            break

        magic = magic_bytes.decode("ascii", errors="replace")
        chunk_class = getattr(m2_chunks, magic, None)
        if chunk_class is None:
            size = struct.unpack("<I", stream.read(4))[0]
            stream.seek(size, io.SEEK_CUR)
            continue

        if magic == "SFID":
            chunk = chunk_class(n_views=getattr(root, "num_skin_profiles", 0)).read(stream)
            result["sfid"] = chunk
        else:
            chunk = chunk_class().read(stream)
            result[magic.lower()] = chunk
    return result


def parse_m2_summary(file_name: str, data: bytes) -> list[str]:
    if len(data) < 16:
        raise ValueError("M2 file is too small")

    original_version = M2VersionsManager().m2_version
    stream = io.BytesIO(data[4:])
    magic = data[:4]
    aux_chunks: dict[str, object] = {}

    try:
        if magic == b"MD20":
            version = struct.unpack_from("<I", data, 4)[0]
            M2VersionsManager().set_m2_version(version)
            root = MD20().read(stream)
            signature = "MD20"
        elif magic == b"MD21":
            if len(data) < 20:
                raise ValueError("MD21 file is too small")
            version = struct.unpack_from("<I", data, 12)[0]
            M2VersionsManager().set_m2_version(version)
            root = MD21().read(stream)
            aux_chunks = parse_m2_aux_chunks(stream, root)
            signature = "MD21"
        else:
            raise ValueError(f"Unsupported M2 signature: {magic!r}")

        skin_profiles = getattr(root, "num_skin_profiles", len(getattr(root, "skin_profiles", [])))
        inline_texture_paths = [texture.filename.value for texture in root.textures if getattr(texture.filename, "value", "")]
        estimated_skin_paths = derive_skin_paths(file_name, skin_profiles)

        lines = [
            f"M2 Signature: {signature}",
            f"M2 Version: {root.version}",
            f"Model Name: {root.name.value or '<unnamed>'}",
            f"Global Flags: 0x{int(root.global_flags):X}",
            f"Sequences: {len(root.sequences):,}",
            f"Bones: {len(root.bones):,}",
            f"Vertices: {len(root.vertices):,}",
            f"Textures: {len(root.textures):,}",
            f"Texture Paths: {len(inline_texture_paths):,}",
            f"Materials: {len(root.materials):,}",
            f"Skin Profiles: {skin_profiles:,}",
            f"Attachments: {len(root.attachments):,}",
            f"Cameras: {len(root.cameras):,}",
            f"Particle Emitters: {len(root.particle_emitters):,}",
            f"Ribbon Emitters: {len(root.ribbon_emitters):,}",
        ]

        sfid = aux_chunks.get("sfid")
        if sfid is not None:
            lines.append(f"Skin FileDataIDs: {summarize_sequence(sfid.skin_file_data_ids)}")
            lines.append(f"LOD Skin FileDataIDs: {summarize_sequence(sfid.lod_skin_file_data_ids)}")
        elif estimated_skin_paths:
            lines.append(f"Likely Skin Files: {summarize_sequence(estimated_skin_paths)}")

        txid = aux_chunks.get("txid")
        if txid is not None:
            lines.append(f"Texture FileDataIDs: {summarize_sequence(list(txid.texture_ids))}")
        if inline_texture_paths:
            lines.append(f"Texture Refs: {summarize_sequence(inline_texture_paths)}")

        skid = aux_chunks.get("skid")
        if skid is not None:
            lines.append(f"Skeleton FileDataID: {skid.skeleton_file_id}")

        return lines
    finally:
        M2VersionsManager().set_m2_version(original_version)


def parse_skin_summary(data: bytes) -> list[str]:
    last_error = None
    original_version = M2VersionsManager().m2_version

    for version in (M2Versions.CATA, M2Versions.WOTLK):
        try:
            M2VersionsManager().set_m2_version(version)
            skin = M2SkinProfile().read(io.BytesIO(data))
            shadow_batches = len(getattr(skin, "shadow_batches", [])) if hasattr(skin, "shadow_batches") else 0
            max_bone_influences = max((submesh.bone_influences for submesh in skin.submeshes), default=0)
            max_vertices = max((submesh.vertex_count for submesh in skin.submeshes), default=0)
            max_indices = max((submesh.index_count for submesh in skin.submeshes), default=0)
            lines = [
                f"SKIN Magic: {skin.magic}",
                f"Vertex Indices: {len(skin.vertex_indices):,}",
                f"Triangle Indices: {len(skin.triangle_indices):,}",
                f"Triangles: {len(skin.triangle_indices) // 3:,}",
                f"Bone Index Sets: {len(skin.bone_indices):,}",
                f"Submeshes: {len(skin.submeshes):,}",
                f"Texture Units: {len(skin.texture_units):,}",
                f"Bone Count Max: {skin.bone_count_max:,}",
                f"Max Bone Influences: {max_bone_influences:,}",
                f"Largest Submesh Vertices: {max_vertices:,}",
                f"Largest Submesh Indices: {max_indices:,}",
                f"Shadow Batches: {shadow_batches:,}",
            ]
            M2VersionsManager().set_m2_version(original_version)
            return lines
        except Exception as exc:
            last_error = exc
    M2VersionsManager().set_m2_version(original_version)
    raise ValueError(f"Unable to parse SKIN file: {last_error}")


def iter_wmo_chunks(data: bytes):
    stream = io.BytesIO(data)
    data_length = len(data)
    while stream.tell() + 8 <= data_length:
        raw_magic = stream.read(4)
        size_bytes = stream.read(4)
        if len(raw_magic) != 4 or len(size_bytes) != 4:
            break

        size = struct.unpack("<I", size_bytes)[0]
        payload = stream.read(size)
        if len(payload) != size:
            break

        yield raw_magic.decode("ascii", errors="replace")[::-1], size_bytes + payload


def parse_wmo_summary(data: bytes) -> list[str]:
    chunk_map: dict[str, bytes] = {}
    for magic, chunk_data in iter_wmo_chunks(data):
        chunk_map.setdefault(magic, chunk_data)

    if "MOHD" in chunk_map:
        mohd = MOHD().read(io.BytesIO(chunk_map["MOHD"]))
        texture_names = decode_null_terminated_strings(chunk_map.get("MOTX", b"")[4:])
        doodad_names = decode_null_terminated_strings(chunk_map.get("MODN", b"")[4:])
        return [
            "WMO Kind: Root",
            f"Materials: {mohd.n_materials:,}",
            f"Groups: {mohd.n_groups:,}",
            f"Portals: {mohd.n_portals:,}",
            f"Lights: {mohd.n_lights:,}",
            f"Models: {mohd.n_models:,}",
            f"Doodads: {mohd.n_doodads:,}",
            f"Doodad Sets: {mohd.n_sets:,}",
            f"LOD Levels: {mohd.n_lods:,}",
            f"Flags: 0x{int(mohd.flags):X}",
            f"Texture Names: {len(texture_names):,}",
            f"Doodad Paths: {len(doodad_names):,}",
        ]

    if "MOGP" in chunk_map:
        mogp = MOGP().read(io.BytesIO(chunk_map["MOGP"]))
        movt_size = len(chunk_map.get("MOVT", b"")) - 4
        movi_size = len(chunk_map.get("MOVI", b"")) - 4
        moba_size = len(chunk_map.get("MOBA", b"")) - 4
        modr_size = len(chunk_map.get("MODR", b"")) - 4
        molr_size = len(chunk_map.get("MOLR", b"")) - 4
        mobn_size = len(chunk_map.get("MOBN", b"")) - 4
        return [
            "WMO Kind: Group",
            f"Group ID: {mogp.group_id}",
            f"Flags: 0x{int(mogp.flags):X}",
            f"Vertices: {max(0, movt_size) // 12:,}",
            f"Indices: {max(0, movi_size) // 2:,}",
            f"Triangles: {max(0, movi_size) // 6:,}",
            f"Batches: {max(0, moba_size) // 24:,}",
            f"Doodad Refs: {max(0, modr_size) // 2:,}",
            f"Light Refs: {max(0, molr_size) // 2:,}",
            f"BSP Nodes: {max(0, mobn_size) // 16:,}",
            f"Has Liquid: {'MLIQ' in chunk_map}",
            f"Has Vertex Colors: {'MOCV' in chunk_map}",
        ]

    raise ValueError("Unrecognized WMO structure")


def read_adt_chunk_at(data: bytes, offset: int) -> tuple[str, bytes] | None:
    if offset <= 0 or offset + 8 > len(data):
        return None

    magic = data[offset : offset + 4].decode("ascii", errors="replace")
    size = struct.unpack_from("<I", data, offset + 4)[0]
    payload_start = offset + 8
    payload_end = payload_start + size
    if payload_end > len(data):
        return None

    return magic, data[payload_start:payload_end]


def iter_raw_chunks(data: bytes):
    stream = io.BytesIO(data)
    data_length = len(data)
    while stream.tell() + 8 <= data_length:
        magic_bytes = stream.read(4)
        size_bytes = stream.read(4)
        if len(magic_bytes) != 4 or len(size_bytes) != 4:
            break

        size = struct.unpack("<I", size_bytes)[0]
        payload = stream.read(size)
        if len(payload) != size:
            break

        yield magic_bytes.decode("ascii", errors="replace"), payload


def parse_adt_chunked_summary(data: bytes) -> list[str]:
    chunk_map: dict[str, list[bytes]] = {}
    for magic, payload in iter_raw_chunks(data):
        chunk_map.setdefault(magic, []).append(payload)

    version = None
    if "REVM" in chunk_map and chunk_map["REVM"]:
        payload = chunk_map["REVM"][0]
        if len(payload) >= 4:
            version = struct.unpack_from("<I", payload, 0)[0]

    texture_names = decode_null_terminated_strings(chunk_map.get("XTEM", [b""])[0])
    m2_names = decode_null_terminated_strings(chunk_map.get("XDMM", [b""])[0])
    wmo_names = decode_null_terminated_strings(chunk_map.get("OMWM", [b""])[0])
    doodad_instances = sum(len(payload) // 36 for payload in chunk_map.get("FDDM", []))
    wmo_instances = sum(len(payload) // 64 for payload in chunk_map.get("FDOM", []))
    terrain_chunks = len(chunk_map.get("KNCM", []))

    lines = ["ADT Variant: Chunked subfile"]
    if version is not None:
        lines.append(f"ADT Version: {version}")
    lines.extend(
        [
            f"Terrain Chunks: {terrain_chunks:,}",
            f"Textures: {len(texture_names):,}",
            f"M2 Paths: {len(m2_names):,}",
            f"WMO Paths: {len(wmo_names):,}",
            f"Doodad Instances: {doodad_instances:,}",
            f"WMO Instances: {wmo_instances:,}",
            f"Chunk Types: {len(chunk_map):,}",
        ]
    )
    return lines


def parse_adt_summary(data: bytes) -> list[str]:
    try:
        if len(data) < 12 + 8 + 49:
            raise ValueError("ADT file is too small")
        if data[:4].decode("ascii", errors="replace") != "REVM":
            raise ValueError("Invalid ADT header")

        version = struct.unpack_from("<I", data, 8)[0]
        mhdr_offset = 12
        mhdr_magic = data[mhdr_offset : mhdr_offset + 4].decode("ascii", errors="replace")
        if mhdr_magic != "RDHM":
            raise ValueError("Missing MHDR chunk")

        mhdr_data_start = mhdr_offset + 8
        flags = struct.unpack_from("<I", data, mhdr_data_start)[0]
        raw_offsets = struct.unpack_from("<11I", data, mhdr_data_start + 4)
        offsets = dict(zip(ADT_MHDR_OFFSETS, raw_offsets))

        chunk_payloads: dict[str, bytes] = {}
        for key, relative_offset in offsets.items():
            chunk = read_adt_chunk_at(data, mhdr_data_start + relative_offset)
            if chunk is not None:
                chunk_payloads[key] = chunk[1]

        mcin_payload = chunk_payloads.get("mcin", b"")
        active_chunks = 0
        if mcin_payload:
            for index in range(0, min(len(mcin_payload), 16 * 256), 16):
                chunk_offset = struct.unpack_from("<I", mcin_payload, index)[0]
                chunk_size = struct.unpack_from("<I", mcin_payload, index + 4)[0]
                if chunk_offset or chunk_size:
                    active_chunks += 1

        texture_names = decode_null_terminated_strings(chunk_payloads.get("mtex", b""))
        m2_names = decode_null_terminated_strings(chunk_payloads.get("mmdx", b""))
        wmo_names = decode_null_terminated_strings(chunk_payloads.get("mwmo", b""))
        doodad_instances = len(chunk_payloads.get("mddf", b"")) // 36
        wmo_instances = len(chunk_payloads.get("modf", b"")) // 64
        texture_flags = len(chunk_payloads.get("mtxf", b"")) // 4

        return [
            f"ADT Version: {version}",
            f"Header Flags: 0x{int(flags):X}",
            f"Terrain Chunks: {active_chunks:,}/256",
            f"Textures: {len(texture_names):,}",
            f"M2 Paths: {len(m2_names):,}",
            f"WMO Paths: {len(wmo_names):,}",
            f"Doodad Instances: {doodad_instances:,}",
            f"WMO Instances: {wmo_instances:,}",
            f"Texture Flags: {texture_flags:,}",
            f"Has MH2O: {'mh2o' in chunk_payloads}",
        ]
    except Exception:
        return parse_adt_chunked_summary(data)


def get_format_summary_lines(file_name: str, data: bytes) -> list[str]:
    lower_name = file_name.lower()
    if lower_name.endswith(".m2"):
        return parse_m2_summary(file_name, data)
    if lower_name.endswith(".skin"):
        return parse_skin_summary(data)
    if lower_name.endswith(".wmo"):
        return parse_wmo_summary(data)
    if lower_name.endswith(".adt"):
        return parse_adt_summary(data)
    return []


@dataclass(slots=True)
class AssetFile:
    name: str
    full_path: str
    file_data_id: int


@dataclass(slots=True)
class AssetDirectory:
    name: str
    full_path: str
    directories: dict[str, "AssetDirectory"] = field(default_factory=dict)
    files: list[AssetFile] = field(default_factory=list)


class AssetIndex:
    def __init__(self) -> None:
        self.root = AssetDirectory(name="", full_path="")
        self.file_count = 0
        self.directory_count = 0

    @classmethod
    def build(
        cls,
        allowed_file_ids: set[int] | None = None,
        progress: Callable[[int, str], None] | None = None,
    ) -> "AssetIndex":
        index = cls()
        if not LISTFILE_PATH.is_file():
            raise FileNotFoundError(LISTFILE_PATH)

        total_bytes = max(LISTFILE_PATH.stat().st_size, 1)

        if progress is not None:
            progress(0, 'Indexing "listfile.csv"...')

        processed_bytes = 0
        with LISTFILE_PATH.open(encoding="utf-8", newline="") as handle:
            for line_number, line in enumerate(handle, start=1):
                processed_bytes += len(line.encode("utf-8"))
                row = next(csv.reader([line], delimiter=";"), None)
                if not row or len(row) != 2:
                    continue

                try:
                    file_data_id = int(row[0])
                except ValueError:
                    continue

                if allowed_file_ids is not None and file_data_id not in allowed_file_ids:
                    continue

                full_path = row[1].replace("/", "\\").strip("\\")
                if not full_path:
                    continue

                index._add_file(full_path, file_data_id)

                if progress is not None and line_number % 5000 == 0:
                    percent = min(100, int(processed_bytes / total_bytes * 100))
                    progress(percent, 'Indexing "listfile.csv"...')

        index._sort(index.root)
        if progress is not None:
            progress(100, 'Indexing "listfile.csv"...')
        return index

    def _add_file(self, full_path: str, file_data_id: int) -> None:
        parts = [part for part in full_path.split("\\") if part]
        node = self.root
        current_parts: list[str] = []
        for part in parts[:-1]:
            current_parts.append(part)
            next_node = node.directories.get(part)
            if next_node is None:
                next_node = AssetDirectory(name=part, full_path="\\".join(current_parts))
                node.directories[part] = next_node
                self.directory_count += 1
            node = next_node

        node.files.append(AssetFile(name=parts[-1], full_path=full_path, file_data_id=file_data_id))
        self.file_count += 1

    def _sort(self, node: AssetDirectory) -> None:
        node.files.sort(key=lambda item: item.name.lower())
        ordered = sorted(node.directories.items(), key=lambda item: item[0].lower())
        node.directories = dict(ordered)
        for child in node.directories.values():
            self._sort(child)


class WowExplorerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1440x900")
        self.minsize(1100, 720)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.handler: CASCHandler | None = None
        self.asset_index: AssetIndex | None = None
        self.tree_item_to_entry: dict[str, tuple[str, AssetDirectory | AssetFile]] = {}
        self.preview_image_ref: ImageTk.PhotoImage | None = None
        self.missing_db2_key_file_ids: set[int] = set()
        self.background_events: queue.Queue[tuple[str, int, object, object | None]] = queue.Queue()
        self.preview_events: queue.Queue[tuple[str, int, object, object | None]] = queue.Queue()
        self.load_request_id = 0
        self.active_load_id: int | None = None
        self.preview_request_id = 0
        self.active_preview_id: int | None = None
        self.is_loading = False
        self.is_closing = False

        self.wow_path_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Select a WoW directory to begin.")
        self.progress_var = tk.DoubleVar(value=0.0)

        self._build_ui()
        self.after(50, self.process_background_events)

    def _build_ui(self) -> None:
        self.option_add("*Font", ("Consolas", 10))
        self.style = ttk.Style(self)
        self.style.configure("Explorer.Status.TLabel", foreground="")
        self.style.configure("Explorer.StatusError.TLabel", foreground="#B00020")
        self.style.configure("Explorer.Preview.TLabel", foreground="")
        self.style.configure("Explorer.PreviewError.TLabel", foreground="#B00020")

        toolbar = ttk.Frame(self, padding=(10, 10, 10, 6))
        toolbar.pack(fill="x")

        ttk.Label(toolbar, text="WoW Path").pack(side="left")
        self.path_entry = ttk.Entry(toolbar, textvariable=self.wow_path_var)
        self.path_entry.pack(side="left", fill="x", expand=True, padx=(8, 8))
        self.path_entry.bind("<Return>", lambda _event: self.open_storage())

        self.browse_button = ttk.Button(toolbar, text="Browse", command=self.browse_storage)
        self.browse_button.pack(side="left")
        self.open_button = ttk.Button(toolbar, text="Open", command=self.open_storage)
        self.open_button.pack(side="left", padx=(8, 0))
        self.refresh_button = ttk.Button(toolbar, text="Refresh", command=self.refresh_storage)
        self.refresh_button.pack(side="left", padx=(8, 0))

        main_pane = ttk.Panedwindow(self, orient="horizontal")
        main_pane.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        left_frame = ttk.Frame(main_pane, padding=(0, 0, 8, 0))
        main_pane.add(left_frame, weight=3)
        right_frame = ttk.Frame(main_pane)
        main_pane.add(right_frame, weight=4)

        self.tree = ttk.Treeview(left_frame, columns=("kind", "file_id"), displaycolumns=("kind", "file_id"))
        self.tree.heading("#0", text="Asset")
        self.tree.heading("kind", text="Kind")
        self.tree.heading("file_id", text="FileDataID")
        self.tree.column("#0", width=420, anchor="w")
        self.tree.column("kind", width=90, anchor="center")
        self.tree.column("file_id", width=120, anchor="e")
        self.tree.tag_configure("missing_db2_key", foreground="#B00020")
        self.tree.pack(side="left", fill="both", expand=True)

        tree_scroll = ttk.Scrollbar(left_frame, orient="vertical", command=self.tree.yview)
        tree_scroll.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=tree_scroll.set)

        self.tree.bind("<<TreeviewOpen>>", self.on_tree_open)
        self.tree.bind("<<TreeviewSelect>>", self.on_tree_select)
        self.tree.bind("<Button-3>", self.on_tree_context_menu)

        self.tree_menu = tk.Menu(self, tearoff=False)
        self.tree_menu.add_command(label="Extract", command=self.extract_selected)
        self.tree_menu.add_command(label="Extract as PNG", command=self.extract_selected_as_png)
        self.tree_menu.add_separator()
        self.tree_menu.add_command(label="Copy Asset Path", command=self.copy_selected_path)

        preview_pane = ttk.Notebook(right_frame)
        preview_pane.pack(fill="both", expand=True)

        info_frame = ttk.Frame(preview_pane, padding=8)
        preview_pane.add(info_frame, text="Info")
        self.info_text = self._build_readonly_text(info_frame)

        preview_frame = ttk.Frame(preview_pane, padding=8)
        preview_pane.add(preview_frame, text="Preview")
        self.preview_container = ttk.Frame(preview_frame)
        self.preview_container.pack(fill="both", expand=True)

        self.preview_image_frame = ttk.Frame(self.preview_container)
        self.preview_label = ttk.Label(
            self.preview_image_frame,
            text="No preview",
            anchor="center",
            style="Explorer.Preview.TLabel",
        )
        self.preview_label.pack(fill="both", expand=True)

        self.preview_table_frame = ttk.Frame(self.preview_container)
        self.preview_table_info_var = tk.StringVar(value="")
        ttk.Label(
            self.preview_table_frame,
            textvariable=self.preview_table_info_var,
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(0, 6))

        preview_table_grid = ttk.Frame(self.preview_table_frame)
        preview_table_grid.pack(fill="both", expand=True)
        self.preview_table = ttk.Treeview(preview_table_grid, show="headings")
        self.preview_table.pack(side="left", fill="both", expand=True)

        preview_table_y = ttk.Scrollbar(preview_table_grid, orient="vertical", command=self.preview_table.yview)
        preview_table_y.pack(side="right", fill="y")
        self.preview_table.configure(yscrollcommand=preview_table_y.set)

        preview_table_x = ttk.Scrollbar(self.preview_table_frame, orient="horizontal", command=self.preview_table.xview)
        preview_table_x.pack(fill="x")
        self.preview_table.configure(xscrollcommand=preview_table_x.set)

        self.show_preview_message("No preview")

        text_frame = ttk.Frame(preview_pane, padding=8)
        preview_pane.add(text_frame, text="Text")
        self.text_preview = self._build_readonly_text(text_frame)

        hex_frame = ttk.Frame(preview_pane, padding=8)
        preview_pane.add(hex_frame, text="Hex")
        self.hex_text = self._build_readonly_text(hex_frame)

        status_bar = ttk.Frame(self, relief="sunken", padding=(8, 4))
        status_bar.pack(fill="x", side="bottom")

        self.status_label = ttk.Label(
            status_bar,
            textvariable=self.status_var,
            anchor="w",
            style="Explorer.Status.TLabel",
        )
        self.status_label.pack(side="left", fill="x", expand=True)
        self.progress_bar = ttk.Progressbar(
            status_bar,
            orient="horizontal",
            mode="determinate",
            maximum=100,
            variable=self.progress_var,
            length=260,
        )
        self.progress_bar.pack(side="right", padx=(8, 0))

    def _build_readonly_text(self, parent: ttk.Frame) -> tk.Text:
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        widget = tk.Text(frame, wrap="none", font=("Consolas", 10))
        widget.pack(side="left", fill="both", expand=True)
        widget.configure(state="disabled")

        y_scroll = ttk.Scrollbar(frame, orient="vertical", command=widget.yview)
        y_scroll.pack(side="right", fill="y")
        widget.configure(yscrollcommand=y_scroll.set)

        x_scroll = ttk.Scrollbar(parent, orient="horizontal", command=widget.xview)
        x_scroll.pack(fill="x")
        widget.configure(xscrollcommand=x_scroll.set)
        return widget

    def browse_storage(self) -> None:
        if self.is_loading:
            return
        selected = filedialog.askdirectory(title="Select World of Warcraft directory")
        if selected:
            self.wow_path_var.set(selected)
            self.open_storage()

    def refresh_storage(self) -> None:
        if not self.wow_path_var.get().strip():
            return
        self.open_storage()

    def open_storage(self) -> None:
        if self.is_loading:
            return

        wow_path = self.wow_path_var.get().strip()
        if not wow_path:
            messagebox.showerror(APP_TITLE, "Select a World of Warcraft directory first.")
            return

        self.start_storage_load(wow_path)

    def populate_tree(self) -> None:
        self.tree.delete(*self.tree.get_children(""))
        self.tree_item_to_entry.clear()
        self.clear_preview()

        if self.asset_index is None:
            return

        self._populate_directory("", self.asset_index.root)

    def _populate_directory(self, parent_item: str, directory: AssetDirectory) -> None:
        for child in directory.directories.values():
            item_id = self.tree.insert(parent_item, "end", text=child.name or "root", values=("dir", ""))
            self.tree_item_to_entry[item_id] = ("dir", child)
            if child.directories or child.files:
                self.tree.insert(item_id, "end", text="__loading__")

        for file_entry in directory.files:
            item_id = self.tree.insert(
                parent_item,
                "end",
                text=file_entry.name,
                values=("file", file_entry.file_data_id),
                tags=self.get_tree_tags(file_entry),
            )
            self.tree_item_to_entry[item_id] = ("file", file_entry)

    def on_tree_open(self, _event=None) -> None:
        item_id = self.tree.focus()
        entry = self.tree_item_to_entry.get(item_id)
        if not entry or entry[0] != "dir":
            return

        placeholder = self.tree.get_children(item_id)
        if len(placeholder) == 1 and self.tree.item(placeholder[0], "text") == "__loading__":
            self.tree.delete(placeholder[0])
            self._populate_directory(item_id, entry[1])

    def on_tree_select(self, _event=None) -> None:
        if self.is_loading:
            return
        item_id = self.get_selected_item()
        if not item_id:
            return

        kind, entry = self.tree_item_to_entry.get(item_id, (None, None))
        if kind == "dir":
            self.show_directory_info(entry)
        elif kind == "file":
            self.show_file(entry)

    def on_tree_context_menu(self, event) -> None:
        if self.is_loading:
            return
        item_id = self.tree.identify_row(event.y)
        if not item_id:
            return

        self.tree.selection_set(item_id)
        self.tree.focus(item_id)

        kind, entry = self.tree_item_to_entry.get(item_id, (None, None))
        if kind == "file" and entry.name.lower().endswith(".blp"):
            self.tree_menu.entryconfigure("Extract as PNG", state="normal")
        else:
            self.tree_menu.entryconfigure("Extract as PNG", state="disabled")

        try:
            self.tree_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.tree_menu.grab_release()

    def get_selected_item(self) -> str | None:
        selection = self.tree.selection()
        return selection[0] if selection else None

    def show_directory_info(self, directory: AssetDirectory) -> None:
        self.active_preview_id = None
        info = [
            f"Directory: {directory.full_path or '<root>'}",
            f"Subdirectories: {len(directory.directories):,}",
            f"Files: {len(directory.files):,}",
        ]
        self.set_text(self.info_text, "\n".join(info))
        self.set_text(self.text_preview, "")
        self.set_text(self.hex_text, "")
        self.set_status_style(False)
        self.show_preview_message("Directory selected")

    def show_file(self, file_entry: AssetFile) -> None:
        if self.handler is None:
            return

        self.preview_request_id += 1
        request_id = self.preview_request_id
        self.active_preview_id = request_id

        self.set_text(self.info_text, f"Loading {file_entry.full_path}...")
        self.set_text(self.text_preview, "")
        self.set_text(self.hex_text, "")
        self.set_status_style(False)
        self.show_preview_message("Loading preview...")
        self.status_var.set(f"Loading {file_entry.full_path}...")

        worker = threading.Thread(
            target=self._load_file_worker,
            args=(request_id, self.handler, file_entry),
            name=f"wow-file-preview-{request_id}",
            daemon=True,
        )
        worker.start()

    def _load_file_worker(self, request_id: int, handler: CASCHandler, file_entry: AssetFile) -> None:
        try:
            with handler.open_file_by_file_data_id(file_entry.file_data_id) as stream:
                data = stream.read()
            info = handler.inspect_entry(file_entry.full_path, file_entry.file_data_id)
            formatted_info = self.format_info(file_entry, info, data)
            formatted_hex = self.format_hex(data)
            formatted_text = self.format_text_preview(file_entry, data)
            preview_content = self.build_preview_content(file_entry, data)
            payload = (
                file_entry,
                formatted_info,
                formatted_hex,
                formatted_text,
                preview_content,
                len(data),
            )
            self.preview_events.put(("file_loaded", request_id, payload, None))
        except Exception as exc:
            self.preview_events.put(("file_error", request_id, file_entry, exc))

    def format_info(self, file_entry: AssetFile, info: dict, data: bytes) -> str:
        lines = [
            f"Path: {file_entry.full_path}",
            f"FileDataID: {file_entry.file_data_id}",
            f"Size: {len(data):,} bytes",
        ]

        selected_source = info.get("selected_source")
        if selected_source:
            lines.append(f"Source: {selected_source}")

        storage = info.get("storage")
        if isinstance(storage, dict):
            lines.append(f"Storage: {storage.get('storage')}")
            lines.append(f"Download Required: {storage.get('download_required')}")

        encoding = info.get("encoding")
        if encoding:
            lines.append(f"Encoding Key: {encoding.get('key')}")
            lines.append(f"Encoding Size: {encoding.get('size')}")

        root_entries = info.get("root_entries") or []
        if root_entries:
            lines.append(f"Root Entries: {len(root_entries)}")

        if file_entry.name.lower().endswith(".blp"):
            try:
                blp_info = inspect_blp(data)
            except Exception as exc:
                lines.append(f"BLP Info: unavailable ({exc})")
            else:
                lines.append(f"BLP Signature: {blp_info.signature}")
                lines.append(f"BLP Version: {blp_info.version}")
                lines.append(f"Texture Size: {blp_info.width}x{blp_info.height}")
                lines.append(f"Mip Levels: {blp_info.mip_levels}")
                lines.append(
                    f"Compression: {blp_info.compression_name} (type {blp_info.compression})"
                )
                lines.append(
                    f"Alpha: {blp_info.alpha_depth}-bit, {blp_info.alpha_compression_name} "
                    f"(mode {blp_info.alpha_compression})"
                )

        try:
            summary_lines = get_format_summary_lines(file_entry.name, data)
        except Exception as exc:
            lower_name = file_entry.name.lower()
            if lower_name.endswith((".m2", ".wmo", ".adt")):
                lines.append(f"Format Summary: unavailable ({exc})")
        else:
            if summary_lines:
                lines.append("")
                lines.extend(summary_lines)

        return "\n".join(lines)

    def format_text_preview(self, file_entry: AssetFile, data: bytes) -> str:
        preview = DBTablePreviewParser.parse(data)
        if preview is not None:
            preview = apply_db_column_hints(file_entry.name, preview)
            lines = list(preview.summary_lines)
            if preview.note:
                lines.append(preview.note)
            lines.append("")
            if preview.columns:
                lines.append("\t".join(preview.columns))
            for row in preview.rows:
                lines.append("\t".join(row))
            return "\n".join(lines)

        text_data = data[:TEXT_PREVIEW_LIMIT]
        if self.looks_like_text(text_data, file_entry.name):
            suffix = "\n\n[truncated]" if len(data) > TEXT_PREVIEW_LIMIT else ""
            return text_data.decode("utf-8", errors="replace") + suffix

        return "Binary file."

    def build_preview_content(self, file_entry: AssetFile, data: bytes) -> tuple[str, object]:
        lower_name = file_entry.name.lower()
        db_preview = DBTablePreviewParser.parse(data)
        if db_preview is not None:
            db_preview = apply_db_column_hints(file_entry.name, db_preview)
            return ("table", db_preview)

        try:
            if lower_name.endswith(".blp"):
                image = load_blp_image(data)
            elif lower_name.endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tga")):
                image = Image.open(io.BytesIO(data))
            else:
                return ("message", "No visual preview")

            image = image.convert("RGBA")
            image.thumbnail(IMAGE_PREVIEW_SIZE, Image.Resampling.LANCZOS)
            return ("image", image)
        except Exception as exc:
            return ("message", f"Preview unavailable\n\n{exc}")

    def apply_preview_content(self, preview_content: tuple[str, object]) -> None:
        kind, payload = preview_content
        if kind == "table":
            self.show_preview_table(payload)
            return
        if kind == "image":
            self.preview_image_ref = ImageTk.PhotoImage(payload)
            self.preview_table_frame.pack_forget()
            self.preview_image_frame.pack(fill="both", expand=True)
            self.preview_label.configure(image=self.preview_image_ref, text="")
            return
        self.show_preview_message(str(payload))

    def extract_selected(self) -> None:
        if self.is_loading:
            return
        item_id = self.get_selected_item()
        if not item_id or self.handler is None:
            return

        output_dir = filedialog.askdirectory(title="Extract to directory")
        if not output_dir:
            return

        kind, entry = self.tree_item_to_entry.get(item_id, (None, None))
        try:
            if kind == "file":
                self.extract_file(entry, Path(output_dir))
            elif kind == "dir":
                self.extract_directory(entry, Path(output_dir))
            else:
                return
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"Extraction failed:\n\n{exc}")
            return

        self.status_var.set(f"Extracted to {output_dir}")

    def extract_selected_as_png(self) -> None:
        if self.is_loading:
            return
        item_id = self.get_selected_item()
        if not item_id or self.handler is None:
            return

        kind, entry = self.tree_item_to_entry.get(item_id, (None, None))
        if kind != "file" or not entry.name.lower().endswith(".blp"):
            return

        output_path = filedialog.asksaveasfilename(
            title="Extract texture as PNG",
            defaultextension=".png",
            initialfile=Path(entry.name).with_suffix(".png").name,
            filetypes=[("PNG image", "*.png")],
        )
        if not output_path:
            return

        try:
            with self.handler.open_file_by_file_data_id(entry.file_data_id) as stream:
                image = load_blp_image(stream.read())
            image.save(output_path)
        except Exception as exc:
            messagebox.showerror(APP_TITLE, f"PNG extraction failed:\n\n{exc}")
            return

        self.status_var.set(f"Saved {output_path}")

    def extract_file(self, file_entry: AssetFile, output_dir: Path) -> None:
        assert self.handler is not None
        with self.handler.open_file_by_file_data_id(file_entry.file_data_id) as stream:
            data = stream.read()

        target = output_dir / Path(file_entry.full_path.replace("\\", os.sep))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def extract_directory(self, directory: AssetDirectory, output_dir: Path) -> None:
        for file_entry in self.iter_directory_files(directory):
            self.extract_file(file_entry, output_dir)

    def iter_directory_files(self, directory: AssetDirectory):
        for file_entry in directory.files:
            yield file_entry
        for child in directory.directories.values():
            yield from self.iter_directory_files(child)

    def copy_selected_path(self) -> None:
        item_id = self.get_selected_item()
        if not item_id:
            return

        kind, entry = self.tree_item_to_entry.get(item_id, (None, None))
        if kind == "file":
            value = entry.full_path
        elif kind == "dir":
            value = entry.full_path or "<root>"
        else:
            return

        self.clipboard_clear()
        self.clipboard_append(value)
        self.status_var.set(f"Copied path: {value}")

    def clear_preview(self) -> None:
        self.active_preview_id = None
        self.set_text(self.info_text, "")
        self.set_text(self.text_preview, "")
        self.set_text(self.hex_text, "")
        self.set_status_style(False)
        self.show_preview_message("No preview")

    def show_preview_message(self, message: str) -> None:
        self.show_preview_message_with_style(message, is_error=False)

    def show_preview_error(self, message: str) -> None:
        self.show_preview_message_with_style(message, is_error=True)

    def show_preview_message_with_style(self, message: str, *, is_error: bool) -> None:
        self.preview_table_frame.pack_forget()
        self.preview_image_frame.pack(fill="both", expand=True)
        self.preview_image_ref = None
        self.preview_table_info_var.set("")
        self.preview_label.configure(
            style="Explorer.PreviewError.TLabel" if is_error else "Explorer.Preview.TLabel"
        )
        self.preview_label.configure(text=message, image="")

    def show_preview_table(self, preview: DBTablePreview) -> None:
        columns = preview.columns or ["Value"]
        self.preview_image_frame.pack_forget()
        self.preview_table_frame.pack(fill="both", expand=True)

        self.preview_table.delete(*self.preview_table.get_children(""))
        self.preview_table.configure(columns=columns, displaycolumns=columns)

        for column in columns:
            self.preview_table.heading(column, text=column)
            self.preview_table.column(column, width=140, minwidth=80, stretch=True, anchor="w")

        for row in preview.rows:
            values = list(row[: len(columns)])
            if len(values) < len(columns):
                values.extend("" for _ in range(len(columns) - len(values)))
            self.preview_table.insert("", "end", values=values)

        info_lines = list(preview.summary_lines[:4])
        if preview.note:
            info_lines.append(preview.note)
        self.preview_table_info_var.set(" | ".join(info_lines))

    def start_storage_load(self, wow_path: str) -> None:
        self.load_request_id += 1
        request_id = self.load_request_id
        self.active_load_id = request_id
        self.is_loading = True
        self.set_controls_enabled(False)
        self.tree.delete(*self.tree.get_children(""))
        self.tree_item_to_entry.clear()
        self.clear_preview()
        self.set_loading_progress(0, "Opening CASC storage...")

        worker = threading.Thread(
            target=self._open_storage_worker,
            args=(request_id, wow_path),
            name=f"wow-storage-loader-{request_id}",
            daemon=True,
        )
        worker.start()

    def _open_storage_worker(self, request_id: int, wow_path: str) -> None:
        handler = None
        try:
            handler = CASCHandler.open_local_storage(wow_path, progress=self.make_storage_progress_reporter(request_id))
            handler.set_flags(LocaleFlags.All)
            asset_index = AssetIndex.build(
                handler.root.get_file_data_ids(),
                progress=self.make_progress_reporter(request_id, 75, 100),
            )
            self.background_events.put(("loaded", request_id, (wow_path, handler, asset_index), None))
        except Exception as exc:
            if handler is not None:
                handler.close()
            self.background_events.put(("error", request_id, exc, traceback.format_exc()))

    def process_background_events(self) -> None:
        if self.is_closing:
            return

        while True:
            try:
                event_type, request_id, payload, extra = self.background_events.get_nowait()
            except queue.Empty:
                break

            if request_id != self.active_load_id:
                if event_type == "loaded":
                    _, stale_handler, _ = payload
                    stale_handler.close()
                continue

            if event_type == "progress":
                percent = int(payload)
                message = str(extra)
                self.set_loading_progress(percent, message)
                continue

            self.is_loading = False
            self.active_load_id = None
            self.set_controls_enabled(True)

            if event_type == "loaded":
                wow_path, handler, asset_index = payload
                self.close_storage()
                self.handler = handler
                self.asset_index = asset_index
                self.populate_tree()
                self.reset_progress()
                self.status_var.set(
                    f"Opened {wow_path} | {asset_index.file_count:,} files | {asset_index.directory_count:,} directories"
                )
            elif event_type == "error":
                self.reset_progress()
                messagebox.showerror(APP_TITLE, f"Failed to open storage:\n\n{payload}")
                self.status_var.set("Failed to open storage.")

        while True:
            try:
                event_type, request_id, payload, extra = self.preview_events.get_nowait()
            except queue.Empty:
                break

            if request_id != self.active_preview_id:
                continue

            self.active_preview_id = None
            if event_type == "file_loaded":
                file_entry, formatted_info, formatted_hex, formatted_text, preview_content, data_size = payload
                self.clear_tree_missing_key(file_entry)
                self.set_text(self.info_text, formatted_info)
                self.set_text(self.hex_text, formatted_hex)
                self.set_text(self.text_preview, formatted_text)
                self.set_status_style(False)
                self.apply_preview_content(preview_content)
                self.status_var.set(f"Loaded {file_entry.full_path} ({data_size:,} bytes)")
            elif event_type == "file_error":
                file_entry = payload
                exc = extra
                missing_key = extract_missing_key_name(exc)
                if missing_key is not None:
                    self.mark_tree_missing_key(file_entry)
                    self.set_text(
                        self.info_text,
                        f"Missing decryption key for this file.\n\nKey Name: {missing_key}",
                        foreground="#B00020",
                    )
                    self.show_preview_error(f"Missing decryption key\n\n{missing_key}")
                    self.status_var.set(f"Missing decryption key: {missing_key}")
                    self.set_status_style(True)
                else:
                    self.set_text(self.info_text, f"Failed to load file:\n\n{exc}")
                    self.show_preview_message("Failed to load preview")
                    self.status_var.set("Failed to load preview.")
                    self.set_status_style(False)
                self.set_text(self.text_preview, "")
                self.set_text(self.hex_text, "")

        self.after(50, self.process_background_events)

    def set_loading_progress(self, percent: int, message: str) -> None:
        self.progress_var.set(max(0, min(100, percent)))
        self.status_var.set(message)
        self.update_idletasks()

    def make_progress_reporter(self, request_id: int, start: int, end: int) -> Callable[[int, str], None]:
        span = max(0, end - start)
        last_state: list[tuple[int, str] | None] = [None]

        def report(percent: int, message: str) -> None:
            bounded = max(0, min(100, percent))
            scaled = start + int(span * (bounded / 100))
            state = (scaled, message)
            if last_state[0] == state:
                return
            last_state[0] = state
            self.background_events.put(("progress", request_id, scaled, message))

        return report

    def make_storage_progress_reporter(self, request_id: int) -> Callable[[int, str], None]:
        phase_ranges = {
            'Loading "local indexes"...': (0, 25),
            'Loading "encoding"...': (25, 50),
            'Loading "root"...': (50, 75),
            'Loading "CDN indexes"...': (50, 75),
        }
        fallback = self.make_progress_reporter(request_id, 0, 75)
        phase_state: dict[str, Callable[[int, str], None]] = {}

        def report(percent: int, message: str) -> None:
            phase = phase_ranges.get(message)
            if phase is None:
                fallback(percent, message)
                return

            phase_reporter = phase_state.get(message)
            if phase_reporter is None:
                phase_reporter = self.make_progress_reporter(request_id, phase[0], phase[1])
                phase_state[message] = phase_reporter
            phase_reporter(percent, message)

        return report

    def reset_progress(self) -> None:
        self.progress_var.set(0)
        self.update_idletasks()

    def set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.path_entry.configure(state=state)
        self.browse_button.configure(state=state)
        self.open_button.configure(state=state)
        self.refresh_button.configure(state=state)

    def set_status_style(self, is_error: bool) -> None:
        self.status_label.configure(
            style="Explorer.StatusError.TLabel" if is_error else "Explorer.Status.TLabel"
        )

    def get_tree_tags(self, file_entry: AssetFile) -> tuple[str, ...]:
        if file_entry.name.lower().endswith(".db2") and file_entry.file_data_id in self.missing_db2_key_file_ids:
            return ("missing_db2_key",)
        return ()

    def mark_tree_missing_key(self, file_entry: AssetFile) -> None:
        if not file_entry.name.lower().endswith(".db2"):
            return
        self.missing_db2_key_file_ids.add(file_entry.file_data_id)
        for item_id, entry in self.tree_item_to_entry.items():
            if entry[0] == "file" and entry[1].file_data_id == file_entry.file_data_id:
                self.tree.item(item_id, tags=("missing_db2_key",))

    def clear_tree_missing_key(self, file_entry: AssetFile) -> None:
        if file_entry.file_data_id not in self.missing_db2_key_file_ids:
            return
        self.missing_db2_key_file_ids.discard(file_entry.file_data_id)
        for item_id, entry in self.tree_item_to_entry.items():
            if entry[0] == "file" and entry[1].file_data_id == file_entry.file_data_id:
                self.tree.item(item_id, tags=())

    def close_storage(self) -> None:
        if self.handler is not None:
            close = getattr(self.handler, "close", None)
            if callable(close):
                close()
            self.handler = None

    def on_close(self) -> None:
        self.is_closing = True
        self.active_preview_id = None
        self.close_storage()
        self.destroy()

    def set_text(self, widget: tk.Text, value: str, foreground: str | None = None) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.tag_delete("content")
        widget.tag_configure("content", foreground=foreground or "black")
        widget.insert("1.0", value, ("content",))
        widget.configure(state="disabled")

    def looks_like_text(self, data: bytes, file_name: str) -> bool:
        lower_name = file_name.lower()
        if lower_name.endswith((".txt", ".xml", ".lua", ".json", ".csv", ".ini", ".log", ".toc")):
            return True
        if b"\x00" in data[:1024]:
            return False
        if not data:
            return True
        printable = sum(32 <= byte <= 126 or byte in (9, 10, 13) for byte in data[:4096])
        return printable / max(1, min(len(data), 4096)) > 0.85

    def format_hex(self, data: bytes) -> str:
        preview = data[:HEX_PREVIEW_LIMIT]
        lines: list[str] = []
        for offset in range(0, len(preview), 16):
            chunk = preview[offset : offset + 16]
            hex_part = " ".join(f"{byte:02X}" for byte in chunk)
            hex_part = f"{hex_part:<47}"
            ascii_part = "".join(chr(byte) if 32 <= byte <= 126 else "." for byte in chunk)
            lines.append(f"{offset:08X}  {hex_part}  {ascii_part}")
        if len(data) > HEX_PREVIEW_LIMIT:
            lines.append("")
            lines.append(f"[truncated: showing first {HEX_PREVIEW_LIMIT:,} bytes of {len(data):,}]")
        return "\n".join(lines)


def main() -> int:
    try:
        app = WowExplorerApp()
        app.mainloop()
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
