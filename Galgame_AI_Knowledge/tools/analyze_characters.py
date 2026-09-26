"""从 cleaned/messages.jsonl 聚合人物台词与语言特征。

输出：
  characters/<slug>.json            每个角色的完整台词库 + 统计
  characters/_all_speakers.json     全部说话人索引
  reports/character_stats.json      语言特征统计（口癖、称呼、句尾、常用词）
  knowledge/relationships_data.json 同场共现关系数据
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MESSAGES = os.path.join(PROJECT, "cleaned", "messages.jsonl")
CHARS_DIR = os.path.join(PROJECT, "characters")
KNOWLEDGE = os.path.join(PROJECT, "knowledge")
REPORTS = os.path.join(PROJECT, "reports")

# 目标角色：把同一人物的不同名义合并，但保留子标签便于区分场合
TARGET_GROUPS = {
    "sakuragi_luna": {
        "name": "桜小路ルナ",
        "aliases": ["ルナ", "桜小路ルナ"],
        "labels": ["桜小路ルナ"],
        "notes": ["ルナ"],
    },
    "ookura_yuusei": {
        "name": "大蔵遊星（小倉朝日）",
        "aliases": ["大蔵遊星", "小倉朝日", "朝日"],
        "labels": ["小倉朝日", "大蔵遊星"],
        "notes": ["大蔵遊星", "大蔵朝日"],
    },
    # 2026-09-26 追加：其余主要角色的台词库（供 knowledge/characters/*.md 取证）
    # 说明：只按剧本自带的 speaker 精确值分组；合称行（如「湊＆ユルシュール」）不并入，
    # 以免把两个人的话混进同一份台词库。
    "yurushuuru_furuuru_janmeeru": {
        "name": "ユルシュール・フルール・ジャンメール",
        "aliases": ["ユルシュール", "ユーシェ"],
        "labels": ["ユルシュール"],
        "notes": ["ユルシュール"],
    },
    "hananomiya_mizuho": {
        "name": "花之宮瑞穂",
        "aliases": ["花之宮瑞穂", "瑞穂"],
        "labels": ["花之宮瑞穂"],
        "notes": ["花之宮瑞穂"],
    },
    "yanagase_minato": {
        "name": "柳ヶ瀬湊",
        "aliases": ["柳ヶ瀬湊", "湊"],
        "labels": ["柳ヶ瀬湊"],
        "notes": ["柳ヶ瀬湊"],
    },
    "yamabuki_yachiyo": {
        "name": "山吹八千代",
        "aliases": ["山吹八千代", "八千代"],
        "labels": ["山吹八千代"],
        "notes": ["山吹八千代"],
    },
    "ookura_ion": {
        "name": "大蔵衣遠",
        "aliases": ["大蔵衣遠", "衣遠"],
        "labels": ["大蔵衣遠"],
        "notes": ["大蔵衣遠"],
    },
}

FIRST_PERSON = ["僕", "ぼく", "私", "わたし", "わたくし", "俺", "あたし", "わし"]
SENTENCE_ENDINGS = ["ですわ", "ますわ", "ますのよ", "ですの", "のよ", "わよ", "わね",
                    "かしら", "でしょ", "ですわよ", "ますわよ", "のね", "だわ", "よね",
                    "ですのよ", "ますの", "だもの", "のに", "けど", "ですわね"]


def load_messages():
    with open(MESSAGES, encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def vocative(text: str) -> str | None:
    """粗略识别句首称呼：``ルナ、`` / ``朝日！`` 之类。"""
    m = re.match(r"^[「『]?([^、。！？!?…\s]{1,8})[、！!?？]", text)
    return m.group(1) if m else None


def ngrams(text: str, n: int) -> Counter:
    c = Counter()
    clean = re.sub(r"[「」『』（）()、。！？!?…\s]", "", text)
    for i in range(len(clean) - n + 1):
        c[clean[i : i + n]] += 1
    return c


def main() -> int:
    os.makedirs(CHARS_DIR, exist_ok=True)
    os.makedirs(KNOWLEDGE, exist_ok=True)
    os.makedirs(REPORTS, exist_ok=True)

    msgs = list(load_messages())
    dialogues = [m for m in msgs if m["type"] == "dialogue"]

    speaker_counter = Counter(m["speaker"] for m in dialogues if m["speaker"])
    label_counter = Counter(m["speaker_label"] for m in dialogues if m["speaker_label"])
    with open(os.path.join(CHARS_DIR, "_all_speakers.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "speaker_counts": speaker_counter.most_common(),
                "label_counts": label_counter.most_common(),
                "total_dialogue": len(dialogues),
            },
            f,
            ensure_ascii=False,
            indent=1,
        )

    # 全部角色的 2-gram 背景分布（用于找“该角色特有的说法”）
    global_grams: Counter = Counter()
    for m in dialogues:
        if m["speaker"] not in ("桜小路ルナ", "小倉朝日", "大蔵遊星"):
            global_grams += ngrams(m["text"], 2)
            global_grams += ngrams(m["text"], 3)
    global_total = sum(global_grams.values()) or 1

    stats_out = {}
    for slug, meta in TARGET_GROUPS.items():
        # 按剧本自带的 speaker 精确值分组（合称行如「湊＆ユルシュール」不并入）
        own = [m for m in dialogues if m["speaker"] in meta["labels"]]

        by_label = Counter(m["speaker_label"] for m in own)
        by_chapter = Counter(m["chapter"] for m in own)
        scene_counter = Counter(f"{m['chapter']}/{m['scene']}" for m in own)
        voice_count = sum(1 for m in own if m.get("voice"))
        voice_prefix = Counter((m.get("voice") or "none")[:5] for m in own)

        grams: Counter = Counter()
        endings = Counter()
        first_person = Counter()
        voc = Counter()
        for m in own:
            t = m["text"]
            grams += ngrams(t, 2)
            grams += ngrams(t, 3)
            plain = re.sub(r"[「」『』]", "", t)
            for e in SENTENCE_ENDINGS:
                if plain.endswith(e):
                    endings[e] += 1
            for fp in FIRST_PERSON:
                if fp in plain:
                    first_person[fp] += plain.count(fp)
            v = vocative(t)
            if v:
                voc[v] += 1

        # 特征词：本角色使用率 / 其他角色使用率
        total_grams = sum(grams.values()) or 1
        distinctive = []
        for g, c in grams.items():
            if c < 8:
                continue
            own_rate = c / total_grams
            other_rate = global_grams.get(g, 0) / global_total
            score = own_rate / (other_rate + 1e-9)
            if score > 2.5:
                distinctive.append((g, c, round(score, 1)))
        distinctive.sort(key=lambda x: (-x[2], -x[1]))

        stats_out[slug] = {
            "name": meta["name"],
            "dialogue_count": len(own),
            "by_label": by_label.most_common(),
            "by_chapter": by_chapter.most_common(),
            "scene_count": len(scene_counter),
            "top_scenes": scene_counter.most_common(15),
            "voice_lines": voice_count,
            "voice_prefixes": voice_prefix.most_common(3),
            "avg_length": round(sum(len(m["text"]) for m in own) / max(1, len(own)), 1),
            "max_length": max((len(m["text"]) for m in own), default=0),
            "sentence_endings": endings.most_common(20),
            "first_person": first_person.most_common(),
            "top_vocatives": voc.most_common(25),
            "distinctive_phrases": distinctive[:40],
        }

        # 完整台词库
        with open(os.path.join(CHARS_DIR, f"{slug}.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "name": meta["name"],
                    "aliases": meta["aliases"],
                    "internal_labels": meta["labels"],
                    "dialogue_count": len(own),
                    "scenes": sorted(scene_counter),
                    "dialogues": [
                        {
                            "id": m["id"],
                            "file": m["file"],
                            "source_pack": m["source_pack"],
                            "line": m["line"],
                            "chapter": m["chapter"],
                            "scene": m["scene"],
                            "label": m["speaker_label"],
                            "text": m["text"],
                            "voice": m.get("voice"),
                        }
                        for m in own
                    ],
                },
                f,
                ensure_ascii=False,
                indent=1,
            )

    # 共现关系：同场景内出现过的“目标角色 + 其他说话人”
    scene_speakers: dict[str, set] = defaultdict(set)
    for m in dialogues:
        if m["speaker"]:
            scene_speakers[f"{m['chapter']}/{m['scene']}"].add(m["speaker"])
    relations = {}
    for slug, meta in TARGET_GROUPS.items():
        partner = Counter()
        scenes = 0
        for scene, speakers in scene_speakers.items():
            if any(s in meta["labels"] for s in speakers):
                scenes += 1
                for s in speakers:
                    if s not in meta["labels"]:
                        partner[s] += 1
        relations[slug] = {
            "name": meta["name"],
            "scenes_with_speakers": scenes,
            "co_speakers": partner.most_common(25),
        }
    with open(os.path.join(KNOWLEDGE, "relationships_data.json"), "w", encoding="utf-8") as f:
        json.dump(relations, f, ensure_ascii=False, indent=1)

    with open(os.path.join(REPORTS, "character_stats.json"), "w", encoding="utf-8") as f:
        json.dump(stats_out, f, ensure_ascii=False, indent=1)

    for slug, s in stats_out.items():
        print(f"{s['name']}: 台词 {s['dialogue_count']} 条 / 场景 {s['scene_count']} 个 / "
              f"平均 {s['avg_length']} 字 / 带语音 {s['voice_lines']}")
        print("   子标签:", s["by_label"])
        print("   句尾:", s["sentence_endings"][:8])
        print("   第一人称:", s["first_person"])
        print("   常见称呼:", s["top_vocatives"][:10])
    return 0


if __name__ == "__main__":
    sys.exit(main())
