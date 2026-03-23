from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


BLP_HEADER = struct.Struct("<4sI4BII16I16I")
PALETTE_SIZE = 256 * 4


@dataclass(frozen=True)
class BlpHeader:
    signature: bytes
    version: int
    compression: int
    alpha_depth: int
    alpha_compression: int
    mip_levels: int
    width: int
    height: int
    offsets: tuple[int, ...]
    sizes: tuple[int, ...]


def _decode_path(value: bytes | str) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else value


def _parse_header(data: bytes) -> BlpHeader:
    if len(data) < BLP_HEADER.size:
        raise ValueError("BLP file is too small to contain a header")

    unpacked = BLP_HEADER.unpack_from(data)
    signature = unpacked[0]
    if signature not in (b"BLP1", b"BLP2"):
        raise ValueError(f"Unsupported BLP signature: {signature!r}")

    return BlpHeader(
        signature=signature,
        version=unpacked[1],
        compression=unpacked[2],
        alpha_depth=unpacked[3],
        alpha_compression=unpacked[4],
        mip_levels=unpacked[5],
        width=unpacked[6],
        height=unpacked[7],
        offsets=tuple(unpacked[8:24]),
        sizes=tuple(unpacked[24:40]),
    )


def _get_first_mip_slice(header: BlpHeader, data: bytes) -> memoryview:
    offset = header.offsets[0]
    size = header.sizes[0]
    if offset <= 0 or size <= 0:
        raise ValueError("BLP file does not contain a valid first mip level")

    end = offset + size
    if end > len(data):
        raise ValueError("BLP mip level points outside the file")

    return memoryview(data)[offset:end]


def _bgra_to_rgba(raw: bytes | memoryview) -> bytes:
    rgba = bytearray(len(raw))
    for src in range(0, len(raw), 4):
        dst = src
        rgba[dst] = raw[src + 2]
        rgba[dst + 1] = raw[src + 1]
        rgba[dst + 2] = raw[src]
        rgba[dst + 3] = raw[src + 3]
    return bytes(rgba)


def _decode_uncompressed(header: BlpHeader, data: bytes) -> bytes:
    mip = _get_first_mip_slice(header, data)
    expected_size = header.width * header.height * 4
    if len(mip) < expected_size:
        raise ValueError("BLP uncompressed mip level is truncated")

    return _bgra_to_rgba(mip[:expected_size])


def _load_palette(data: bytes) -> list[bytes]:
    start = BLP_HEADER.size
    end = start + PALETTE_SIZE
    if len(data) < end:
        raise ValueError("BLP palette is truncated")

    palette_data = data[start:end]
    return [_bgra_to_rgba(palette_data[i : i + 4]) for i in range(0, PALETTE_SIZE, 4)]


def _iter_alpha_values(alpha_depth: int, alpha_data: bytes, pixel_count: int):
    if alpha_depth == 0:
        for _ in range(pixel_count):
            yield 255
        return

    if alpha_depth == 8:
        if len(alpha_data) < pixel_count:
            raise ValueError("BLP alpha plane is truncated")
        yield from alpha_data[:pixel_count]
        return

    if alpha_depth == 1:
        byte_count = (pixel_count + 7) // 8
        if len(alpha_data) < byte_count:
            raise ValueError("BLP alpha plane is truncated")
        produced = 0
        for value in alpha_data[:byte_count]:
            for bit_index in range(8):
                if produced >= pixel_count:
                    return
                yield 255 if (value & (1 << bit_index)) else 0
                produced += 1
        return

    if alpha_depth == 4:
        byte_count = (pixel_count + 1) // 2
        if len(alpha_data) < byte_count:
            raise ValueError("BLP alpha plane is truncated")
        produced = 0
        for value in alpha_data[:byte_count]:
            yield (value & 0x0F) * 17
            produced += 1
            if produced >= pixel_count:
                return
            yield ((value >> 4) & 0x0F) * 17
            produced += 1
        return

    raise NotImplementedError(f"Unsupported BLP alpha depth: {alpha_depth}")


def _decode_paletted(header: BlpHeader, data: bytes) -> bytes:
    palette = _load_palette(data)
    mip = _get_first_mip_slice(header, data)
    pixel_count = header.width * header.height
    if len(mip) < pixel_count:
        raise ValueError("BLP paletted mip level is truncated")

    indices = mip[:pixel_count]
    alpha_data = mip[pixel_count:]

    rgba = bytearray(pixel_count * 4)
    for index, alpha in enumerate(_iter_alpha_values(header.alpha_depth, alpha_data, pixel_count)):
        color = palette[indices[index]]
        dest = index * 4
        rgba[dest] = color[0]
        rgba[dest + 1] = color[1]
        rgba[dest + 2] = color[2]
        rgba[dest + 3] = alpha

    return bytes(rgba)


def load_blp_rgba(data: bytes) -> tuple[int, int, bytes]:
    header = _parse_header(data)

    if header.compression == 1:
        rgba = _decode_paletted(header, data)
    elif header.compression == 3:
        rgba = _decode_uncompressed(header, data)
    elif header.compression == 2:
        raise NotImplementedError("DXT-compressed BLP textures are not implemented yet")
    else:
        raise NotImplementedError(f"Unsupported BLP compression type: {header.compression}")

    return header.width, header.height, rgba


def load_blp_image(data: bytes) -> Image.Image:
    width, height, rgba = load_blp_rgba(data)
    return Image.frombytes("RGBA", (width, height), rgba)


class BlpConverter:
    def convert(self, input_files, output_path):
        base_path = Path(_decode_path(output_path))
        for data, name in input_files:
            relative_path = Path(_decode_path(name))
            out_path = (base_path / relative_path).with_suffix(".png")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            load_blp_image(data).save(out_path)
