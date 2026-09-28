"""按名字一键取图：从 pack 里抽出指定图像并转成可读 PNG。

用法：
  python get_image.py LUN31A              # 事件 CG（不分大小写，可用部分名）
  python get_image.py lun_l_3_0_04        # 立绘
  python get_image.py --list miz04        # 只列出匹配到的条目，不导出

流程：在 reports/pack_index/data*.txt 里找匹配条目 → 取**序号最大**的 pack
（多版本合并规则：pack 序号大者优先）→ 用 qlie.py 解密取出 → 用 img_convert.py
转成 PNG（DPNG 分块拼接 / BMP 转换）→ 打印 PNG 路径。

已转好的图会直接复用（extracted/images_png/<名字>.png）。
"""

from __future__ import annotations

import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import img_convert  # noqa: E402
import qlie  # noqa: E402

KB = os.path.dirname(HERE)
PACK_INDEX = os.path.join(KB, "reports", "pack_index")
PACK_DIR = "E:\\gal\\Navel\\" + "\u8fd1\u6708\u5c11\u5973\u7684\u793c\u4eea" + "\\GameData"
EXE = "E:\\gal\\Navel\\" + "\u8fd1\u6708\u5c11\u5973\u7684\u793c\u4eea" + "\\\u6708\u306b\u5bc4\u308a\u305d\u3046\u4e59\u5973\u306e\u4f5c\u6cd5.exe"
IMG_EXT = (".png", ".bmp", ".dpng", ".abmp", ".argb", ".b", ".jpg")
OUT_DIR = os.path.join(KB, "extracted", "images_png")


def find_entries(keyword: str):
    """返回 [(pack_no, entry_name)]，按找到顺序（pack 号升序）。"""
    hits = []
    for path in sorted(glob.glob(os.path.join(PACK_INDEX, "data*.txt"))):
        m = re.search(r"data(\d+)", os.path.basename(path))
        if not m:
            continue
        pack_no = int(m.group(1))
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.rstrip("\n").split(None, 3)
                if len(parts) < 4:
                    continue
                entry = parts[3]
                low = entry.lower()
                if not low.endswith(IMG_EXT):
                    continue
                if keyword.lower() in low:
                    hits.append((pack_no, entry))
    return hits


def pick(hits, keyword: str):
    """优先精确同名（不含扩展名）匹配，其次取最大 pack。"""
    if not hits:
        return None
    exact = [h for h in hits if os.path.splitext(os.path.basename(h[1]))[0].lower() == keyword.lower()]
    pool = exact or hits
    return max(pool, key=lambda h: h[0])


def extract(pack_no: int, entry: str) -> str:
    pack = os.path.join(PACK_DIR, "data%d.pack" % pack_no)
    key = qlie.find_key_file(pack)
    game_key = qlie.game_key_from_exe(EXE)
    with qlie.QlieArchive(pack, key, game_key) as arc:
        for e in arc.entries:
            if e.name == entry:
                os.makedirs(OUT_DIR, exist_ok=True)
                tmp = os.path.join(OUT_DIR, os.path.basename(entry))
                with open(tmp, "wb") as f:
                    f.write(arc.read_entry(e))
                return tmp
    raise SystemExit("pack 内未找到条目: %s" % entry)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    if argv[1] == "--list":
        keyword = argv[2] if len(argv) > 2 else ""
        for pack_no, entry in find_entries(keyword):
            print("data%-3d %s" % (pack_no, entry))
        return 0

    keyword = argv[1]
    hits = find_entries(keyword)
    if not hits:
        print("没有匹配到图像条目: %s" % keyword)
        return 1
    pack_no, entry = pick(hits, keyword)
    stem = os.path.splitext(os.path.basename(entry))[0]
    cached = os.path.join(OUT_DIR, stem + ".png")
    if os.path.isfile(cached):
        print("（已存在）%s" % cached)
        return 0
    tmp = extract(pack_no, entry)
    print("取自 data%d.pack : %s" % (pack_no, entry))
    img_convert.convert_file(tmp, OUT_DIR)
    if not os.path.isfile(cached):
        print("转换后的 PNG 未找到，请检查: %s" % cached)
        return 1
    print("PNG: %s" % cached)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
