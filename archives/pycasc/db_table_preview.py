from __future__ import annotations

import struct
from dataclasses import dataclass


@dataclass(frozen=True)
class DBTablePreview:
    magic: str
    rows_count: int
    fields_count: int
    record_size: int
    string_block_size: int
    rows_shown: int
    columns: list[str]
    rows: list[list[str]]
    summary_lines: list[str]
    note: str | None = None


class DBTablePreviewParser:
    DBC_MAGIC = b"WDBC"
    WDB2_MAGIC = b"WDB2"
    WDB5_MAGIC = b"WDB5"
    SUPPORTED_MAGICS = {DBC_MAGIC, WDB2_MAGIC, WDB5_MAGIC}
    DBC_HEADER_SIZE = 20
    WDB2_HEADER_SIZE = 48
    WDB5_HEADER_SIZE = 80
    DEFAULT_MAX_ROWS = 128
    DEFAULT_MAX_COLUMNS = 24

    @classmethod
    def parse(
        cls,
        data: bytes,
        *,
        max_rows: int = DEFAULT_MAX_ROWS,
        max_columns: int = DEFAULT_MAX_COLUMNS,
    ) -> DBTablePreview | None:
        if len(data) < 4:
            return None

        magic = data[:4]
        if magic not in cls.SUPPORTED_MAGICS:
            return None

        if magic == cls.DBC_MAGIC:
            return cls._parse_wdbc(data, max_rows=max_rows, max_columns=max_columns)
        if magic == cls.WDB2_MAGIC:
            return cls._parse_wdb2(data, max_rows=max_rows, max_columns=max_columns)
        return cls._parse_wdb5(data, max_rows=max_rows, max_columns=max_columns)

    @classmethod
    def _parse_wdbc(cls, data: bytes, *, max_rows: int, max_columns: int) -> DBTablePreview | None:
        if len(data) < cls.DBC_HEADER_SIZE:
            return None

        record_count, field_count, record_size, string_block_size = struct.unpack_from("<4I", data, 4)
        records_offset = cls.DBC_HEADER_SIZE
        return cls._build_preview(
            magic="WDBC",
            data=data,
            record_count=record_count,
            fields_count=field_count,
            record_size=record_size,
            string_block_size=string_block_size,
            records_offset=records_offset,
            string_block_offset=records_offset + (record_count * record_size),
            field_offsets=[index * 4 for index in range(field_count) if index * 4 < record_size],
            max_rows=max_rows,
            max_columns=max_columns,
            summary_lines=[
                "Format: WDBC",
                f"Records: {record_count:,}",
                f"Fields: {field_count:,}",
                f"Record Size: {record_size:,}",
                f"String Block Size: {string_block_size:,}",
            ],
        )

    @classmethod
    def _parse_wdb2(cls, data: bytes, *, max_rows: int, max_columns: int) -> DBTablePreview | None:
        if len(data) < cls.WDB2_HEADER_SIZE:
            return None

        (
            record_count,
            field_count,
            record_size,
            string_block_size,
            table_hash,
            build,
            timestamp_last_written,
            min_id,
            max_id,
            locale,
            copy_table_size,
        ) = struct.unpack_from("<11I", data, 4)

        index_count = max(0, max_id - min_id + 1) if max_id else 0
        records_offset = cls.WDB2_HEADER_SIZE + (index_count * 4) + (index_count * 2)
        return cls._build_preview(
            magic="WDB2",
            data=data,
            record_count=record_count,
            fields_count=field_count,
            record_size=record_size,
            string_block_size=string_block_size,
            records_offset=records_offset,
            string_block_offset=records_offset + (record_count * record_size),
            field_offsets=[index * 4 for index in range(field_count) if index * 4 < record_size],
            max_rows=max_rows,
            max_columns=max_columns,
            summary_lines=[
                "Format: WDB2",
                f"Records: {record_count:,}",
                f"Fields: {field_count:,}",
                f"Record Size: {record_size:,}",
                f"String Block Size: {string_block_size:,}",
                f"Build: {build}",
                f"Min ID: {min_id}",
                f"Max ID: {max_id}",
                f"Locale: 0x{locale:X}",
                f"Table Hash: 0x{table_hash:08X}",
                f"Timestamp: 0x{timestamp_last_written:08X}",
                f"Copy Table Size: {copy_table_size:,}",
            ],
        )

    @classmethod
    def _parse_wdb5(cls, data: bytes, *, max_rows: int, max_columns: int) -> DBTablePreview | None:
        if len(data) < cls.WDB5_HEADER_SIZE:
            return None

        (
            record_count,
            field_count,
            record_size,
            string_block_size,
            table_hash,
            layout_hash,
            min_id,
            max_id,
            locale,
            copy_table_size,
            flags,
            id_index,
            total_field_count,
            bitpacked_data_offset,
            lookup_column_count,
            field_storage_info_size,
            common_data_size,
            pallet_data_size,
            section_count,
        ) = struct.unpack_from("<19I", data, 4)

        field_offsets = cls._infer_wdb5_field_offsets(data, field_count, record_size)
        records_offset = cls.WDB5_HEADER_SIZE + (field_count * 4)
        note = None
        if not field_offsets:
            note = "Field layout could not be inferred cleanly; falling back to raw 4-byte columns."
            field_offsets = [index * 4 for index in range(field_count) if index * 4 < record_size]

        return cls._build_preview(
            magic="WDB5",
            data=data,
            record_count=record_count,
            fields_count=field_count,
            record_size=record_size,
            string_block_size=string_block_size,
            records_offset=records_offset,
            string_block_offset=records_offset + (record_count * record_size),
            field_offsets=field_offsets,
            max_rows=max_rows,
            max_columns=max_columns,
            summary_lines=[
                "Format: WDB5",
                f"Records: {record_count:,}",
                f"Fields: {field_count:,}",
                f"Record Size: {record_size:,}",
                f"String Block Size: {string_block_size:,}",
                f"Min ID: {min_id}",
                f"Max ID: {max_id}",
                f"Locale: 0x{locale:X}",
                f"Flags: 0x{flags:08X}",
                f"Table Hash: 0x{table_hash:08X}",
                f"Layout Hash: 0x{layout_hash:08X}",
                f"ID Index: {id_index}",
                f"Total Field Count: {total_field_count}",
                f"Bitpacked Data Offset: {bitpacked_data_offset:,}",
                f"Lookup Column Count: {lookup_column_count:,}",
                f"Field Storage Info Size: {field_storage_info_size:,}",
                f"Common Data Size: {common_data_size:,}",
                f"Pallet Data Size: {pallet_data_size:,}",
                f"Copy Table Size: {copy_table_size:,}",
                f"Sections: {section_count:,}",
            ],
            note=note,
        )

    @classmethod
    def _infer_wdb5_field_offsets(cls, data: bytes, field_count: int, record_size: int) -> list[int]:
        block_offset = cls.WDB5_HEADER_SIZE
        block_size = field_count * 4
        if len(data) < block_offset + block_size:
            return []

        first_values: list[int] = []
        second_values: list[int] = []
        for index in range(field_count):
            first, second = struct.unpack_from("<HH", data, block_offset + (index * 4))
            first_values.append(first)
            second_values.append(second)

        first_offsets = cls._validate_offsets(first_values, record_size)
        if first_offsets:
            return first_offsets

        second_offsets = cls._validate_offsets(second_values, record_size)
        if second_offsets:
            return second_offsets

        return []

    @staticmethod
    def _validate_offsets(offsets: list[int], record_size: int) -> list[int]:
        if not offsets:
            return []
        if offsets[0] != 0:
            return []
        if any(offset >= record_size for offset in offsets):
            return []
        if any(offsets[index] > offsets[index + 1] for index in range(len(offsets) - 1)):
            return []
        unique_offsets: list[int] = []
        for offset in offsets:
            if not unique_offsets or unique_offsets[-1] != offset:
                unique_offsets.append(offset)
        return unique_offsets

    @classmethod
    def _build_preview(
        cls,
        *,
        magic: str,
        data: bytes,
        record_count: int,
        fields_count: int,
        record_size: int,
        string_block_size: int,
        records_offset: int,
        string_block_offset: int,
        field_offsets: list[int],
        max_rows: int,
        max_columns: int,
        summary_lines: list[str],
        note: str | None = None,
    ) -> DBTablePreview | None:
        if record_size <= 0 or records_offset < 0:
            return None

        available_record_bytes = max(0, len(data) - records_offset)
        available_rows = min(record_count, available_record_bytes // record_size, max_rows)

        visible_offsets = field_offsets[:max_columns] if field_offsets else []
        columns = [f"F{index}" for index in range(len(visible_offsets))]
        rows: list[list[str]] = []

        for row_index in range(available_rows):
            row_offset = records_offset + (row_index * record_size)
            row_data = data[row_offset : row_offset + record_size]
            rows.append(
                [
                    cls._format_field(
                        row_data,
                        start=offset,
                        end=visible_offsets[index + 1] if index + 1 < len(visible_offsets) else record_size,
                        string_block=data[string_block_offset : string_block_offset + string_block_size],
                    )
                    for index, offset in enumerate(visible_offsets)
                ]
            )

        if record_count > available_rows:
            preview_note = f"Showing {available_rows:,} / {record_count:,} rows from preview data."
            note = f"{note} {preview_note}".strip() if note else preview_note

        if fields_count > len(columns):
            extra_columns_note = f"Showing first {len(columns):,} / {fields_count:,} columns."
            note = f"{note} {extra_columns_note}".strip() if note else extra_columns_note

        return DBTablePreview(
            magic=magic,
            rows_count=record_count,
            fields_count=fields_count,
            record_size=record_size,
            string_block_size=string_block_size,
            rows_shown=available_rows,
            columns=columns,
            rows=rows,
            summary_lines=summary_lines,
            note=note,
        )

    @staticmethod
    def _format_field(row_data: bytes, *, start: int, end: int, string_block: bytes) -> str:
        field_data = row_data[start:end]
        if not field_data:
            return ""

        if len(field_data) == 4:
            value_u32 = int.from_bytes(field_data, "little", signed=False)
            value_i32 = int.from_bytes(field_data, "little", signed=True)
            value_f32 = struct.unpack("<f", field_data)[0]

            if 0 < value_u32 < len(string_block):
                string_value = DBTablePreviewParser._read_c_string(string_block, value_u32)
                if string_value:
                    return f'"{string_value}" @{value_u32}'

            return f"0x{value_u32:08X} / {value_i32} / {value_f32:.3f}"

        if len(field_data) == 2:
            value_u16 = int.from_bytes(field_data, "little", signed=False)
            value_i16 = int.from_bytes(field_data, "little", signed=True)
            return f"0x{value_u16:04X} / {value_i16}"

        if len(field_data) == 1:
            value = field_data[0]
            return f"0x{value:02X} / {value}"

        if len(field_data) == 8:
            value_u64 = int.from_bytes(field_data, "little", signed=False)
            return f"0x{value_u64:016X}"

        return field_data.hex(" ").upper()

    @staticmethod
    def _read_c_string(data: bytes, offset: int) -> str:
        if offset < 0 or offset >= len(data):
            return ""
        end = data.find(b"\0", offset)
        if end == -1:
            end = len(data)
        raw = data[offset:end]
        if not raw:
            return ""
        return raw.decode("utf-8", errors="replace")
