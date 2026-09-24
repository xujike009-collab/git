"""人物语言特征与场景定位分析。

输出 reports/insights.json，并在终端打印摘要：
  * 目标角色在各场景的台词量（用于定位关键剧情）
  * 高频重复台词（口癖 / 招牌台词）
  * 句尾表达统计
  * 称呼（对谁怎么叫）
  * 第一人称用法（按子标签区分）
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MESSAGES = os.path.join(PROJECT, "cleaned", "messages.jsonl")
OUT = os.path.join(PROJECT, "reports", "insights.json")

LUNA_LABELS = {"桜小路ルナ"}
YUUSEI_LABELS = {"小倉朝日", "大蔵遊星"}

KNOWN_NAMES = [
    "朝日", "遊星", "ルナ", "湊", "ユルシュール", "瑞穂", "衣遠", "りそな",
    "八千代", "七愛", "北斗", "サーシャ", "スタンレー", "メイ", "紅葉",
    "多摩子", "明日菜", "壱与", "キャロル", "メリル",
]

FIRST_PERSON = ["僕", "ぼく", "私", "わたし", "わたくし", "俺", "あたし"]
PUNCT = "」。、！？!?…〜～♪☆★w "


def trailing(text: str, n: int) -> str:
    t = re.sub(r"[「」『』]", "", text).rstrip(PUNCT)
    return t[-n:] if len(t) >= n else ""


def main() -> int:
    msgs = [json.loads(l) for l in open(MESSAGES, encoding="utf-8")]
    dialogues = [m for m in msgs if m["type"] == "dialogue"]
    narration = [m for m in msgs if m["type"] == "narration"]
    choices = [m for m in msgs if m["type"] == "choice"]

    out: dict = {}

    for slug, labels, name in (
        ("luna", LUNA_LABELS, "桜小路ルナ"),
        ("yuusei", YUUSEI_LABELS, "大蔵遊星／小倉朝日"),
    ):
        own = [m for m in dialogues if m["speaker"] in labels]
        per_scene = Counter((m["chapter"], m["scene"]) for m in own)

        line_counter = Counter(m["text"] for m in own if len(m["text"]) >= 4)
        ending2 = Counter(trailing(m["text"], 2) for m in own)
        ending3 = Counter(trailing(m["text"], 3) for m in own)
        ending4 = Counter(trailing(m["text"], 4) for m in own)

        # 称呼统计：句首“名字＋标点”，或句中“名字＋助词”
        voc = Counter()
        for m in own:
            t = m["text"]
            for nm in KNOWN_NAMES:
                for pat in (nm + "、", nm + "！", nm + "。", nm + "って", nm + "は",
                            nm + "に", nm + "の", nm + "さん", nm + "ちゃん", nm + "様"):
                    c = t.count(pat)
                    if c:
                        voc[pat] += c

        fp_by_label: dict[str, Counter] = defaultdict(Counter)
        for m in own:
            lbl = m.get("speaker_label") or m["speaker"]
            for fp in FIRST_PERSON:
                c = m["text"].count(fp)
                if c:
                    fp_by_label[lbl][fp] += c

        # 叙述里提到对方：旁白中出现的名字次数
        narr_mentions = Counter()
        for m in narration:
            for nm in KNOWN_NAMES:
                c = m["text"].count(nm)
                if c:
                    narr_mentions[nm] += c

        out[slug] = {
            "name": name,
            "dialogue_count": len(own),
            "per_scene": {f"{c}/{s}": n for (c, s), n in per_scene.most_common()},
            "top_lines": line_counter.most_common(50),
            "ending2": ending2.most_common(30),
            "ending3": ending3.most_common(30),
            "ending4": ending4.most_common(30),
            "vocatives": voc.most_common(40),
            "first_person_by_label": {k: v.most_common() for k, v in fp_by_label.items()},
            "narration_mentions": narr_mentions.most_common(20),
        }

    out["_meta"] = {
        "total_messages": len(msgs),
        "dialogue": len(dialogues),
        "narration": len(narration),
        "choice": len(choices),
        "choices": [f"{m['file']}:{m['line']} {m['text']}" for m in choices],
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    for slug in ("luna", "yuusei"):
        d = out[slug]
        print(f"===== {d['name']}  {d['dialogue_count']} 条台词 =====")
        print("台词最多的场景:")
        for scene, n in list(d["per_scene"].items())[:15]:
            print(f"    {scene:<28} {n}")
        print("高频台词(≥4字, 前 20):")
        for t, n in d["top_lines"][:20]:
            print(f"    {n:>4}  {t[:40]}")
        print("句尾 2 字:", d["ending2"][:12])
        print("句尾 3 字:", d["ending3"][:12])
        print("称呼:", d["vocatives"][:12])
        print("第一人称:", d["first_person_by_label"])
        print()
    print("选项总数:", out["_meta"]["choice"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
