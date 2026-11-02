"""内置资源首次种入的单元测试（seed_textbooks / seed_wordlists）。

用临时目录替换用户目录与随包资源根，验证：
- 首次启动复制缺失文件；
- 已存在同名文件不覆盖（保护用户修改）；
- 词表只种一次，删除后重启不复活。
"""

from __future__ import annotations

import json

import data.repository as repo


def _make_bundle(root, sub: str, names: list[str]) -> None:
    d = root / "data" / sub
    d.mkdir(parents=True)
    for n in names:
        (d / n).write_text(
            json.dumps({"id": n[:-5], "name": n, "subject": "english", "items": []},
                       ensure_ascii=False),
            encoding="utf-8")


def test_seed_wordlists_copies_once_and_respects_deletions(tmp_path, monkeypatch):
    root = tmp_path / "root"
    appdata = tmp_path / "appdata"
    target = appdata / "wordlists"
    target.mkdir(parents=True)
    _make_bundle(root, "bundled_wordlists", ["a.json", "b.json"])

    monkeypatch.setattr(repo, "_bundled_root", lambda: root)
    monkeypatch.setattr(repo, "APP_DATA", appdata)
    monkeypatch.setattr(repo, "WORDLISTS_DIR", target)

    # 首次：复制 2 个
    assert repo.seed_wordlists() == 2
    assert {p.name for p in target.glob("*.json")} == {"a.json", "b.json"}

    # 第二次：标记已存在，不再复制
    assert repo.seed_wordlists() == 0

    # 用户删除内置词表后，重启不应「复活」
    (target / "a.json").unlink()
    assert repo.seed_wordlists() == 0
    assert not (target / "a.json").exists()


def test_seed_wordlists_does_not_overwrite_user_file(tmp_path, monkeypatch):
    root = tmp_path / "root"
    appdata = tmp_path / "appdata"
    target = appdata / "wordlists"
    target.mkdir(parents=True)
    _make_bundle(root, "bundled_wordlists", ["a.json", "b.json"])
    # 用户已有一个同名文件（自定义内容）
    (target / "a.json").write_text("USER-CONTENT", encoding="utf-8")

    monkeypatch.setattr(repo, "_bundled_root", lambda: root)
    monkeypatch.setattr(repo, "APP_DATA", appdata)
    monkeypatch.setattr(repo, "WORDLISTS_DIR", target)

    assert repo.seed_wordlists() == 1          # 只补 b.json
    assert (target / "a.json").read_text(encoding="utf-8") == "USER-CONTENT"
    assert (target / "b.json").exists()


def test_seed_textbooks_uses_bundled_root(tmp_path, monkeypatch):
    root = tmp_path / "root"
    target = tmp_path / "textbooks"
    target.mkdir()
    _make_bundle(root, "textbooks", ["c.json"])

    monkeypatch.setattr(repo, "_bundled_root", lambda: root)
    monkeypatch.setattr(repo, "TEXTBOOKS_DIR", target)

    assert repo.seed_textbooks() == 1
    assert (target / "c.json").exists()
    # 已存在则不重复复制
    assert repo.seed_textbooks() == 0


def test_bundled_root_source_mode():
    # 源码运行时应指向项目根（含 data/repository.py 的上一级目录）
    root = repo._bundled_root()
    assert (root / "data" / "repository.py").exists()
