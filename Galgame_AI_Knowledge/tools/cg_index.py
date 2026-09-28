"""扫描剧本里的图像调用，建立「图像 ↔ 场景/行号」索引。

剧本（cp932）里图像通过命令引用，例如：
    ^bg01,file:ev_after/LUN31A
    ^bg02,file:ev_after/MIN32A,show:true
    ^ef02,file:ev_after/UFJ38C,scalex:300

本工具把所有 `file:<路径>` 引用连同所在 文件:行号 收集起来，按目录分类
（ev=本编 CG、ev_after=后篇 CG、bg=背景、立ち絵=立绘、face=表情差分、其它），
再用 cleaned/messages.jsonl 把行号映射到 章节 / 场景 / 最近台词，
输出：
    knowledge/images/cg_index.json    机器可读全量索引
    knowledge/images/cg_index.md      人读摘要（CG 明细 + 各分类计数）

用法：python cg_index.py
"""

from __future__ import annotations

import bisect
import json
import os
import re
import sys
from collections import Counter, defaultdict

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MERGED = os.path.join(PROJECT, "extracted", "merged")
MESSAGES = os.path.join(PROJECT, "cleaned", "messages.jsonl")
PACK_INDEX = os.path.join(PROJECT, "reports", "pack_index")
OUT_DIR = os.path.join(PROJECT, "knowledge", "images")

FILE_RE = re.compile(r"file:([^,\r\n]+)")
CMD_RE = re.compile(r"\^([A-Za-z0-9_]+)")


def classify(path: str) -> str:
    p = path.replace("\\", "/").strip().lower()
    if p.startswith("ev_after/"):
        return "CG_after"
    if p.startswith("ev/"):
        return "CG_main"
    if p.startswith("bg"):
        return "background"
    if p.startswith("立ち絵/") or p.startswith("chara"):
        return "sprite"
    if p.startswith("face"):
        return "face"
    if p.startswith("cutin"):
        return "cutin"
    if p.startswith("effect"):
        return "effect"
    if p.startswith("avg/") or p.startswith("script/"):
        return "ui"
    head = p.split("/", 1)[0] if "/" in p else "(无目录)"
    return "other:" + head


def load_scene_map():
    """basename -> (lines[], records[])；records 为 (line, chapter, scene, speaker, text)。

    CG 指令行不在 messages.jsonl 里，因此要按「同文件内离它最近的台词」定位场景。
    """
    per_file = defaultdict(list)
    if not os.path.isfile(MESSAGES):
        return {}
    with open(MESSAGES, encoding="utf-8") as f:
        for raw in f:
            m = json.loads(raw)
            per_file[os.path.basename(m["file"])].append(
                (
                    m["line"],
                    m.get("chapter"),
                    m.get("scene"),
                    m.get("speaker"),
                    (m.get("text") or "")[:60],
                )
            )
    out = {}
    for name, rows in per_file.items():
        rows.sort(key=lambda r: r[0])
        out[name] = ([r[0] for r in rows], rows)
    return out


def nearest(scene_map, fname: str, line: int):
    """取该文件里 line 之后最近的一句台词；没有则取之前最近的。"""
    entry = scene_map.get(os.path.basename(fname))
    if not entry:
        return (None, None, None, None)
    lines, rows = entry
    i = bisect.bisect_left(lines, line)
    row = rows[i] if i < len(rows) else rows[-1]
    return row[1], row[2], row[3], row[4]


def scan():
    refs = []  # dict: category, path, file, line, cmd
    for root, _dirs, files in os.walk(MERGED):
        for name in files:
            if not name.endswith(".s"):
                continue
            full = os.path.join(root, name)
            rel = os.path.relpath(full, MERGED).replace("\\", "/")
            try:
                with open(full, encoding="cp932", errors="replace") as f:
                    for lineno, line in enumerate(f, 1):
                        if "file:" not in line:
                            continue
                        cmd = CMD_RE.search(line)
                        for path in FILE_RE.findall(line):
                            refs.append(
                                {
                                    "category": classify(path),
                                    "path": path,
                                    "file": rel,
                                    "line": lineno,
                                    "cmd": cmd.group(1) if cmd else "",
                                }
                            )
            except OSError as exc:
                print("[跳过] %s : %s" % (full, exc), file=sys.stderr)
    return refs


def pack_inventory():
    """从 pack_index 汇总各分类的条目名（用于对照：哪些图从未被脚本引用）。"""
    inv = defaultdict(set)
    if not os.path.isdir(PACK_INDEX):
        return inv
    for name in sorted(os.listdir(PACK_INDEX)):
        if not name.startswith("data") or not name.endswith(".txt"):
            continue
        with open(os.path.join(PACK_INDEX, name), encoding="utf-8", errors="replace") as f:
            for line in f:
                parts = line.rstrip("\n").split(None, 3)
                if len(parts) < 4:
                    continue
                entry = parts[3]
                low = entry.lower()
                if not low.endswith((".png", ".bmp", ".b", ".dpng", ".abmp", ".argb")):
                    continue
                inv[classify(entry)].add(entry.replace("\\", "/"))
    return inv


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    refs = scan()
    refs.sort(key=lambda r: (r["file"], r["line"]))
    scenes = load_scene_map()

    for r in refs:
        ch, sc, sp, tx = nearest(scenes, r["file"], r["line"])
        r["chapter"], r["scene"], r["near_speaker"], r["near_text"] = ch, sc, sp, tx

    counts = Counter(r["category"] for r in refs)
    by_cg = defaultdict(list)
    for r in refs:
        if r["category"] in ("CG_main", "CG_after"):
            by_cg[r["path"].upper()].append(r)

    idx_json = {
        "_meta": {
            "generated_from": "extracted/merged/**/*.s (cp932) + cleaned/messages.jsonl",
            "category_counts": dict(counts),
            "cg_total_refs": sum(len(v) for v in by_cg.values()),
            "cg_unique": len(by_cg),
        },
        "categories": counts,
        "cg": {
            name: {
                "refs": len(items),
                "first": {
                    "file": items[0]["file"],
                    "line": items[0]["line"],
                    "chapter": items[0]["chapter"],
                    "scene": items[0]["scene"],
                    "near_speaker": items[0]["near_speaker"],
                    "near_text": items[0]["near_text"],
                },
                "places": [
                    {"file": i["file"], "line": i["line"], "scene": i["scene"]} for i in items
                ],
            }
            for name, items in sorted(by_cg.items())
        },
    }
    with open(os.path.join(OUT_DIR, "cg_index.json"), "w", encoding="utf-8") as f:
        json.dump(idx_json, f, ensure_ascii=False, indent=1)

    inv = pack_inventory()

    # 场景 -> CG（供角色扮演配图正查）
    scene_cg = defaultdict(lambda: {"chapter": None, "cgs": set(), "refs": 0})
    for name, items in by_cg.items():
        for i in items:
            sc = i.get("scene")
            if not sc:
                continue
            scene_cg[sc]["chapter"] = i.get("chapter")
            scene_cg[sc]["cgs"].add(name)
            scene_cg[sc]["refs"] += 1
    scene_out = {
        sc: {"chapter": v["chapter"], "refs": v["refs"], "cgs": sorted(v["cgs"])}
        for sc, v in sorted(scene_cg.items())
    }
    with open(os.path.join(OUT_DIR, "scene_cg.json"), "w", encoding="utf-8") as f:
        json.dump(scene_out, f, ensure_ascii=False, indent=1)

    lines = [
        "# 图像索引（CG ↔ 场景）",
        "",
        "> 由 `tools/cg_index.py` 生成：扫描 `extracted/merged/**/*.s` 里的 `file:` 图像调用，",
        "> 用 `cleaned/messages.jsonl` 把行号映射到章节／场景／最近台词。",
        "> 机器可读全量见 `cg_index.json`。",
        "",
        "## 一、各类图像调用次数（脚本引用口径）",
        "",
        "| 分类 | 引用次数 | 说明 |",
        "| --- | --- | --- |",
    ]
    label = {
        "CG_main": "本编事件 CG（`画像\\ev`）",
        "CG_after": "后篇事件 CG（`画像\\ev_after`）",
        "background": "背景（`画像\\bg`）",
        "sprite": "立绘（`立ち絵`）",
        "face": "表情差分（`face`）",
        "cutin": "过场（`画像\\cutin`）",
        "effect": "特效图（`画像\\effect`）",
        "other": "其它",
    }
    for cat, n in counts.most_common():
        lines.append("| %s | %d | %s |" % (cat, n, label.get(cat, "")))

    lines += [
        "",
        "## 二、CG 明细（去重 %d 张，共 %d 次引用）" % (len(by_cg), idx_json["_meta"]["cg_total_refs"]),
        "",
        "| CG | 引用 | 首次出现（章节／场景） | 紧接着的台词 |",
        "| --- | --- | --- | --- |",
    ]
    for name, items in sorted(by_cg.items(), key=lambda kv: -len(kv[1])):
        first = items[0]
        near = "【%s】%s" % (first["near_speaker"], first["near_text"]) if first["near_speaker"] else (first["near_text"] or "—")
        where = "%s / %s" % (first["chapter"] or "?", first["scene"] or "?")
        lines.append("| `%s` | %d | %s（`%s:%d`） | %s |" % (name, len(items), where, first["file"], first["line"], near))

    lines += [
        "",
        "## 三、归档条目对照（哪些图从未被脚本引用）",
        "",
        "| 分类 | 归档条目 | 脚本引用过的名字 | 疑似未被引用 |",
        "| --- | --- | --- | --- |",
    ]
    for cat in ["CG_main", "CG_after", "background", "sprite", "face", "cutin", "effect"]:
        have = inv.get(cat, set())
        used_names = {
            os.path.splitext(os.path.basename(r["path"]))[0].lower()
            for r in refs
            if r["category"] == cat
        }
        have_names = {os.path.splitext(os.path.basename(x))[0].lower() for x in have}
        unused = sorted(have_names - used_names)
        lines.append(
            "| %s | %d | %d | %d |" % (cat, len(have_names), len(have_names & used_names), len(unused))
        )
    lines.append("")
    lines.append("> 「疑似未被引用」多为 UI 素材、多版本覆盖文件，或通过变量拼接路径调用的图；需要时再逐个核。")

    lines += [
        "",
        "## 四、场景 → CG（正查，供角色扮演配图；机器可读见 `scene_cg.json`）",
        "",
        "| 场景 | 章节 | CG |",
        "| --- | --- | --- |",
    ]
    for sc, v in scene_out.items():
        lines.append("| `%s` | %s | %s |" % (sc, v["chapter"] or "?", "、".join("`%s`" % c for c in v["cgs"])))
    with open(os.path.join(OUT_DIR, "cg_index.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print("图像引用总数:", len(refs))
    for cat, n in counts.most_common():
        print("  %-12s %d" % (cat, n))
    print("CG 去重:", len(by_cg), " 含 CG 的场景:", len(scene_out))
    print("输出:", OUT_DIR, "（cg_index.md / cg_index.json / scene_cg.json）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
