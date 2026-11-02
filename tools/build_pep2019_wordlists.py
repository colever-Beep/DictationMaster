"""整理人教版高中英语（2019）词汇，输出为听写助手可用的词库文件。

数据源：GitHub cyforkk/pep-english-words（来自人教版 2019 教材官方词表）。
已下载的原始 JSON 位于 assets/wordlists/pep2019/pep2019-*.json。

产出（均落在 assets/wordlists/pep2019/）：
  - pep2019_highschool.json   总库（册→单元→单词[en,zh,phonetic]）
  - wordlists/*.json          每单元一个 App 原生词表（subject=english, lang=en, note=中文义）
  - units_txt/*.txt           每单元英文单词（一行一词，供导入对话框使用）
  - pep2019_all.csv           全部单词参考表（book,unit,en,zh,phonetic）
  - high_freq.json / .txt     跨册高频词排行（按出现册数 + 词频）

用法：python tools/build_pep2019_wordlists.py
"""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "assets" / "wordlists" / "pep2019"
OUT = SRC

# 册 id -> (短码, 中文名)
BOOKS = {
    "pep2019-compulsory-1": ("c1", "必修第一册"),
    "pep2019-compulsory-2": ("c2", "必修第二册"),
    "pep2019-compulsory-3": ("c3", "必修第三册"),
    "pep2019-optional-1":   ("o1", "选择性必修第一册"),
    "pep2019-optional-2":   ("o2", "选择性必修第二册"),
    "pep2019-optional-3":   ("o3", "选择性必修第三册"),
    "pep2019-optional-4":   ("o4", "选择性必修第四册"),
}

STAMP = datetime(2026, 10, 5, 0, 0, 0).strftime("%Y-%m-%dT%H:%M:%S")

# 载入原始数据
raw: dict[str, dict] = {}
for bid in BOOKS:
    raw[bid] = json.loads((SRC / f"{bid}.json").read_text(encoding="utf-8"))

# --------------------------------------------------------------------------
# 1) 总库 JSON
# --------------------------------------------------------------------------
master = {
    "title": "人教版高中英语（2019）词汇总库",
    "edition": "2019 新课标",
    "source": "cyforkk/pep-english-words（人教版 2019 教材官方词表）",
    "books": [],
}
for bid, (code, title) in BOOKS.items():
    d = raw[bid]
    master["books"].append({
        "id": bid,
        "code": code,
        "title": d.get("title", title),
        "units": [
            {
                "id": u.get("id", ""),
                "title": u.get("title", ""),
                "words": [
                    {"en": w.get("en", "").strip(),
                     "zh": w.get("zh", ""),
                     "phonetic": w.get("phonetic", "")}
                    for w in u.get("words", [])
                ],
            }
            for u in d.get("units", [])
        ],
    })
(OUT / "pep2019_highschool.json").write_text(
    json.dumps(master, ensure_ascii=False, indent=2), encoding="utf-8")

# --------------------------------------------------------------------------
# 2) App 原生词表 JSON（每单元一个，可直接放入 %LOCALAPPDATA%/DictationMaster/wordlists/）
# --------------------------------------------------------------------------
wl_dir = OUT / "wordlists"
wl_dir.mkdir(exist_ok=True)
for bid, (code, title) in BOOKS.items():
    for ui, u in enumerate(raw[bid]["units"], 1):
        items = []
        for w in u.get("words", []):
            en = w.get("en", "").strip()
            if not en:
                continue
            items.append({
                "id": f"it_{code}_u{ui}_{len(items) + 1}",
                "text": en,
                "alias": "",          # 英文单词按英文朗读，alias 留空
                "lang": "en",
                "enabled": True,
                "repeat": None,
                "interval": None,
                "note": w.get("zh", ""),  # 中文释义进 note（不被朗读）
            })
        if not items:
            continue
        wl = {
            "schema": 1,
            "id": f"pep_{code}_u{ui}",
            "name": f"人教版{title} · {u.get('title', '')}",
            "subject": "english",
            "builtin": True,
            "grade": "高中",
            "created_at": STAMP,
            "updated_at": STAMP,
            "items": items,
        }
        (wl_dir / f"{wl['id']}.json").write_text(
            json.dumps(wl, ensure_ascii=False, indent=2), encoding="utf-8")

# --------------------------------------------------------------------------
# 3) 导入用 .txt（每单元英文单词一行一词）
# --------------------------------------------------------------------------
txt_dir = OUT / "units_txt"
txt_dir.mkdir(exist_ok=True)
for bid, (code, title) in BOOKS.items():
    for ui, u in enumerate(raw[bid]["units"], 1):
        lines = [w.get("en", "").strip() for w in u.get("words", [])
                 if w.get("en", "").strip()]
        safe = re.sub(r'[\\/:*?"<>|\s]+', "_", u.get("title", ""))
        (txt_dir / f"pep_{code}_u{ui:02d}_{safe}.txt").write_text(
            "\n".join(lines), encoding="utf-8-sig")

# --------------------------------------------------------------------------
# 4) 全部单词参考 CSV（book,unit,en,zh,phonetic）
# --------------------------------------------------------------------------
with (OUT / "pep2019_all.csv").open("w", encoding="utf-8-sig", newline="") as f:
    wr = csv.writer(f)
    wr.writerow(["book", "unit", "en", "zh", "phonetic"])
    for bid, (code, title) in BOOKS.items():
        for u in raw[bid]["units"]:
            for w in u.get("words", []):
                wr.writerow([title, u.get("title", ""),
                             w.get("en", ""), w.get("zh", ""),
                             w.get("phonetic", "")])

# --------------------------------------------------------------------------
# 5) 教材复现核心词（按「出现单元数」排序：跨单元复现 = 课标核心词）
#    教材词表按主题编排，跨册重复少；真正的高频信号是「跨单元复现」。
# --------------------------------------------------------------------------
freq: dict[str, dict] = defaultdict(
    lambda: {"books": set(), "units": set(), "count": 0, "zh": ""})
for bid, (code, title) in BOOKS.items():
    for ui, u in enumerate(raw[bid]["units"], 1):
        seen_in_unit: set[str] = set()
        for w in u.get("words", []):
            en = w.get("en", "").strip()
            if not en:
                continue
            key = en.lower()
            freq[key]["books"].add(bid)
            freq[key]["count"] += 1
            if not freq[key]["zh"]:
                freq[key]["zh"] = w.get("zh", "")
            if key not in seen_in_unit:
                seen_in_unit.add(key)
                freq[key]["units"].add((bid, ui))

ranked = sorted(freq.items(),
                key=lambda kv: (-len(kv[1]["units"]), -len(kv[1]["books"]),
                                -kv[1]["count"], kv[0]))
hf = [{"en": k, "units": len(v["units"]), "books": len(v["books"]),
       "occurrences": v["count"], "zh": v["zh"]}
      for k, v in ranked]
(OUT / "high_freq.json").write_text(
    json.dumps(hf, ensure_ascii=False, indent=2), encoding="utf-8")
(OUT / "high_freq.txt").write_text(
    "# 教材复现核心词（人教版高中英语2019）\n"
    "# 排序：跨单元复现次数(n) → 跨册数(b) → 总出现次数(c) → 字母序\n"
    "# 说明：教材词表按主题编排，跨册重复本就少；此处仅标记「在多个单元复现」的词，\n"
    "#       作为教材内部核心参考。真正的「高考高频词」需考试语料词频，本数据集不含。\n"
    + "\n".join(f"{i+1}. {k}  (n={len(v['units'])} b={len(v['books'])} c={v['count']})"
                for i, (k, v) in enumerate(ranked)),
    encoding="utf-8-sig")

# --------------------------------------------------------------------------
# 统计
# --------------------------------------------------------------------------
n_units = sum(len(raw[bid]["units"]) for bid in BOOKS)
n_entries = sum(len(u.get("words", [])) for bid in BOOKS
                for u in raw[bid]["units"])
print(f"册数={len(BOOKS)}  单元数={n_units}  单词词条数={n_entries}  "
      f"去重单词(小写)={len(freq)}")
print(f"词表 JSON 文件数={len(list(wl_dir.glob('*.json')))}")
print(f".txt 文件数={len(list(txt_dir.glob('*.txt')))}")
print("高频 Top10：")
for k, v in ranked[:10]:
    print(f"  {k}  ({len(v['books'])}册/{v['count']}次)")
print("完成 ->", OUT)
