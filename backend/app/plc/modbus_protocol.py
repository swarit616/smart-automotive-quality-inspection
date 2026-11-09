"""Minimal Modbus TCP (MBAP + PDU) encoding/decoding for the function codes used here.

Supported: 0x01 read coils, 0x02 read discrete inputs (mapped onto coils), 0x03 read holding
registers, 0x04 read input registers (mapped onto holding registers), 0x05 write single coil,
0x06 write single register, 0x0F write multiple coils, 0x10 write multiple registers.
"""
from __future__ import annotations

import struct
from typing import Protocol

ILLEGAL_FUNCTION = 0x01
ILLEGAL_ADDRESS = 0x02
ILLEGAL_VALUE = 0x03

MAX_READ_BITS = 2000
MAX_READ_REGS = 125
MAX_WRITE_BITS = 1968
MAX_WRITE_REGS = 123


class ModbusException(Exception):
    def __init__(self, code: int, message: str = ""):
        super().__init__(message or f"modbus exception {code}")
        self.code = code


class DataStore(Protocol):
    def read_coils(self, address: int, count: int) -> list[bool]: ...
    def write_coils(self, address: int, values: list[bool]) -> None: ...
    def read_registers(self, address: int, count: int) -> list[int]: ...
    def write_registers(self, address: int, values: list[int]) -> None: ...


def pack_bits(bits: list[bool]) -> bytes:
    out = bytearray((len(bits) + 7) // 8)
    for i, b in enumerate(bits):
        if b:
            out[i // 8] |= 1 << (i % 8)
    return bytes(out)


def unpack_bits(data: bytes, count: int) -> list[bool]:
    return [bool(data[i // 8] >> (i % 8) & 1) for i in range(count)]


def process_pdu(pdu: bytes, store: DataStore) -> bytes:
    """Execute one request PDU against the datastore and return the response PDU."""
    if not pdu:
        raise ModbusException(ILLEGAL_FUNCTION, "empty PDU")
    fc = pdu[0]
    try:
        if fc in (0x01, 0x02):
            addr, count = _need(pdu, ">HH", 4)
            if not 1 <= count <= MAX_READ_BITS:
                raise ModbusException(ILLEGAL_VALUE, "bad quantity")
            bits = pack_bits(store.read_coils(addr, count))
            return bytes([fc, len(bits)]) + bits
        if fc in (0x03, 0x04):
            addr, count = _need(pdu, ">HH", 4)
            if not 1 <= count <= MAX_READ_REGS:
                raise ModbusException(ILLEGAL_VALUE, "bad quantity")
            regs = store.read_registers(addr, count)
            return bytes([fc, count * 2]) + struct.pack(f">{count}H", *regs)
        if fc == 0x05:
            addr, val = _need(pdu, ">HH", 4)
            if val not in (0x0000, 0xFF00):
                raise ModbusException(ILLEGAL_VALUE, "coil value must be 0x0000 or 0xFF00")
            store.write_coils(addr, [val == 0xFF00])
            return pdu[:5]
        if fc == 0x06:
            addr, val = _need(pdu, ">HH", 4)
            store.write_registers(addr, [val])
            return pdu[:5]
        if fc == 0x0F:
            addr, count, nbytes = _need(pdu, ">HHB", 5)
            if not 1 <= count <= MAX_WRITE_BITS or nbytes != (count + 7) // 8 or len(pdu) != 6 + nbytes:
                raise ModbusException(ILLEGAL_VALUE, "bad quantity/byte count")
            store.write_coils(addr, unpack_bits(pdu[6:], count))
            return struct.pack(">BHH", fc, addr, count)
        if fc == 0x10:
            addr, count, nbytes = _need(pdu, ">HHB", 5)
            if not 1 <= count <= MAX_WRITE_REGS or nbytes != count * 2 or len(pdu) != 6 + nbytes:
                raise ModbusException(ILLEGAL_VALUE, "bad quantity/byte count")
            store.write_registers(addr, list(struct.unpack(f">{count}H", pdu[6:])))
            return struct.pack(">BHH", fc, addr, count)
    except struct.error as exc:
        raise ModbusException(ILLEGAL_VALUE, "malformed request") from exc
    raise ModbusException(ILLEGAL_FUNCTION, f"unsupported function 0x{fc:02X}")


def _need(pdu: bytes, fmt: str, size: int) -> tuple:
    if len(pdu) < 1 + size:
        raise ModbusException(ILLEGAL_VALUE, "request too short")
    return struct.unpack(fmt, pdu[1 : 1 + size])


def exception_pdu(fc: int, code: int) -> bytes:
    return bytes([fc | 0x80, code])


def mbap(transaction: int, unit: int, pdu: bytes) -> bytes:
    return struct.pack(">HHHB", transaction & 0xFFFF, 0, len(pdu) + 1, unit) + pdu
