"""从 QLIE 归档中导出剧本文本类资源（只读原始 pack）。

输出：
  extracted/packs/<pack名>/<归档内路径>   每个 pack 的原始文件（未做任何转换）
  extracted/merged/<归档内路径>           按“后加载的 pack 覆盖先加载的”合并后的版本
  reports/extract_manifest.json           每个文件的来源 pack / 大小 / MD5

注意：脚本文件本体是 Shift-JIS 编码的明文，导出时可以只改扩展名方便识别，
内容一个字节都不改（改名的副本另存为 *_utf8.txt 时才做编码转换）。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from qlie import QlieArchive, find_key_file, game_key_from_exe  # noqa: E402

GAME_DIR = r"E:\gal\Navel\近月少女的礼仪"
GAMEDATA = os.path.join(GAME_DIR, "GameData")
GAME_EXE = os.path.join(GAME_DIR, "月に寄りそう乙女の作法.exe")

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_PACKS = os.path.join(PROJECT, "extracted", "packs")
OUT_MERGED = os.path.join(PROJECT, "extracted", "merged")
MANIFEST = os.path.join(PROJECT, "reports", "extract_manifest.json")

# 只导出文本类资源，图片 / 音频不重复搬运
WANTED_EXT = (".s", ".txt", ".b", ".dat", ".key", ".csv")


def pack_sort_key(path: str) -> int:
    m = re.search(r"data(\d+)\.pack$", os.path.basename(path))
    return int(m.group(1)) if m else -1


def main() -> int:
    packs = [
        os.path.join(GAMEDATA, f)
        for f in os.listdir(GAMEDATA)
        if f.lower().endswith(".pack")
    ]
    packs.sort(key=pack_sort_key)

    os.makedirs(OUT_PACKS, exist_ok=True)
    os.makedirs(OUT_MERGED, exist_ok=True)
    os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)

    key_file = find_key_file(packs[0])
    game_key = game_key_from_exe(GAME_EXE)
    print(f"key.fkey {len(key_file) if key_file else 0} 字节；GameKey "
          f"{len(game_key) if game_key else 0} 字节")

    manifest: dict[str, list[dict]] = {}
    total_written = 0

    for pack in packs:
        pack_name = os.path.splitext(os.path.basename(pack))[0]
        with QlieArchive(pack, key_file, game_key) as arc:
            entries = [
                e for e in arc.entries if e.name.lower().endswith(WANTED_EXT)
            ]
            print(f"{pack_name}: 命中 {len(entries)} / {len(arc.entries)} 个条目")
            for e in entries:
                data = arc.read_entry(e)
                rel = e.name.replace("\\", "/").lstrip("/")
                target = os.path.join(OUT_PACKS, pack_name, rel)
                os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
                with open(target, "wb") as f:
                    f.write(data)
                total_written += 1
                manifest.setdefault(rel, []).append(
                    {
                        "pack": pack_name,
                        "offset": e.offset,
                        "stored_size": e.size,
                        "unpacked_size": e.unpacked_size,
                        "packed": bool(e.is_packed),
                        "encrypted": bool(e.encryption_method),
                        "md5": hashlib.md5(data).hexdigest(),
                    }
                )

    # 合并视图：pack 序号大的覆盖小的
    merged_count = 0
    winning: dict[str, str] = {}
    for rel, versions in sorted(manifest.items()):
        versions_sorted = sorted(versions, key=lambda v: pack_sort_key(v["pack"] + ".pack"))
        winner = versions_sorted[-1]
        winning[rel] = winner["pack"]
        src = os.path.join(OUT_PACKS, winner["pack"], rel)
        dst = os.path.join(OUT_MERGED, rel)
        os.makedirs(os.path.dirname(dst) or ".", exist_ok=True)
        with open(src, "rb") as f:
            data = f.read()
        with open(dst, "wb") as f:
            f.write(data)
        merged_count += 1

    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(
            {"files": manifest, "winning_pack": winning},
            f,
            ensure_ascii=False,
            indent=1,
        )

    dup = {k: v for k, v in manifest.items() if len(v) > 1}
    print(f"导出 {total_written} 个文件；合并后 {merged_count} 个；"
          f"其中 {len(dup)} 个文件存在多版本")
    print(f"清单 -> {MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
