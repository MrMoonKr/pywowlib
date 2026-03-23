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
    WDC5_MAGIC = b"WDC5"
    SUPPORTED_MAGICS = {DBC_MAGIC, WDB2_MAGIC, WDB5_MAGIC, WDC5_MAGIC}
    DBC_HEADER_SIZE = 20
    WDB2_HEADER_SIZE = 48
    WDB5_HEADER_SIZE = 80
    WDC5_HEADER_SIZE = 204
    WDC5_SECTION_HEADER_SIZE = 40
    FIELD_STORAGE_INFO_SIZE = 24
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
        if magic == cls.WDB5_MAGIC:
            return cls._parse_wdb5(data, max_rows=max_rows, max_columns=max_columns)
        return cls._parse_wdc5(data, max_rows=max_rows, max_columns=max_columns)

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
    def _parse_wdc5(cls, data: bytes, *, max_rows: int, max_columns: int) -> DBTablePreview | None:
        if len(data) < cls.WDC5_HEADER_SIZE:
            return None

        version_num = struct.unpack_from("<I", data, 4)[0]
        schema_string = data[8:136].split(b"\0", 1)[0].decode("utf-8", errors="replace")
        (
            record_count,
            field_count,
            record_size,
            string_table_size,
            table_hash,
            layout_hash,
            min_id,
            max_id,
            locale,
            flags,
            id_index,
            total_field_count,
            bitpacked_data_offset,
            lookup_column_count,
            field_storage_info_size,
            common_data_size,
            pallet_data_size,
            section_count,
        ) = struct.unpack_from("<9IHH7I", data, 136)

        sections_offset = cls.WDC5_HEADER_SIZE
        section_headers_size = section_count * cls.WDC5_SECTION_HEADER_SIZE
        fields_offset = sections_offset + section_headers_size
        field_structures_size = total_field_count * 4
        field_info_offset = fields_offset + field_structures_size
        pallet_data_offset = field_info_offset + field_storage_info_size
        common_data_offset = pallet_data_offset + pallet_data_size

        if len(data) < common_data_offset + common_data_size:
            return None

        sections = cls._parse_wdc5_sections(data, sections_offset, section_count)
        if not sections:
            return None

        field_infos = cls._parse_wdc5_field_infos(data, field_info_offset, field_storage_info_size)
        if not field_infos:
            return None

        pallet_data = data[pallet_data_offset : pallet_data_offset + pallet_data_size]
        field_palette_offsets = cls._build_additional_data_offsets(field_infos, storage_types={3, 4})
        field_common_offsets = cls._build_additional_data_offsets(field_infos, storage_types={2})

        note_parts: list[str] = []
        if flags & 0x1:
            note_parts.append("Offset-map WDC5 preview is not supported yet.")

        columns = [f"F{index}" for index in range(min(field_count, len(field_infos), max_columns))]
        rows: list[list[str]] = []
        rows_shown = 0
        preview_section_limit = min(section_count, 1 if flags & 0x1 else section_count)

        for section_index in range(preview_section_limit):
            section = sections[section_index]
            if section["file_offset"] >= len(data):
                continue

            if flags & 0x1:
                break

            record_data_offset = section["file_offset"]
            section_records_size = section["record_count"] * record_size
            section_string_offset = record_data_offset + section_records_size
            section_string_block = data[
                section_string_offset : section_string_offset + section["string_table_size"]
            ]

            available_record_bytes = max(0, len(data) - record_data_offset)
            available_rows = min(
                section["record_count"],
                available_record_bytes // record_size,
                max_rows - rows_shown,
            )

            for row_index in range(available_rows):
                row_offset = record_data_offset + (row_index * record_size)
                row_data = data[row_offset : row_offset + record_size]
                rows.append(
                    [
                        cls._format_wdc5_field(
                            row_data,
                            field_index=field_index,
                            field_info=field_infos[field_index],
                            string_block=section_string_block,
                            pallet_data=pallet_data,
                            palette_data_offset=field_palette_offsets[field_index],
                            common_data_offset=field_common_offsets[field_index],
                        )
                        for field_index in range(len(columns))
                    ]
                )
                rows_shown += 1
                if rows_shown >= max_rows:
                    break

            if rows_shown >= max_rows:
                break

        if record_count > rows_shown:
            note_parts.append(f"Showing {rows_shown:,} / {record_count:,} rows from preview data.")
        if field_count > len(columns):
            note_parts.append(f"Showing first {len(columns):,} / {field_count:,} columns.")

        note = " ".join(part for part in note_parts if part) or None
        section_note = (
            f"Sections: {section_count:,}"
            if section_count <= 1
            else f"Sections: {section_count:,} (preview merged across sections)"
        )

        return DBTablePreview(
            magic="WDC5",
            rows_count=record_count,
            fields_count=field_count,
            record_size=record_size,
            string_block_size=string_table_size,
            rows_shown=rows_shown,
            columns=columns,
            rows=rows,
            summary_lines=[
                "Format: WDC5",
                f"Schema: {schema_string or '<unknown>'}",
                f"Version: {version_num}",
                f"Records: {record_count:,}",
                f"Fields: {field_count:,}",
                f"Record Size: {record_size:,}",
                f"String Table Size: {string_table_size:,}",
                f"Min ID: {min_id}",
                f"Max ID: {max_id}",
                f"Locale: 0x{locale:X}",
                f"Flags: 0x{flags:04X}",
                f"ID Index: {id_index}",
                f"Total Field Count: {total_field_count}",
                f"Bitpacked Data Offset: {bitpacked_data_offset:,}",
                f"Lookup Column Count: {lookup_column_count:,}",
                f"Field Storage Info Size: {field_storage_info_size:,}",
                f"Common Data Size: {common_data_size:,}",
                f"Pallet Data Size: {pallet_data_size:,}",
                section_note,
                f"Table Hash: 0x{table_hash:08X}",
                f"Layout Hash: 0x{layout_hash:08X}",
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

    @classmethod
    def _parse_wdc5_sections(cls, data: bytes, offset: int, section_count: int) -> list[dict[str, int]]:
        sections: list[dict[str, int]] = []
        for index in range(section_count):
            section_offset = offset + (index * cls.WDC5_SECTION_HEADER_SIZE)
            if len(data) < section_offset + cls.WDC5_SECTION_HEADER_SIZE:
                return []
            (
                tact_key_hash,
                file_offset,
                record_count,
                string_table_size,
                offset_records_end,
                id_list_size,
                relationship_data_size,
                offset_map_id_count,
                copy_table_count,
            ) = struct.unpack_from("<Q8I", data, section_offset)
            sections.append(
                {
                    "tact_key_hash": tact_key_hash,
                    "file_offset": file_offset,
                    "record_count": record_count,
                    "string_table_size": string_table_size,
                    "offset_records_end": offset_records_end,
                    "id_list_size": id_list_size,
                    "relationship_data_size": relationship_data_size,
                    "offset_map_id_count": offset_map_id_count,
                    "copy_table_count": copy_table_count,
                }
            )
        return sections

    @classmethod
    def _parse_wdc5_field_infos(
        cls, data: bytes, offset: int, field_storage_info_size: int
    ) -> list[dict[str, int]]:
        if field_storage_info_size <= 0:
            return []
        field_count = field_storage_info_size // cls.FIELD_STORAGE_INFO_SIZE
        field_infos: list[dict[str, int]] = []
        for index in range(field_count):
            field_offset = offset + (index * cls.FIELD_STORAGE_INFO_SIZE)
            if len(data) < field_offset + cls.FIELD_STORAGE_INFO_SIZE:
                return []
            (
                field_offset_bits,
                field_size_bits,
                additional_data_size,
                storage_type,
                value1,
                value2,
                value3,
            ) = struct.unpack_from("<HHIIIII", data, field_offset)
            field_infos.append(
                {
                    "field_offset_bits": field_offset_bits,
                    "field_size_bits": field_size_bits,
                    "additional_data_size": additional_data_size,
                    "storage_type": storage_type,
                    "value1": value1,
                    "value2": value2,
                    "value3": value3,
                }
            )
        return field_infos

    @staticmethod
    def _build_additional_data_offsets(
        field_infos: list[dict[str, int]], *, storage_types: set[int]
    ) -> list[int]:
        offsets: list[int] = []
        current_offset = 0
        for field_info in field_infos:
            if field_info["storage_type"] in storage_types:
                offsets.append(current_offset)
                current_offset += field_info["additional_data_size"]
            else:
                offsets.append(0)
        return offsets

    @classmethod
    def _format_wdc5_field(
        cls,
        row_data: bytes,
        *,
        field_index: int,
        field_info: dict[str, int],
        string_block: bytes,
        pallet_data: bytes,
        palette_data_offset: int,
        common_data_offset: int,
    ) -> str:
        start_bit = field_info["field_offset_bits"]
        size_bits = field_info["field_size_bits"]
        storage_type = field_info["storage_type"]
        value = cls._extract_bits(row_data, start_bit=start_bit, size_bits=size_bits)

        if storage_type == 3:
            pallet_value = cls._read_pallet_value(pallet_data, palette_data_offset, value)
            if pallet_value is not None:
                return f"{pallet_value} [idx {value}]"
        elif storage_type == 4:
            return f"idx {value}"
        elif storage_type == 2:
            return f"default@{common_data_offset} raw={value}"
        elif storage_type == 5:
            value = cls._sign_extend(value, size_bits)
            return str(value)

        if start_bit % 8 == 0 and size_bits % 8 == 0:
            start = start_bit // 8
            end = start + (size_bits // 8)
            return cls._format_field(row_data, start=start, end=end, string_block=string_block)

        if storage_type == 1 and field_info["value3"] & 0x1:
            value = cls._sign_extend(value, size_bits)

        if size_bits <= 8:
            return f"0x{value:02X} / {value}"
        if size_bits <= 16:
            return f"0x{value:04X} / {value}"
        if size_bits <= 32:
            signed = cls._sign_extend(value, size_bits)
            return f"0x{value:08X} / {signed}"
        if size_bits <= 64:
            signed = cls._sign_extend(value, size_bits)
            return f"0x{value:016X} / {signed}"
        return f"0x{value:X}"

    @staticmethod
    def _extract_bits(row_data: bytes, *, start_bit: int, size_bits: int) -> int:
        if size_bits <= 0:
            return 0
        start_byte = start_bit // 8
        end_bit = start_bit + size_bits
        end_byte = (end_bit + 7) // 8
        raw = row_data[start_byte:end_byte]
        if not raw:
            return 0
        value = int.from_bytes(raw, "little", signed=False)
        value >>= start_bit % 8
        if size_bits >= value.bit_length() + 1:
            mask = (1 << size_bits) - 1
            return value & mask
        return value & ((1 << size_bits) - 1)

    @staticmethod
    def _read_pallet_value(pallet_data: bytes, field_offset: int, index: int) -> int | None:
        value_offset = field_offset + (index * 4)
        if value_offset < 0 or value_offset + 4 > len(pallet_data):
            return None
        return struct.unpack_from("<I", pallet_data, value_offset)[0]

    @staticmethod
    def _sign_extend(value: int, bits: int) -> int:
        if bits <= 0:
            return 0
        sign_bit = 1 << (bits - 1)
        if value & sign_bit:
            return value - (1 << bits)
        return value

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
