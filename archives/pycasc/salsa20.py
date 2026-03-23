from __future__ import annotations


class Salsa20:
    SIGMA = b"expand 32-byte k"
    TAU = b"expand 16-byte k"

    @staticmethod
    def _rotate(value: int, count: int) -> int:
        return ((value << count) | (value >> (32 - count))) & 0xFFFFFFFF

    @staticmethod
    def _add(left: int, right: int) -> int:
        return (left + right) & 0xFFFFFFFF

    @staticmethod
    def _to_uint32(data: bytes, offset: int) -> int:
        return int.from_bytes(data[offset : offset + 4], "little")

    @staticmethod
    def _to_bytes(value: int) -> bytes:
        return value.to_bytes(4, "little")

    def create_decryptor(self, key: bytes, iv: bytes):
        if len(key) not in (16, 32):
            raise ValueError("Invalid key size; it must be 128 or 256 bits.")
        if len(iv) != 8:
            raise ValueError("Invalid IV size; it must be 8 bytes.")
        return Salsa20Transform(key, iv)


class Salsa20Transform:
    def __init__(self, key: bytes, iv: bytes, rounds: int = 20) -> None:
        self.rounds = rounds
        self.state = self._initialize(key, iv)

    def _initialize(self, key: bytes, iv: bytes) -> list[int]:
        constants = Salsa20.SIGMA if len(key) == 32 else Salsa20.TAU
        key_index = len(key) - 16
        state = [0] * 16
        state[1] = Salsa20._to_uint32(key, 0)
        state[2] = Salsa20._to_uint32(key, 4)
        state[3] = Salsa20._to_uint32(key, 8)
        state[4] = Salsa20._to_uint32(key, 12)
        state[11] = Salsa20._to_uint32(key, key_index + 0)
        state[12] = Salsa20._to_uint32(key, key_index + 4)
        state[13] = Salsa20._to_uint32(key, key_index + 8)
        state[14] = Salsa20._to_uint32(key, key_index + 12)
        state[0] = Salsa20._to_uint32(constants, 0)
        state[5] = Salsa20._to_uint32(constants, 4)
        state[10] = Salsa20._to_uint32(constants, 8)
        state[15] = Salsa20._to_uint32(constants, 12)
        state[6] = Salsa20._to_uint32(iv, 0)
        state[7] = Salsa20._to_uint32(iv, 4)
        state[8] = 0
        state[9] = 0
        return state

    def _hash(self, state_in: list[int]) -> bytes:
        state = state_in[:]
        for _ in range(self.rounds, 0, -2):
            state[4] ^= Salsa20._rotate(Salsa20._add(state[0], state[12]), 7)
            state[8] ^= Salsa20._rotate(Salsa20._add(state[4], state[0]), 9)
            state[12] ^= Salsa20._rotate(Salsa20._add(state[8], state[4]), 13)
            state[0] ^= Salsa20._rotate(Salsa20._add(state[12], state[8]), 18)
            state[9] ^= Salsa20._rotate(Salsa20._add(state[5], state[1]), 7)
            state[13] ^= Salsa20._rotate(Salsa20._add(state[9], state[5]), 9)
            state[1] ^= Salsa20._rotate(Salsa20._add(state[13], state[9]), 13)
            state[5] ^= Salsa20._rotate(Salsa20._add(state[1], state[13]), 18)
            state[14] ^= Salsa20._rotate(Salsa20._add(state[10], state[6]), 7)
            state[2] ^= Salsa20._rotate(Salsa20._add(state[14], state[10]), 9)
            state[6] ^= Salsa20._rotate(Salsa20._add(state[2], state[14]), 13)
            state[10] ^= Salsa20._rotate(Salsa20._add(state[6], state[2]), 18)
            state[3] ^= Salsa20._rotate(Salsa20._add(state[15], state[11]), 7)
            state[7] ^= Salsa20._rotate(Salsa20._add(state[3], state[15]), 9)
            state[11] ^= Salsa20._rotate(Salsa20._add(state[7], state[3]), 13)
            state[15] ^= Salsa20._rotate(Salsa20._add(state[11], state[7]), 18)
            state[1] ^= Salsa20._rotate(Salsa20._add(state[0], state[3]), 7)
            state[2] ^= Salsa20._rotate(Salsa20._add(state[1], state[0]), 9)
            state[3] ^= Salsa20._rotate(Salsa20._add(state[2], state[1]), 13)
            state[0] ^= Salsa20._rotate(Salsa20._add(state[3], state[2]), 18)
            state[6] ^= Salsa20._rotate(Salsa20._add(state[5], state[4]), 7)
            state[7] ^= Salsa20._rotate(Salsa20._add(state[6], state[5]), 9)
            state[4] ^= Salsa20._rotate(Salsa20._add(state[7], state[6]), 13)
            state[5] ^= Salsa20._rotate(Salsa20._add(state[4], state[7]), 18)
            state[11] ^= Salsa20._rotate(Salsa20._add(state[10], state[9]), 7)
            state[8] ^= Salsa20._rotate(Salsa20._add(state[11], state[10]), 9)
            state[9] ^= Salsa20._rotate(Salsa20._add(state[8], state[11]), 13)
            state[10] ^= Salsa20._rotate(Salsa20._add(state[9], state[8]), 18)
            state[12] ^= Salsa20._rotate(Salsa20._add(state[15], state[14]), 7)
            state[13] ^= Salsa20._rotate(Salsa20._add(state[12], state[15]), 9)
            state[14] ^= Salsa20._rotate(Salsa20._add(state[13], state[12]), 13)
            state[15] ^= Salsa20._rotate(Salsa20._add(state[14], state[13]), 18)

        output = bytearray()
        for index in range(16):
            output.extend(Salsa20._to_bytes(Salsa20._add(state[index], state_in[index])))
        return bytes(output)

    def transform_final_block(self, data: bytes) -> bytes:
        output = bytearray(len(data))
        offset = 0
        remaining = len(data)
        while remaining > 0:
            block = self._hash(self.state)
            self.state[8] = (self.state[8] + 1) & 0xFFFFFFFF
            if self.state[8] == 0:
                self.state[9] = (self.state[9] + 1) & 0xFFFFFFFF

            block_size = min(64, remaining)
            for index in range(block_size):
                output[offset + index] = data[offset + index] ^ block[index]

            remaining -= block_size
            offset += block_size
        return bytes(output)
