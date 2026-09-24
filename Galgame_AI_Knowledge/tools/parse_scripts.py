"""把 QLIE/AVG 的 ``*.s`` 剧本解析成结构化数据。

输出：
  raw/script_lines.jsonl      每一行的原始记录（含命令、标签，便于追溯）
  cleaned/messages.jsonl      只保留“可读文本”：台词 / 旁白 / 选项
  reports/parse_stats.json    解析统计（含无法归类的行）

设计原则（对应任务说明 5/12/13 条）：
  * 原始行一个字节都不丢，全部写进 raw/。
  * 清洗只做“去控制码”，不做删除；无法确定的行单独记录，不猜。
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MERGED = os.path.join(PROJECT, "extracted", "merged")
MANIFEST = os.path.join(PROJECT, "reports", "extract_manifest.json")
RAW_OUT = os.path.join(PROJECT, "raw", "script_lines.jsonl")
CLEAN_OUT = os.path.join(PROJECT, "cleaned", "messages.jsonl")
STATS_OUT = os.path.join(PROJECT, "reports", "parse_stats.json")

CP932 = "cp932"

SPEAKER_RE = re.compile(r"^【(.+?)】\s*$")
VOICE_RE = re.compile(r"^％\s*[+＋]?\s*([A-Za-z0-9_]+)\s*$")
COMMAND_RE = re.compile(r"^[\^\\@]")
SELECT_RE = re.compile(r"^\^select,(.+)$")
TITLE_RE = re.compile(r"^『[^』]{1,40}』$")

# 文本内联控制码：清洗时移除，但原文保留在 raw 字段
INLINE_TAGS = re.compile(r"\[(n|nn|no|i|[0-9]{1,2}|c,[^\]]*|s,[^\]]*|f,[^\]]*)\]")
RUBY_TAG = re.compile(r"\[rb,([^,\]]*),([^\]]*)\]")


def decode(path: str) -> str:
    with open(path, "rb") as f:
        return f.read().decode(CP932)


def classify(chapter: str, rel: str) -> str:
    if rel.startswith("scenario"):
        return "scenario"
    if rel.startswith("script") or rel.startswith("avg") or rel.startswith("system"):
        return "system"
    return "other"


def clean_text(text: str) -> str:
    text = RUBY_TAG.sub(lambda m: m.group(1), text)
    text = INLINE_TAGS.sub("", text)
    return text


def speaker_split(label: str) -> tuple[str, str | None]:
    """``スタンレー＠フランス語の声`` -> (``スタンレー``, ``フランス語の声``)。"""
    for sep in ("＠", "@"):
        if sep in label:
            name, _, note = label.partition(sep)
            return name.strip(), note.strip() or None
    return label.strip(), None


def main() -> int:
    with open(MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)
    winning = manifest["winning_pack"]

    os.makedirs(os.path.dirname(RAW_OUT), exist_ok=True)
    os.makedirs(os.path.dirname(CLEAN_OUT), exist_ok=True)

    stats = {
        "files": 0,
        "lines": 0,
        "messages": 0,
        "by_type": Counter(),
        "by_chapter": Counter(),
        "unknown_lines": [],
        "speaker_labels": Counter(),
        "inline_tags_seen": Counter(),
    }

    raw_f = open(RAW_OUT, "w", encoding="utf-8")
    clean_f = open(CLEAN_OUT, "w", encoding="utf-8")

    scene_index: dict[str, list] = defaultdict(list)

    script_files = sorted(
        os.path.join(dp, fn)
        for dp, _dn, fns in os.walk(MERGED)
        for fn in fns
        if fn.lower().endswith(".s")
    )

    seq = 0
    for path in script_files:
        rel = os.path.relpath(path, MERGED).replace(os.sep, "/")
        src_pack = winning.get(rel.replace("/", "\\"), winning.get(rel, "?"))
        parts = rel.split("/")
        chapter = parts[1] if parts[0] == "scenario" and len(parts) > 2 else parts[0]
        scene = os.path.splitext(parts[-1])[0]
        kind = classify(chapter, rel)

        text = decode(path)
        lines = text.split("\r\n") if "\r\n" in text else text.split("\n")
        stats["files"] += 1

        speaker_label: str | None = None
        speaker: str | None = None
        speaker_note: str | None = None
        voice: str | None = None
        last_msg_line: int | None = None

        for i, line in enumerate(lines):
            lineno = i + 1
            stripped = line.strip()
            if not stripped:
                continue
            stats["lines"] += 1

            m = SPEAKER_RE.match(stripped)
            if m:
                speaker_label = m.group(1).strip()
                speaker, speaker_note = speaker_split(speaker_label)
                if kind == "scenario":
                    stats["speaker_labels"][speaker_label] += 1
                rec = {
                    "file": rel,
                    "line": lineno,
                    "type": "speaker_label",
                    "speaker": speaker,
                    "speaker_note": speaker_note,
                    "raw": line,
                }
                raw_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                continue

            m = VOICE_RE.match(stripped)
            if m:
                voice = m.group(1)
                continue

            if COMMAND_RE.match(stripped):
                sel = SELECT_RE.match(stripped)
                rec = {
                    "file": rel,
                    "line": lineno,
                    "type": "choice" if sel else "command",
                    "raw": line,
                }
                if sel:
                    options = [o.strip() for o in sel.group(1).split(",")]
                    rec["options"] = options
                    for opt in options:
                        seq += 1
                        msg = {
                            "id": f"{scene}-{seq:06d}",
                            "file": rel,
                            "source_pack": src_pack,
                            "line": lineno,
                            "chapter": chapter,
                            "scene": scene,
                            "kind": kind,
                            "type": "choice",
                            "speaker": None,
                            "text": clean_text(opt),
                            "voice": None,
                        }
                        clean_f.write(json.dumps(msg, ensure_ascii=False) + "\n")
                        scene_index[f"{chapter}/{scene}"].append(msg)
                        stats["messages"] += 1
                        stats["by_type"]["choice"] += 1
                raw_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                continue

            # 到这里视为正文
            if TITLE_RE.match(stripped) and not speaker:
                mtype = "chapter_title"
            elif line.startswith("（") or line.startswith("“") or line.startswith("("):
                mtype = "narration"
            elif line.startswith("「") or line.startswith("『"):
                mtype = "dialogue"
            elif line.startswith("　") or line.startswith(" "):
                mtype = "narration"
            else:
                mtype = "dialogue" if speaker else "narration"
                stats["unknown_lines"].append(
                    {"file": rel, "line": lineno, "raw": line, "guessed": mtype}
                )

            for tag in re.findall(r"\[[^\]]{1,16}\]", line):
                stats["inline_tags_seen"][tag] += 1

            seq += 1
            msg = {
                "id": f"{scene}-{seq:06d}",
                "file": rel,
                "source_pack": src_pack,
                "line": lineno,
                "chapter": chapter,
                "scene": scene,
                "kind": kind,
                "type": mtype,
                "speaker": speaker if mtype == "dialogue" else None,
                "speaker_label": speaker_label if mtype == "dialogue" else None,
                "speaker_note": speaker_note if mtype == "dialogue" else None,
                "text": clean_text(line).strip(),
                "text_raw": line,
                "voice": voice if mtype == "dialogue" else None,
                "prev": last_msg_line,
            }
            last_msg_line = msg["id"]
            voice = None
            clean_f.write(json.dumps(msg, ensure_ascii=False) + "\n")
            scene_index[f"{chapter}/{scene}"].append(msg)
            stats["messages"] += 1
            stats["by_type"][mtype] += 1
            stats["by_chapter"][chapter] += 1

    raw_f.close()
    clean_f.close()

    stats["inline_tags_seen"] = dict(stats["inline_tags_seen"].most_common())
    stats["unknown_count"] = len(stats["unknown_lines"])
    stats["unknown_lines"] = stats["unknown_lines"][:500]
    stats["by_type"] = dict(stats["by_type"])
    stats["by_chapter"] = dict(stats["by_chapter"])
    stats["speaker_labels"] = dict(stats["speaker_labels"].most_common())
    with open(STATS_OUT, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=1)

    print(f"解析 {stats['files']} 个脚本、{stats['lines']} 行非空行")
    print(f"消息 {stats['messages']} 条 -> {CLEAN_OUT}")
    print("类型分布:", stats["by_type"])
    print("无法自动归类行数:", stats["unknown_count"])
    print("章节分布:", dict(sorted(stats['by_chapter'].items(), key=lambda x: -x[1])[:10]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
