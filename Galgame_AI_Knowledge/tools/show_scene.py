"""把一个场景的剧本按“台词 / 旁白”形式打印出来，便于人工阅读与写作。

用法::

    python show_scene.py 本編/l12_03b            # 打印该场景全部正文
    python show_scene.py 本編/l12_03b --mono ルナ  # 只看含“ルナ”相关的行
    python show_scene.py --list                  # 列出所有场景及正文条数
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MESSAGES = os.path.join(PROJECT, "cleaned", "messages.jsonl")


def load():
    return [json.loads(l) for l in open(MESSAGES, encoding="utf-8")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("scene", nargs="?")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--grep")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    msgs = load()
    if args.list:
        counter = Counter(
            f"{m['chapter']}/{m['scene']}" for m in msgs if m.get("kind") == "scenario"
        )
        for scene, n in sorted(counter.items()):
            print(f"{n:>6}  {scene}")
        return 0

    want = args.scene.replace("\\", "/")
    rows = [
        m
        for m in msgs
        if f"{m['chapter']}/{m['scene']}" == want and m["type"] in ("dialogue", "narration", "choice")
    ]
    if args.grep:
        rows = [m for m in rows if args.grep in m["text"]]
    if args.limit:
        rows = rows[: args.limit]
    print(f"### {want}  正文 {len(rows)} 条")
    for m in rows:
        tag = m["speaker"] or ("旁白" if m["type"] == "narration" else "选项")
        print(f"{m['line']:>5} [{tag}] {m['text']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
