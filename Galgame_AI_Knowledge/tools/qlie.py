"""QLIE (FilePackVer3.0) 归档读取器 —— 只读实现。

用途：把 Navel / QLIE 引擎游戏的 ``*.pack`` 归档内容读出来，方便整理成
AI 知识库。本模块 **只读取**，不会写入或修改原始游戏文件。

算法来源：公开开源项目 GARbro (MIT License) 的 QLIE 支持模块
``ArcFormats/Qlie/{ArcQLIE,Encryption,QlieMersenneTwister}.cs``，
此处为等价的 Python 转写。

同时实现了归档内条目使用的 ``1PC\xFF`` LZ 解压缩。

命令行用法::

    python qlie.py list  <pack 文件>
    python qlie.py extract <pack 文件> <输出目录> [名字包含的关键字 ...]
    python qlie.py key <游戏 exe>        # 打印从 exe 中取出的 GameKey 指纹
"""

from __future__ import annotations

import argparse
import hashlib
import os
import struct
import sys
from dataclasses import dataclass, field
from typing import Iterable, Optional

MASK32 = 0xFFFFFFFF


# --------------------------------------------------------------------------
# MMX 风格的 64 位分道运算（对应 GARbro 用到的 PADD*/PSLLD 指令）
# --------------------------------------------------------------------------
def paddb(a: int, b: int) -> int:
    """按字节分道相加（8 条 8 位通道，各自取模 256）。"""
    out = 0
    for i in range(8):
        x = ((a >> (i * 8)) & 0xFF) + ((b >> (i * 8)) & 0xFF)
        out |= (x & 0xFF) << (i * 8)
    return out


def paddw(a: int, b: int) -> int:
    """按字（16 位）分道相加，各通道取模 65536。"""
    out = 0
    for i in range(4):
        x = ((a >> (i * 16)) & 0xFFFF) + ((b >> (i * 16)) & 0xFFFF)
        out |= (x & 0xFFFF) << (i * 16)
    return out


def paddd(a: int, b: int) -> int:
    """按双字（32 位）分道相加，各通道取模 2^32。"""
    out = 0
    for i in range(2):
        x = ((a >> (i * 32)) & MASK32) + ((b >> (i * 32)) & MASK32)
        out |= (x & MASK32) << (i * 32)
    return out


def pslld(a: int, count: int) -> int:
    """按双字分道左移。"""
    out = 0
    for i in range(2):
        x = (((a >> (i * 32)) & MASK32) << count) & MASK32
        out |= x << (i * 32)
    return out


# --------------------------------------------------------------------------
# QLIE 专用 Mersenne Twister
# --------------------------------------------------------------------------
class QlieMersenneTwister:
    STATE_LENGTH = 64
    STATE_M = 39
    MATRIX_A = 0x9908B0DF
    SIGN_MASK = 0x80000000
    LOWER_MASK = 0x7FFFFFFF
    TEMPERING_B = 0x9C4F88E3
    TEMPERING_C = 0xE7F70000

    def __init__(self, seed: int):
        self.mt = [0] * self.STATE_LENGTH
        self.mag01 = (0, self.MATRIX_A)
        self.mti = self.STATE_LENGTH
        self.srand(seed)

    def srand(self, seed: int) -> None:
        self.mt[0] = seed & MASK32
        for i in range(1, self.STATE_LENGTH):
            prev = self.mt[i - 1]
            self.mt[i] = (0x6611BC19 * (prev ^ (prev >> 30)) + i) & MASK32
        self.mti = self.STATE_LENGTH

    def xor_state(self, data: bytes) -> None:
        length = min(len(data) // 4, self.STATE_LENGTH)
        for i in range(length):
            self.mt[i] ^= struct.unpack_from("<I", data, i * 4)[0]

    def rand(self) -> int:
        mt = self.mt
        if self.mti >= self.STATE_LENGTH:
            for kk in range(self.STATE_LENGTH - self.STATE_M):
                y = (mt[kk] & self.SIGN_MASK) | ((mt[kk + 1] & self.LOWER_MASK) >> 1)
                mt[kk] = mt[kk + self.STATE_M] ^ y ^ self.mag01[mt[kk + 1] & 1]
            for kk in range(self.STATE_LENGTH - self.STATE_M, self.STATE_LENGTH - 1):
                y = (mt[kk] & self.SIGN_MASK) | ((mt[kk + 1] & self.LOWER_MASK) >> 1)
                mt[kk] = mt[kk + self.STATE_M - self.STATE_LENGTH] ^ y ^ self.mag01[mt[kk + 1] & 1]
            y = (mt[self.STATE_LENGTH - 1] & self.SIGN_MASK) | ((mt[0] & self.LOWER_MASK) >> 1)
            mt[self.STATE_LENGTH - 1] = (
                mt[self.STATE_M - 1] ^ y ^ self.mag01[mt[self.STATE_LENGTH - 2] & 1]
            )
            self.mti = 0

        y = mt[self.mti]
        self.mti += 1
        y ^= y >> 11
        y ^= (y << 7) & self.TEMPERING_B
        y ^= (y << 15) & self.TEMPERING_C
        y ^= y >> 18
        return y & MASK32

    def rand64(self) -> int:
        v = self.rand()
        return v | (self.rand() << 32)


# --------------------------------------------------------------------------
# 加密 / 名称解密
# --------------------------------------------------------------------------
def hash_v3(data: bytes) -> int:
    """EncryptionV3.CalculateHash（PADDW 累加）。"""
    h = 0
    key = 0
    for i in range(0, (len(data) // 8) * 8, 8):
        chunk = struct.unpack_from("<Q", data, i)[0]
        h = paddw(h, 0x0307030703070307)
        key = paddw(key, chunk ^ h)
    return (key ^ (key >> 32)) & MASK32


def hash_v3_1(data: bytes) -> int:
    """EncryptionV3_1.CalculateHash（用于 FilePackVer3.1）。"""
    h = 0
    key = 0
    for i in range(0, (len(data) // 8) * 8, 8):
        chunk = struct.unpack_from("<Q", data, i)[0]
        h = paddw(h, 0xA35793A7A35793A7)
        key = paddw(key, chunk ^ h)
        key = ((key << 3) | (key >> 61)) & 0xFFFFFFFFFFFFFFFF
        key &= 0xFFFFFFFFFFFFFFFF
        # 每 32 位分道循环左移 3 位
        lo = ((key & MASK32) << 3 | (key & MASK32) >> 29) & MASK32
        hi = (((key >> 32) & MASK32) << 3 | ((key >> 32) & MASK32) >> 29) & MASK32
        key = lo | (hi << 32)
    lo = key & MASK32
    hi = (key >> 32) & MASK32
    s_lo = lo & 0xFFFF
    s_lo_hi = (lo >> 16) & 0xFFFF
    s_hi = hi & 0xFFFF
    s_hi_hi = (hi >> 16) & 0xFFFF
    prod = s_lo * s_hi + s_lo_hi * s_hi_hi
    return prod & MASK32


def decrypt_name_v2(name: bytearray, name_length: int, name_key: int) -> None:
    """EncryptionV2.DecryptName（就地 XOR）。"""
    key = (name_length + (name_key ^ 0x3E)) & MASK32
    for k in range(name_length):
        name[k] ^= (((k + 1) ^ key) + k + 1) & 0xFF


def decrypt_name_v3_1(name: bytearray, name_length: int, name_key: int) -> None:
    """EncryptionV3_1.DecryptName（UTF-16LE 名称，就地 XOR）。"""
    char_count = name_length // 2
    h = (char_count * char_count) ^ char_count
    h ^= 0x3E13 ^ (name_key >> 16) ^ name_key
    h &= 0xFFFF
    key = h
    for i in range(char_count):
        key = h + i + 8 * key
        name[i * 2] ^= key & 0xFF
        name[i * 2 + 1] ^= (key >> 8) & 0xFF


def _decrypt_v1(data: bytearray, length: int, arc_key: int) -> None:
    hash64 = 0xA73C5F9DA73C5F9D
    xor = (arc_key ^ 0xFEC9753E) & MASK32
    xor |= xor << 32
    for i in range(length // 8):
        off = i * 8
        hash64 = paddd(hash64, 0xCE24F523CE24F523) ^ xor
        val = struct.unpack_from("<Q", data, off)[0]
        out = val ^ hash64
        struct.pack_into("<Q", data, off, out)


def _decrypt_v2(data: bytearray, length: int, arc_key: int) -> None:
    hash64 = 0xA73C5F9DA73C5F9D
    xor = ((length & MASK32) + arc_key) & MASK32
    xor ^= 0xFEC9753E
    xor |= xor << 32
    for i in range(length // 8):
        off = i * 8
        hash64 = paddd(hash64, 0xCE24F523CE24F523) ^ xor
        val = struct.unpack_from("<Q", data, off)[0]
        out = val ^ hash64
        struct.pack_into("<Q", data, off, out)


def _xor4(data: bytearray) -> None:
    """把 bytes 中前 0x100 字节与偏移 0x100 处的 0x100 字节逐位异或。"""
    if len(data) < 0x200:
        return
    a, b = data[0x0:0x100], data[0x100:0x200]
    for i in range(0x100):
        data[i] = a[i] ^ b[i]


def decrypt_entry_v3(
    data: bytearray,
    length: int,
    raw_name: bytes,
    arc_key: int,
    key_file: Optional[bytes],
    game_key: Optional[bytes],
) -> None:
    """EncryptionV3.DecryptEntry（就地解密）。"""
    if key_file is None or (game_key is not None and len(game_key) == 0):
        _decrypt_v2(data, length, arc_key)
        return
    if length < 8:
        return

    hash_ = 0x85F532
    seed = 0x33F641
    for i in range(len(raw_name)):
        hash_ = (hash_ + (i & 0xFF) * raw_name[i]) & MASK32
        seed ^= hash_
    mix = (7 * (length & 0xFFFFFF) + length + hash_ + (hash_ ^ length ^ 0x8F32DC)) & MASK32
    seed = (seed + (arc_key ^ mix)) & MASK32
    seed = 9 * (seed & 0xFFFFFF) & MASK32
    if game_key is not None:
        seed ^= 0x453A

    mt = QlieMersenneTwister(seed)
    mt.xor_state(key_file)
    if game_key is not None and len(game_key):
        mt.xor_state(game_key)

    table = [mt.rand64() for _ in range(16)]
    for _ in range(9):
        mt.rand()
    hash64 = mt.rand64()
    t = mt.rand() & 0xF

    # 先取出 bytearray 中 16 字节对齐之后的数据（调用方保证 offset 为 0 或已切片）
    buf = memoryview(data)
    for i in range(length // 8):
        off = i * 8
        hash64 = paddd(hash64 ^ table[t], table[t])
        val = struct.unpack_from("<Q", buf, off)[0]
        out = val ^ hash64
        struct.pack_into("<Q", data, off, out)
        hash64 = paddb(hash64, out) ^ out
        hash64 = paddw(pslld(hash64, 1), out)
        t = (t + 1) & 0xF


# --------------------------------------------------------------------------
# 1PC\xFF LZ 解压缩
# --------------------------------------------------------------------------
def decompress_1pc(data: bytes) -> Optional[bytes]:
    if len(data) < 12 or struct.unpack_from("<I", data, 0)[0] != 0xFF435031:
        return None
    is_16bit = bool(data[4] & 1)
    node0 = bytearray(256)
    node1 = bytearray(256)
    child = bytearray(256)
    out_len = struct.unpack_from("<I", data, 8)[0]
    if out_len == 0 or out_len > 0x40000000:
        return None
    out = bytearray(out_len)
    src = 12
    dst = 0
    n = len(data)
    while src < n:
        for i in range(256):
            node0[i] = i
        i = 0
        while i < 256:
            if src >= n:
                break
            count = data[src]
            src += 1
            if count > 127:
                i += count - 127
                count = 0
            if i > 255:
                break
            count += 1
            for _ in range(count):
                if src >= n:
                    break
                node0[i] = data[src]
                src += 1
                if node0[i] != (i & 0xFF):
                    if src >= n:
                        break
                    node1[i] = data[src]
                    src += 1
                i += 1
                if i > 255:
                    break
        if is_16bit:
            if src + 2 > n:
                break
            count = struct.unpack_from("<H", data, src)[0]
            src += 2
        else:
            if src + 4 > n:
                break
            count = struct.unpack_from("<i", data, src)[0]
            src += 4

        k = 0
        while True:
            if k > 0:
                k -= 1
                index = child[k]
            else:
                if count == 0:
                    break
                count -= 1
                if src >= n:
                    break
                index = data[src]
                src += 1
            if node0[index] == index:
                if dst >= out_len:
                    return None
                out[dst] = index
                dst += 1
            else:
                child[k] = node1[index]
                k += 1
                child[k] = node0[index]
                k += 1
    if dst != out_len:
        return None
    return bytes(out)


# --------------------------------------------------------------------------
# EXE 中隐藏的 GameKey（TFORM1 -> IconKeyImage -> Picture.Data）
# --------------------------------------------------------------------------
def game_key_from_exe(path: str) -> Optional[bytes]:
    """QLIE 把 V3 归档的解密用 KeyData 藏在 exe 的窗体资源里。"""
    with open(path, "rb") as f:
        d = f.read()
    pos = 0
    while True:
        pos = d.find(b"TPF0", pos)
        if pos < 0:
            return None
        chunk = d[pos : pos + 0x20000]
        if b"IconKeyImage" in chunk:
            idx = chunk.find(b"\x05TIcon")
            if idx >= 0 and idx + 6 + 0x100 <= len(chunk):
                return chunk[idx + 6 : idx + 6 + 0x100]
        pos += 4


# --------------------------------------------------------------------------
# 归档读取
# --------------------------------------------------------------------------
@dataclass
class QlieEntry:
    name: str
    offset: int
    size: int
    unpacked_size: int
    is_packed: int
    encryption_method: int
    hash: int = 0
    raw_name: bytes = field(default=b"", repr=False)


class QlieArchive:
    """按需读取 QLIE ``*.pack``。打开时只解析索引，不碰条目数据。"""

    def __init__(
        self,
        path: str,
        key_file: Optional[bytes] = None,
        game_key: Optional[bytes] = None,
        use_pack_keyfile: Optional[bool] = None,
    ):
        self.path = path
        self.name = os.path.basename(path)
        self.key_file = key_file
        self.game_key = game_key
        self.entries: list[QlieEntry] = []
        self._fh = open(path, "rb")
        self._parse(use_pack_keyfile)

    # -- 索引 -------------------------------------------------------------
    def _read_tail(self) -> bytes:
        self._fh.seek(0, os.SEEK_END)
        size = self._fh.tell()
        self.size = size
        self._fh.seek(size - 0x1C)
        return self._fh.read(0x1C)

    def _parse(self, use_pack_keyfile: Optional[bool]) -> None:
        tail = self._read_tail()
        if tail[0:11] != b"FilePackVer":
            raise ValueError(f"{self.name}: 不是 QLIE pack 归档")
        self.major = tail[0x0B] - 0x30
        self.minor = tail[0x0D] - 0x30
        count = struct.unpack_from("<i", tail, 0x10)[0]
        index_offset = struct.unpack_from("<q", tail, 0x14)[0]

        self._fh.seek(self.size - 0x41C)
        key_data = self._fh.read(0x100)
        if self.major == 3 and self.minor == 1:
            self.arc_key = hash_v3_1(key_data) & 0x0FFFFFFF
            self.is_unicode = True
        else:
            self.arc_key = hash_v3(key_data) & 0x0FFFFFFF
            self.is_unicode = False
        self.name_key = self.arc_key

        if self.major < 2:
            raise NotImplementedError("本工具目前只处理 FilePackVer2/3 归档")

        if use_pack_keyfile is None:
            use_pack_keyfile = self.key_file is not None and self.major >= 3
        read_pack_keyfile = bool(self.major == 3 and use_pack_keyfile)

        self._fh.seek(index_offset)
        pending_key_file = self.key_file
        for _ in range(count):
            name_length = struct.unpack("<H", self._fh.read(2))[0]
            if name_length > 0x100:
                raise ValueError(f"{self.name}: 索引名称长度异常 ({name_length})")
            if self.is_unicode:
                raw_len = name_length * 2
            else:
                raw_len = name_length
            raw = bytearray(self._fh.read(raw_len))
            if self.is_unicode:
                decrypt_name_v3_1(raw, raw_len, self.name_key)
                name = raw.decode("utf-16-le", errors="replace")
            else:
                decrypt_name_v2(raw, raw_len, self.name_key)
                name = raw.decode("cp932", errors="replace")

            offset = struct.unpack("<q", self._fh.read(8))[0]
            size = struct.unpack("<I", self._fh.read(4))[0]
            unpacked_size = struct.unpack("<I", self._fh.read(4))[0]
            is_packed = struct.unpack("<i", self._fh.read(4))[0]
            enc_method = struct.unpack("<i", self._fh.read(4))[0]
            hash_ = struct.unpack("<I", self._fh.read(4))[0]

            entry = QlieEntry(
                name=name,
                offset=offset,
                size=size,
                unpacked_size=unpacked_size,
                is_packed=is_packed,
                encryption_method=enc_method,
                hash=hash_,
                raw_name=bytes(raw),
            )
            self.entries.append(entry)

            if read_pack_keyfile and "pack_keyfile" in name:
                pending_key_file = self.read_entry(entry, key_file=pending_key_file)
                self.key_file = pending_key_file
                read_pack_keyfile = False

    # -- 条目 -------------------------------------------------------------
    def read_entry(
        self,
        entry: QlieEntry,
        key_file: Optional[bytes] = None,
        game_key: Optional[bytes] = None,
    ) -> bytes:
        if key_file is None:
            key_file = self.key_file
        if game_key is None:
            game_key = self.game_key
        # 读取条目数据时不能破坏索引流的当前位置（索引解析过程中也会调用本方法）
        saved_pos = self._fh.tell()
        try:
            self._fh.seek(entry.offset)
            data = bytearray(self._fh.read(entry.size))
        finally:
            self._fh.seek(saved_pos)
        if entry.encryption_method != 0:
            decrypt_entry_v3(data, len(data), entry.raw_name, self.arc_key, key_file, game_key)
        if entry.is_packed:
            out = decompress_1pc(bytes(data))
            if out is not None:
                return out
        return bytes(data)

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> "QlieArchive":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def find_key_file(pack_path: str) -> Optional[bytes]:
    """按 QLIE 约定在归档附近寻找 key.fkey。"""
    base = os.path.dirname(os.path.abspath(pack_path))
    for rel in (".", "..", os.path.join("..", "DLL"), "DLL"):
        candidate = os.path.join(base, rel, "key.fkey")
        if os.path.isfile(candidate):
            with open(candidate, "rb") as f:
                return f.read()
    return None


# --------------------------------------------------------------------------
# 命令行
# --------------------------------------------------------------------------
def _cmd_list(args: argparse.Namespace) -> int:
    key_file = find_key_file(args.pack)
    game_key = None
    if args.exe:
        game_key = game_key_from_exe(args.exe)
    with QlieArchive(args.pack, key_file, game_key) as arc:
        print(f"# {arc.name}  FilePackVer{arc.major}.{arc.minor}  条目 {len(arc.entries)} 个")
        for e in arc.entries:
            flag = []
            if e.encryption_method:
                flag.append("enc")
            if e.is_packed:
                flag.append("zip")
            print(
                f"{e.size:>12}  {e.unpacked_size:>12}  {'+'.join(flag) or '--':<7}  {e.name}"
            )
    return 0


def _cmd_extract(args: argparse.Namespace) -> int:
    key_file = find_key_file(args.pack)
    game_key = None
    if args.exe:
        game_key = game_key_from_exe(args.exe)
    filters = args.filters or []
    written = 0
    with QlieArchive(args.pack, key_file, game_key) as arc:
        for e in arc.entries:
            if filters and not any(f.lower() in e.name.lower() for f in filters):
                continue
            data = arc.read_entry(e)
            target = os.path.join(args.outdir, e.name.replace("\\", "/").lstrip("/"))
            os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
            with open(target, "wb") as f:
                f.write(data)
            written += 1
            print(f"{len(data):>12}  {e.name}")
    print(f"# 共写出 {written} 个文件 -> {args.outdir}")
    return 0


def _cmd_key(args: argparse.Namespace) -> int:
    key = game_key_from_exe(args.exe)
    if key is None:
        print("未找到 GameKey")
        return 1
    print(f"GameKey len={len(key)} md5={hashlib.md5(key).hexdigest()}")
    return 0


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="QLIE pack 归档只读读取器")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="列出归档内文件")
    p_list.add_argument("pack")
    p_list.add_argument("--exe", help="游戏 exe（用于取 GameKey）")
    p_list.set_defaults(func=_cmd_list)

    p_ext = sub.add_parser("extract", help="导出归档内容")
    p_ext.add_argument("pack")
    p_ext.add_argument("outdir")
    p_ext.add_argument("filters", nargs="*", help="只导出名字含这些关键字的文件")
    p_ext.add_argument("--exe", help="游戏 exe（用于取 GameKey）")
    p_ext.set_defaults(func=_cmd_extract)

    p_key = sub.add_parser("key", help="显示 exe 中的 GameKey 指纹")
    p_key.add_argument("exe")
    p_key.set_defaults(func=_cmd_key)

    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
