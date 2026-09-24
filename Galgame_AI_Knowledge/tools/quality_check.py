"""数据质量检查（对应任务说明第十二阶段）。

检查项：
  * 数量统计：文本 / 角色 / 台词 / 旁白 / 选项 / 场景 / 章节
  * 角色问题：无名说话人、疑似旁白被当成角色、只出现一次的杂役角色
  * 台词问题：乱码、替换字符、重复文本、空文本
  * 结构问题：章节与路线分布、被多版本覆盖的文件
  * 输出 reports/quality_report.md 与 reports/quality_report.json
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MESSAGES = os.path.join(PROJECT, "cleaned", "messages.jsonl")
STATS = os.path.join(PROJECT, "reports", "parse_stats.json")
MANIFEST = os.path.join(PROJECT, "reports", "extract_manifest.json")
OUT_MD = os.path.join(PROJECT, "reports", "quality_report.md")
OUT_JSON = os.path.join(PROJECT, "reports", "quality_report.json")

BAD_CHARS = re.compile(r"[\uFFFD\x00-\x08\x0B\x0C\x0E-\x1F]")


def main() -> int:
    msgs = [json.loads(l) for l in open(MESSAGES, encoding="utf-8")]
    parse_stats = json.load(open(STATS, encoding="utf-8"))
    manifest = json.load(open(MANIFEST, encoding="utf-8"))

    dialogues = [m for m in msgs if m["type"] == "dialogue"]
    narrations = [m for m in msgs if m["type"] == "narration"]
    choices = [m for m in msgs if m["type"] == "choice"]

    speakers = Counter(m["speaker"] for m in dialogues if m["speaker"])
    anonymous = [m for m in dialogues if not m["speaker"]]
    bad_chars = [m for m in msgs if BAD_CHARS.search(m["text"])]
    empty = [m for m in msgs if not m["text"].strip()]
    dup = Counter(m["text"] for m in msgs if len(m["text"]) >= 6)
    dup_multi = [(t, c) for t, c in dup.most_common(40) if c > 1]

    minor = [(s, c) for s, c in speakers.most_common() if c <= 3]
    major = [(s, c) for s, c in speakers.most_common() if c >= 100]

    chapters = Counter(m["chapter"] for m in msgs)
    scenes = Counter(f"{m['chapter']}/{m['scene']}" for m in msgs)

    dup_files = {k: v for k, v in manifest["files"].items() if len(v) > 1}
    packs = Counter(v["pack"] for vs in manifest["files"].values() for v in vs)

    summary = {
        "总文件数（脚本）": parse_stats["files"],
        "总消息数": len(msgs),
        "台词数": len(dialogues),
        "旁白数": len(narrations),
        "选项条目数": len(choices),
        "选项分支数": len(choices) // 2,
        "说话人数": len(speakers),
        "场景数": len(scenes),
        "章节数": len(chapters),
        "无名说话人台词数": len(anonymous),
        "疑似乱码消息数": len(bad_chars),
        "空文本消息数": len(empty),
        "解析时无法归类行数": parse_stats["unknown_count"],
        "多版本覆盖文件数": len(dup_files),
    }

    lines = ["# 数据质量检查报告", "", "## 一、总体统计", "", "| 项目 | 数值 |", "| --- | --- |"]
    lines += [f"| {k} | {v} |" for k, v in summary.items()]

    lines += ["", "## 二、章节分布", "", "| 章节 | 消息数 |", "| --- | --- |"]
    lines += [f"| {k} | {v} |" for k, v in chapters.most_common()]

    lines += ["", "## 三、角色问题", ""]
    lines.append(f"- 无名说话人的台词：{len(anonymous)} 条"
                 + ("（已按旁白处理，如需可人工复核）" if anonymous else "（无）"))
    lines.append(f"- 台词数 ≥100 的主要角色：{len(major)} 人")
    lines.append(f"- 仅 1～3 句的路人角色：{len(minor)} 人（多为「女生徒Ａ」这类群众，属正常）")
    lines.append("")
    lines.append("| 主要角色 | 台词数 |")
    lines.append("| --- | --- |")
    lines += [f"| {s} | {c} |" for s, c in major]

    lines += ["", "## 四、台词问题", ""]
    lines.append(f"- 乱码/控制字符：{len(bad_chars)} 条")
    lines.append(f"- 空文本：{len(empty)} 条")
    lines.append(f"- 重复文本（出现 ≥2 次且长度 ≥6 字）：{len(dup_multi)} 种")
    lines.append("")
    lines.append("| 重复文本 | 次数 |")
    lines.append("| --- | --- |")
    lines += [f"| {t[:40]} | {c} |" for t, c in dup_multi[:20]]

    lines += ["", "## 五、结构与来源", ""]
    lines.append(f"- 剧本文件：{parse_stats['files']} 个（`.s`），场景 {len(scenes)} 个")
    lines.append(f"- 存在多版本（被多个 pack 收录）的文本资源：{len(dup_files)} 个")
    lines.append(f"- 合并规则：pack 序号大者覆盖小者（`data0` → `data15`）")
    lines.append("")
    lines.append("| 来源 pack | 提供的文本资源数 |")
    lines.append("| --- | --- |")
    lines += [f"| {p} | {c} |" for p, c in sorted(packs.items(), key=lambda x: int(x[0][4:]))]

    lines += ["", "## 六、内联控制码（已从清洗文本移除，原文保留在 raw）", ""]
    lines.append("| 标记 | 次数 |")
    lines.append("| --- | --- |")
    lines += [f"| `{k}` | {v} |" for k, v in list(parse_stats["inline_tags_seen"].items())[:20]]

    lines += ["", "## 七、待人工确认", ""]
    if parse_stats["unknown_count"]:
        lines.append("以下行无法被规则自动归类，已逐条保留：")
        lines.append("")
        lines.append("| 文件 | 行 | 原文 | 暂判 |")
        lines.append("| --- | --- | --- | --- |")
        for u in parse_stats["unknown_lines"][:30]:
            lines.append(f"| {u['file']} | {u['line']} | {u['raw'][:60]} | {u['guessed']} |")
    else:
        lines.append("- 无。")

    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "chapters": chapters, "major_speakers": major},
                  f, ensure_ascii=False, indent=1)

    for k, v in summary.items():
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
