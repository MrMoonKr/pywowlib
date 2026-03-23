from __future__ import annotations

import csv
import io
import os
import queue
import sys
import threading
import traceback
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageTk

from pywowlib.archives.pycasc import CASCHandler, LocaleFlags
from pywowlib.archives.pycasc.db_table_preview import DBTablePreviewParser
from pywowlib.blp import inspect_blp, load_blp_image


APP_TITLE = "pywowlib Asset Explorer"
LISTFILE_PATH = Path(__file__).resolve().parent / "archives" / "listfile.csv"
HEX_PREVIEW_LIMIT = 256 * 1024
TEXT_PREVIEW_LIMIT = 256 * 1024
IMAGE_PREVIEW_SIZE = (640, 640)


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
        self.background_events: queue.Queue[tuple[str, int, object, object | None]] = queue.Queue()
        self.load_request_id = 0
        self.active_load_id: int | None = None
        self.is_loading = False
        self.is_closing = False

        self.wow_path_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Select a WoW directory to begin.")
        self.progress_var = tk.DoubleVar(value=0.0)

        self._build_ui()
        self.after(50, self.process_background_events)

    def _build_ui(self) -> None:
        self.option_add("*Font", ("Consolas", 10))

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
        self.preview_label = ttk.Label(preview_frame, text="No preview", anchor="center")
        self.preview_label.pack(fill="both", expand=True)

        text_frame = ttk.Frame(preview_pane, padding=8)
        preview_pane.add(text_frame, text="Text")
        self.text_preview = self._build_readonly_text(text_frame)

        hex_frame = ttk.Frame(preview_pane, padding=8)
        preview_pane.add(hex_frame, text="Hex")
        self.hex_text = self._build_readonly_text(hex_frame)

        status_bar = ttk.Frame(self, relief="sunken", padding=(8, 4))
        status_bar.pack(fill="x", side="bottom")

        ttk.Label(status_bar, textvariable=self.status_var, anchor="w").pack(side="left", fill="x", expand=True)
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
        info = [
            f"Directory: {directory.full_path or '<root>'}",
            f"Subdirectories: {len(directory.directories):,}",
            f"Files: {len(directory.files):,}",
        ]
        self.set_text(self.info_text, "\n".join(info))
        self.set_text(self.text_preview, "")
        self.set_text(self.hex_text, "")
        self.preview_label.configure(text="Directory selected", image="")
        self.preview_image_ref = None

    def show_file(self, file_entry: AssetFile) -> None:
        if self.handler is None:
            return

        try:
            with self.handler.open_file_by_file_data_id(file_entry.file_data_id) as stream:
                data = stream.read()
            info = self.handler.inspect_entry(file_entry.full_path, file_entry.file_data_id)
        except Exception as exc:
            self.set_text(self.info_text, f"Failed to load file:\n\n{exc}")
            self.set_text(self.text_preview, "")
            self.set_text(self.hex_text, "")
            self.preview_label.configure(text="Failed to load preview", image="")
            self.preview_image_ref = None
            return

        self.set_text(self.info_text, self.format_info(file_entry, info, data))
        self.set_text(self.hex_text, self.format_hex(data))
        self.set_text(self.text_preview, self.format_text_preview(file_entry, data))
        self.update_visual_preview(file_entry, data)
        self.status_var.set(f"Loaded {file_entry.full_path} ({len(data):,} bytes)")

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

        return "\n".join(lines)

    def format_text_preview(self, file_entry: AssetFile, data: bytes) -> str:
        preview = DBTablePreviewParser.parse(data)
        if preview is not None:
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

    def update_visual_preview(self, file_entry: AssetFile, data: bytes) -> None:
        lower_name = file_entry.name.lower()
        try:
            if lower_name.endswith(".blp"):
                image = load_blp_image(data)
            elif lower_name.endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tga")):
                image = Image.open(io.BytesIO(data))
            else:
                self.preview_label.configure(text="No visual preview", image="")
                self.preview_image_ref = None
                return

            image = image.convert("RGBA")
            image.thumbnail(IMAGE_PREVIEW_SIZE, Image.Resampling.LANCZOS)
            self.preview_image_ref = ImageTk.PhotoImage(image)
            self.preview_label.configure(image=self.preview_image_ref, text="")
        except Exception as exc:
            self.preview_label.configure(text=f"Preview unavailable\n\n{exc}", image="")
            self.preview_image_ref = None

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
        self.set_text(self.info_text, "")
        self.set_text(self.text_preview, "")
        self.set_text(self.hex_text, "")
        self.preview_label.configure(text="No preview", image="")
        self.preview_image_ref = None

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
            handler = CASCHandler.open_local_storage(wow_path, progress=self.make_progress_reporter(request_id, 0, 75))
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

    def reset_progress(self) -> None:
        self.progress_var.set(0)
        self.update_idletasks()

    def set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.path_entry.configure(state=state)
        self.browse_button.configure(state=state)
        self.open_button.configure(state=state)
        self.refresh_button.configure(state=state)

    def close_storage(self) -> None:
        if self.handler is not None:
            self.handler.close()
            self.handler = None

    def on_close(self) -> None:
        self.is_closing = True
        self.close_storage()
        self.destroy()

    def set_text(self, widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
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
