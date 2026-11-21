"""Binary encoding of BCD "device" elements (partition on a GPT or MBR disk).

Layout (88 bytes), reverse engineered from stores written by bcdboot and
documented in docs/BCD.md:

  0x00 16  GUID  additional options (zero)
  0x10  4  u32   device type: 6 = partition
  0x14  4  u32   flags (0)
  0x18  4  u32   size of the device data from 0x10 (0x48)
  0x1C  4  u32   reserved (0)
  0x20 16        partition identifier: GPT partition GUID (bytes_le)
                 or MBR partition byte offset (u64) + 8 zero bytes
  0x30  4  u32   partition style: 0 = GPT, 1 = MBR
  0x34  4  u32   reserved (0)
  0x38 16        disk identifier: GPT disk GUID (bytes_le) or MBR signature (u32)
  0x48 16        zero padding
"""

from __future__ import annotations

import struct
import uuid
from dataclasses import dataclass

DEVICE_PARTITION = 6
DEVICE_BOOT = 5
DATA_SIZE = 0x48
TOTAL_SIZE = 0x58
STYLE_GPT = 0
STYLE_MBR = 1


@dataclass
class DeviceInfo:
    device_type: int
    style: int | None = None
    partition_guid: str | None = None
    disk_guid: str | None = None
    mbr_offset: int | None = None
    mbr_signature: int | None = None

    @property
    def is_gpt_partition(self) -> bool:
        return self.device_type == DEVICE_PARTITION and self.style == STYLE_GPT


def encode_gpt_partition(partition_guid: str, disk_guid: str) -> bytes:
    head = b"\0" * 16 + struct.pack("<IIII", DEVICE_PARTITION, 0, DATA_SIZE, 0)
    body = uuid.UUID(partition_guid).bytes_le + struct.pack("<II", STYLE_GPT, 0) + uuid.UUID(disk_guid).bytes_le
    out = head + body + b"\0" * 16
    assert len(out) == TOTAL_SIZE
    return out


def encode_mbr_partition(offset_bytes: int, signature: int) -> bytes:
    head = b"\0" * 16 + struct.pack("<IIII", DEVICE_PARTITION, 0, DATA_SIZE, 0)
    body = struct.pack("<Q", offset_bytes) + b"\0" * 8 + struct.pack("<II", STYLE_MBR, 0)
    body += struct.pack("<I", signature) + b"\0" * 12
    out = head + body + b"\0" * 16
    assert len(out) == TOTAL_SIZE
    return out


def decode(data: bytes) -> DeviceInfo | None:
    if len(data) < 0x20:
        return None
    dtype = struct.unpack_from("<I", data, 0x10)[0]
    info = DeviceInfo(dtype)
    if dtype != DEVICE_PARTITION or len(data) < 0x48:
        return info
    style = struct.unpack_from("<I", data, 0x30)[0]
    info.style = style
    if style == STYLE_GPT:
        info.partition_guid = str(uuid.UUID(bytes_le=bytes(data[0x20:0x30])))
        info.disk_guid = str(uuid.UUID(bytes_le=bytes(data[0x38:0x48])))
    elif style == STYLE_MBR:
        info.mbr_offset = struct.unpack_from("<Q", data, 0x20)[0]
        info.mbr_signature = struct.unpack_from("<I", data, 0x38)[0]
    return info
