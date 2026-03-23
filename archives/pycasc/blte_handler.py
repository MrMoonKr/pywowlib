from __future__ import annotations

import io
import hashlib
import zlib

from .binary import BinaryReader
from .key_service import KeyService
from .types import MD5Hash, ensure_md5, is_zeroed_md5


class BLTEDecoderException(Exception):
    pass


class BLTEHandler:
    ENCRYPTION_SALSA20 = 0x53
    ENCRYPTION_ARC4 = 0x41
    BLTE_MAGIC = 0x45544C42

    def __init__(self, stream, md5: MD5Hash, validate_data: bool = True, max_output_size: int | None = None) -> None:
        self.reader = BinaryReader(stream)
        self.validate_data = validate_data
        self.max_output_size = max_output_size
        self.buffer = io.BytesIO()
        self._parse(ensure_md5(md5))

    def open_file(self) -> io.BytesIO:
        self.buffer.seek(0)
        return io.BytesIO(self.buffer.getvalue())

    def _parse(self, md5: MD5Hash) -> None:
        size = self.reader.length()
        if size < 8:
            raise BLTEDecoderException("not enough data: 8")

        magic = self.reader.read_int32()
        if magic != self.BLTE_MAGIC:
            raise BLTEDecoderException("frame header mismatch (bad BLTE file)")

        header_size = self.reader.read_uint32_be()
        if self.validate_data:
            old_pos = self.reader.tell()
            self.reader.seek(0)
            hash_data = self.reader.read_bytes(header_size if header_size > 0 else size)
            if hashlib.md5(hash_data).digest() != md5:
                raise BLTEDecoderException("data corrupted")
            self.reader.seek(old_pos)

        num_blocks = 1
        if header_size > 0:
            if size < 12:
                raise BLTEDecoderException("not enough data: 12")
            fcbytes = self.reader.read_bytes(4)
            num_blocks = (fcbytes[1] << 16) | (fcbytes[2] << 8) | fcbytes[3]
            if fcbytes[0] != 0x0F or num_blocks == 0:
                raise BLTEDecoderException(f"bad table format 0x{fcbytes[0]:x2}, numBlocks {num_blocks}")
            frame_header_size = 24 * num_blocks + 12
            if header_size != frame_header_size:
                raise BLTEDecoderException("header size mismatch")
            if size < frame_header_size:
                raise BLTEDecoderException(f"not enough data: {frame_header_size}")

        blocks: list[tuple[int, MD5Hash]] = []
        for _ in range(num_blocks):
            if header_size != 0:
                comp_size = self.reader.read_int32_be()
                self.reader.read_int32_be()
                block_hash = ensure_md5(self.reader.read_bytes(16))
            else:
                comp_size = size - 8
                block_hash = b"\0" * 16
            blocks.append((comp_size, block_hash))

        for block_index, (comp_size, block_hash) in enumerate(blocks):
            data = self.reader.read_bytes(comp_size)
            if not is_zeroed_md5(block_hash) and self.validate_data:
                if hashlib.md5(data).digest() != block_hash:
                    raise BLTEDecoderException("MD5 mismatch")
            self._handle_data_block(data, block_index)
            if self._reached_output_limit():
                break

    def _handle_data_block(self, data: bytes, index: int) -> None:
        block_type = data[0]
        if block_type == 0x45:
            self._handle_data_block(self._decrypt(data, index), index)
        elif block_type == 0x46:
            raise BLTEDecoderException("DecoderFrame not implemented")
        elif block_type == 0x4E:
            self._write_output(data[1:])
        elif block_type == 0x5A:
            remaining = self._remaining_output_bytes()
            if remaining is None:
                self._write_output(zlib.decompress(data[3:], -zlib.MAX_WBITS))
            else:
                decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
                self._write_output(decompressor.decompress(data[3:], remaining))
        else:
            raise BLTEDecoderException(f"unknown BLTE block type {chr(block_type)} (0x{block_type:02X})!")

    def _decrypt(self, data: bytes, index: int) -> bytes:
        key_name_size = data[1]
        if key_name_size == 0 or key_name_size != 8:
            raise BLTEDecoderException("keyNameSize == 0 || keyNameSize != 8")

        key_name = int.from_bytes(data[2 : 2 + key_name_size], "little")
        iv_size = data[key_name_size + 2]
        if iv_size != 4 or iv_size > 0x10:
            raise BLTEDecoderException("IVSize != 4 || IVSize > 0x10")

        iv_part = data[key_name_size + 3 : key_name_size + 3 + iv_size]
        if len(data) < iv_size + key_name_size + 4:
            raise BLTEDecoderException("data.Length < IVSize + keyNameSize + 4")

        data_offset = key_name_size + iv_size + 3
        enc_type = data[data_offset]
        if enc_type not in (self.ENCRYPTION_SALSA20, self.ENCRYPTION_ARC4):
            raise BLTEDecoderException("encType != 0x53 && encType != 0x41")
        data_offset += 1

        iv = bytearray(8)
        iv[: len(iv_part)] = iv_part
        for shift, i in zip(range(0, 32, 8), range(4)):
            iv[i] ^= (index >> shift) & 0xFF

        key = KeyService.get_key(key_name)
        if key is None:
            raise BLTEDecoderException(f"unknown keyname {key_name:016X}")
        if enc_type == self.ENCRYPTION_SALSA20:
            decryptor = KeyService.SALSA_INSTANCE.create_decryptor(key, bytes(iv))
            return decryptor.transform_final_block(data[data_offset:])
        raise BLTEDecoderException("encType A not implemented")

    def _reached_output_limit(self) -> bool:
        return self.max_output_size is not None and self.buffer.tell() >= self.max_output_size

    def _remaining_output_bytes(self) -> int | None:
        if self.max_output_size is None:
            return None
        return max(0, self.max_output_size - self.buffer.tell())

    def _write_output(self, data: bytes) -> None:
        remaining = self._remaining_output_bytes()
        if remaining is None:
            self.buffer.write(data)
            return
        if remaining > 0:
            self.buffer.write(data[:remaining])
