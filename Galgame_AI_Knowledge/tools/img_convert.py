"""把 QLIE 的图像产物转成通用格式，供读图/看图使用。

支持的输入：
  1) QLIE DPNG（游戏内扩展名为 .png）：48 字节文件头（含画布尺寸与第 1 块的位置）
     ＋ 若干块 tile PNG ＋ 每块后 28 字节的下一块描述 (x, y, w, h, size, 1, 0)。
     转换 = 解码每块 PNG(RGBA) 后按 (x, y) 拼到画布上。
  2) 标准 BMP（游戏内 CG／背景为 1280x720 24bpp BI_RGB）：转成 PNG。
  3) 已是标准 PNG：原样复制。

输出一律为 PNG（8bit RGB/RGBA），只依赖 Python 3 标准库（struct + zlib）。

用法：
  python img_convert.py <输入文件或目录> <输出目录>        # 目录会递归处理
"""

from __future__ import annotations

import os
import struct
import sys
import zlib

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def write_png(path: str, width: int, height: int, rows: list[bytes], alpha: bool) -> None:
    color_type = 6 if alpha else 2
    raw = b"".join(b"\x00" + r for r in rows)
    with open(path, "wb") as f:
        f.write(
            PNG_MAGIC
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(raw, 6))
            + _chunk(b"IEND", b"")
        )


# ---------------------------------------------------------------- PNG 解码

def read_png(blob: bytes):
    """解析一段标准 PNG，返回 (width, height, bpp, pixels)。

    仅支持 bit depth 8、color type 2(RGB) / 6(RGBA)——QLIE 的 tile 都是这两种。
    """
    if blob[:8] != PNG_MAGIC:
        raise ValueError("PNG 魔数不对")
    pos = 8
    width = height = depth = ctype = None
    idat = bytearray()
    while pos + 8 <= len(blob):
        ln = struct.unpack_from(">I", blob, pos)[0]
        tag = blob[pos + 4 : pos + 8]
        data = blob[pos + 8 : pos + 8 + ln]
        if tag == b"IHDR":
            width, height, depth, ctype = struct.unpack(">IIBB", data[:10])
        elif tag == b"IDAT":
            idat += data
        elif tag == b"IEND":
            break
        pos += 12 + ln
    if depth != 8 or ctype not in (2, 6):
        raise ValueError("不支持的 PNG：depth=%s color=%s" % (depth, ctype))
    bpp = 4 if ctype == 6 else 3
    stride = width * bpp
    raw = zlib.decompress(bytes(idat))
    out = bytearray(height * stride)
    prev = bytearray(stride)
    p = 0
    for y in range(height):
        f = raw[p]
        p += 1
        line = bytearray(raw[p : p + stride])
        p += stride
        if f == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif f == 3:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif f == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                pa = abs(b - c)
                pb = abs(a - c)
                pc = abs(a + b - 2 * c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        elif f != 0:
            raise ValueError("未知 PNG 行过滤 %d" % f)
        out[y * stride : (y + 1) * stride] = line
        prev = line
    return width, height, bpp, out


def _blit(canvas: bytearray, cw: int, ch: int, x: int, y: int, tw: int, th: int, bpp: int, px) -> None:
    """把一块图贴到画布（source-over，源为 RGBA/RGB）。"""
    for ty in range(th):
        cy = y + ty
        if cy < 0 or cy >= ch:
            continue
        src_row = ty * tw * bpp
        dst_row = (cy * cw + x) * 4
        for tx in range(tw):
            cx = x + tx
            if cx < 0 or cx >= cw:
                continue
            si = src_row + tx * bpp
            di = dst_row + tx * 4
            if bpp == 4:
                sa = px[si + 3]
                if sa == 0:
                    continue
                if sa == 255:
                    canvas[di : di + 4] = px[si : si + 4]
                else:
                    inv = 255 - sa
                    canvas[di] = (px[si] * sa + canvas[di] * inv) // 255
                    canvas[di + 1] = (px[si + 1] * sa + canvas[di + 1] * inv) // 255
                    canvas[di + 2] = (px[si + 2] * sa + canvas[di + 2] * inv) // 255
                    canvas[di + 3] = min(255, sa + canvas[di + 3] * inv // 255)
            else:
                canvas[di : di + 3] = px[si : si + 3]
                canvas[di + 3] = 255


def convert_dpng(data: bytes, out_path: str) -> str:
    if data[:4] != b"DPNG":
        raise ValueError("不是 DPNG")
    cw, ch = struct.unpack_from("<II", data, 12)
    x, y, w, h, _size, _a, _b = struct.unpack_from("<IIIIIII", data, 20)
    canvas = bytearray(cw * ch * 4)
    pos = 48
    tiles = 0
    while True:
        end = data.find(b"IEND", pos)
        if end < 0:
            break
        png_end = end + 8
        tw, th, bpp, px = read_png(data[pos:png_end])
        _blit(canvas, cw, ch, x, y, tw, th, bpp, px)
        tiles += 1
        if png_end + 28 > len(data):
            break
        x, y, w, h, _size, _a, _b = struct.unpack_from("<IIIIIII", data, png_end)
        pos = png_end + 28
    rows = [bytes(canvas[r * cw * 4 : (r + 1) * cw * 4]) for r in range(ch)]
    write_png(out_path, cw, ch, rows, alpha=True)
    return "dpng->png (%d 块拼成 %dx%d)" % (tiles, cw, ch)


# ---------------------------------------------------------------- BMP

def convert_bmp(data: bytes, out_path: str) -> str:
    if data[:2] != b"BM":
        raise ValueError("不是 BMP")
    data_off = struct.unpack_from("<I", data, 10)[0]
    hdr_size = struct.unpack_from("<I", data, 14)[0]
    if hdr_size < 40:
        raise ValueError("不支持的 BMP 头（%d 字节）" % hdr_size)
    width, height = struct.unpack_from("<ii", data, 18)
    bpp = struct.unpack_from("<H", data, 28)[0]
    compression = struct.unpack_from("<I", data, 30)[0]
    if compression != 0:
        raise ValueError("不支持的 BMP 压缩方式 %d" % compression)
    if bpp not in (24, 32):
        raise ValueError("不支持的 BMP 位深 %d（仅 24/32）" % bpp)
    bottom_up = height > 0
    h = abs(height)
    stride = ((width * bpp // 8) + 3) // 4 * 4
    step = bpp // 8
    rows: list[bytes] = []
    for y in range(h):
        src_y = (h - 1 - y) if bottom_up else y
        start = data_off + src_y * stride
        line = data[start : start + width * step]
        if step == 4:
            px = bytearray(width * 4)
            for i in range(width):
                b, g, r, a = line[i * 4 : i * 4 + 4]
                px[i * 4 : i * 4 + 4] = bytes((r, g, b, a))
            rows.append(bytes(px))
        else:
            px = bytearray(width * 3)
            for i in range(width):
                b, g, r = line[i * 3 : i * 3 + 3]
                px[i * 3 : i * 3 + 3] = bytes((r, g, b))
            rows.append(bytes(px))
    write_png(out_path, width, h, rows, alpha=(bpp == 32))
    return "bmp->png (%dx%d, %dbpp)" % (width, h, bpp)


# ---------------------------------------------------------------- 入口

def convert_file(src: str, dst_dir: str) -> str:
    with open(src, "rb") as f:
        data = f.read()
    out_path = os.path.join(dst_dir, os.path.splitext(os.path.basename(src))[0] + ".png")
    os.makedirs(dst_dir, exist_ok=True)
    if data[:4] == b"DPNG":
        how = convert_dpng(data, out_path)
    elif data[:2] == b"BM":
        how = convert_bmp(data, out_path)
    elif data[:8] == PNG_MAGIC:
        with open(out_path, "wb") as f:
            f.write(data)
        how = "png 原样复制"
    else:
        raise ValueError("未知图像格式")
    return "%s  ->  %s" % (how, out_path)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    src, dst_dir = argv[1], argv[2]
    targets: list[str] = []
    if os.path.isdir(src):
        for root, _dirs, files in os.walk(src):
            for name in files:
                targets.append(os.path.join(root, name))
    else:
        targets.append(src)
    ok = bad = 0
    for path in targets:
        try:
            print(convert_file(path, dst_dir))
            ok += 1
        except Exception as exc:  # noqa: BLE001 - 逐文件报告，不中断批处理
            print("[跳过] %s : %s" % (path, exc))
            bad += 1
    print("# 成功 %d / 跳过 %d -> %s" % (ok, bad, dst_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
