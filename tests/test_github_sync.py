"""GitHub 同步内核与仓库辅助的单元测试（mock 掉网络，不真实访问 GitHub）。"""
import base64
import json
from unittest.mock import patch

import pytest

from core.github_sync import GitHubSync, GitHubSyncError, make_github_sync
from data.assignments_repo import (
    assignment_from_dict,
    import_assignment_dict,
    list_assignments,
    upsert_assignment_dict,
)


# --------------------------------------------------------------------------- mock
class _Resp:
    """模拟 urllib 的响应对象（支持 with 上下文管理器）。"""

    def __init__(self, data: bytes) -> None:
        self._d = data

    def read(self) -> bytes:
        return self._d

    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, *exc) -> bool:
        return False


def _make_task(id_: str, name: str) -> dict:
    return {"id": id_, "name": name, "words": [{"id": "1", "text": "x"}],
            "config": {}, "done": False}


def _fake_urlopen(task_a: dict, task_b: dict):
    """根据请求 URL / 方法返回不同假数据。"""

    def handler(req, *args, **kwargs):
        url = req.full_url
        method = req.method
        if url.endswith("/repos/owner/repo") and method == "GET":
            return _Resp(json.dumps({"full_name": "owner/repo"}).encode())
        if method == "GET" and "/contents/tasks/" in url:
            # 拉取单个任务文件（URL 形如 .../contents/tasks/a.json?ref=main）
            which = task_a if "a.json" in url else task_b
            b64 = base64.b64encode(json.dumps(which).encode()).decode()
            return _Resp(json.dumps({"content": b64, "sha": "s1"}).encode())
        if "/contents/tasks" in url and "ref=" in url and method == "GET":
            # 列出 tasks/ 目录
            entries = [
                {"name": "a.json", "path": "tasks/a.json", "sha": "s1", "size": 10},
                {"name": "b.json", "path": "tasks/b.json", "sha": "s2", "size": 10},
                {"name": "readme.md", "path": "tasks/readme.md", "sha": "s9", "size": 3},
            ]
            return _Resp(json.dumps(entries).encode())
        if method == "PUT":
            return _Resp(json.dumps({"commit": {"sha": "new"}}).encode())
        if method == "DELETE":
            return _Resp(b"{}")
        raise AssertionError(f"unexpected request {method} {url}")

    return handler


@pytest.fixture
def sync():
    return GitHubSync(owner="owner", repo="repo", branch="main",
                     token="tok", path="tasks")


# --------------------------------------------------------------------------- 内核
def test_test_connection_ok(sync):
    with patch("urllib.request.urlopen", _fake_urlopen(_make_task("a", "A"),
                                                       _make_task("b", "B"))):
        ok, msg = sync.test_connection()
    assert ok is True
    assert "owner/repo" in msg


def test_list_remote_tasks_filters_json(sync):
    with patch("urllib.request.urlopen", _fake_urlopen(_make_task("a", "A"),
                                                       _make_task("b", "B"))):
        tasks = sync.list_remote_tasks()
    names = {t["name"] for t in tasks}
    assert names == {"a.json", "b.json"}  # readme.md 被过滤
    assert all(t["sha"] for t in tasks)


def test_fetch_task_decodes_base64(sync):
    with patch("urllib.request.urlopen", _fake_urlopen(_make_task("a", "任务A"),
                                                       _make_task("b", "B"))):
        data = sync.fetch_task({"path": "tasks/a.json"})
    assert data["name"] == "任务A"
    assert data["id"] == "a"


def test_push_task_returns_commit(sync):
    with patch("urllib.request.urlopen", _fake_urlopen(_make_task("a", "A"),
                                                       _make_task("b", "B"))):
        result = sync.push_task(_make_task("a", "A"))
    assert result["commit"]["sha"] == "new"
    assert result["skipped"] is False


def test_push_task_skips_when_overwrite_disabled(sync):
    """关闭「覆盖同名任务」：远端已存在同 ID 时直接跳过，不发 PUT。"""
    with patch("urllib.request.urlopen", _fake_urlopen(_make_task("a", "A"),
                                                       _make_task("b", "B"))):
        result = sync.push_task(_make_task("a", "A"), overwrite=False)
    assert result["skipped"] is True
    assert result["id"] == "a"


def test_ensure_folder_returns_exists_when_readme_present(sync):
    with patch("urllib.request.urlopen", _fake_urlopen(_make_task("a", "A"),
                                                       _make_task("b", "B"))):
        assert sync.ensure_folder() == "exists"


def test_ensure_folder_creates_when_missing(sync):
    """目录不存在（README 404）时用 PUT 写入占位说明，使仓库出现任务文件夹。"""
    import urllib.error

    calls: list[str] = []

    def handler(req, *args, **kwargs):
        calls.append(req.method)
        if req.method == "GET":
            raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)
        return _Resp(b"{}")

    with patch("urllib.request.urlopen", handler):
        assert sync.ensure_folder() == "created"
    assert calls == ["GET", "PUT"]


def test_upload_default_config_items_exist():
    from app_config import cfg

    assert hasattr(cfg, "github_auto_upload")
    assert hasattr(cfg, "github_upload_overwrite")
    # 默认：不自动上传、覆盖同名任务
    assert cfg.github_auto_upload.value in (True, False)
    assert cfg.github_upload_overwrite.value is True


def test_pull_tasks_returns_dicts(sync):
    with patch("urllib.request.urlopen", _fake_urlopen(_make_task("a", "A"),
                                                       _make_task("b", "B"))):
        pulled = sync.pull_tasks()
    assert len(pulled) == 2
    assert {d["id"] for d in pulled} == {"a", "b"}


def test_list_remote_tasks_empty_when_404(sync):
    def not_found(req, *args, **kwargs):
        import urllib.error
        raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)

    with patch("urllib.request.urlopen", not_found):
        assert sync.list_remote_tasks() == []


# --------------------------------------------------------------------------- 配置
def test_make_github_sync_none_without_owner_repo():
    stub = _stub_cfg(owner="", repo="")
    with patch("app_config.cfg", stub):
        assert make_github_sync() is None


def test_make_github_sync_builds_when_configured():
    stub = _stub_cfg(owner="o", repo="r", branch="dev", token="t", path="tasks")
    with patch("app_config.cfg", stub):
        s = make_github_sync()
    assert isinstance(s, GitHubSync)
    assert s.owner == "o" and s.repo == "r" and s.branch == "dev"


def test_make_github_sync_none_when_disabled():
    """关闭「启用 GitHub 同步」开关后，即使填了仓库也不应构造客户端。"""
    stub = _stub_cfg(owner="o", repo="r", enabled=False)
    with patch("app_config.cfg", stub):
        assert make_github_sync() is None


class _Item:
    def __init__(self, v):
        self.value = v


def _stub_cfg(owner, repo, branch="main", token="", path="tasks", enabled=True):
    class _Cfg:
        pass
    c = _Cfg()
    c.github_enabled = _Item(enabled)
    c.github_owner = _Item(owner)
    c.github_repo = _Item(repo)
    c.github_branch = _Item(branch)
    c.github_token = _Item(token)
    c.github_tasks_path = _Item(path)
    return c


# --------------------------------------------------------------------------- 仓库辅助
def test_upsert_keeps_id(tmp_path, monkeypatch):
    monkeypatch.setattr("data.assignments_repo.ASSIGNMENTS_DIR", tmp_path)
    d = _make_task("remote-1", "远程任务")
    upsert_assignment_dict(d)
    # 文件应直接用原始 id 命名
    assert (tmp_path / "remote-1.json").exists()
    # 再次 upsert 不应新增副本（按 id 去重的关键）
    upsert_assignment_dict(d)
    assert len(list(tmp_path.glob("*.json"))) == 1
    loaded = list_assignments()
    assert loaded[0].id == "remote-1"


def test_import_assignment_dict_regenerates_id(tmp_path, monkeypatch):
    monkeypatch.setattr("data.assignments_repo.ASSIGNMENTS_DIR", tmp_path)
    d = _make_task("orig-id", "导入任务")
    a = import_assignment_dict(d)
    assert a.id != "orig-id"            # 本地导入重新生成 id
    assert a.done is False
    assert (tmp_path / f"{a.id}.json").exists()


def test_roundtrip_assignment_dict():
    d = _make_task("x", "往返")
    a = assignment_from_dict(d)
    # 通过 repo 的序列化函数验证字段完整
    from data.assignments_repo import assignment_to_dict
    back = assignment_to_dict(a)
    assert back["id"] == "x"
    assert back["name"] == "往返"
    assert back["words"][0]["text"] == "x"


# --------------------------------------------------------------------------- 分支一致性
def test_push_task_uses_ref_on_sha_lookup():
    """更新已存在文件时，取 sha 的请求必须带 ref，否则 sha 来自默认分支会导致 409。"""
    seen: list[str] = []

    def handler(req, *args, **kwargs):
        url = req.full_url
        seen.append(url)
        if req.method == "GET":
            return _Resp(json.dumps({"sha": "oldsha"}).encode())
        if req.method == "PUT":
            return _Resp(json.dumps({"commit": {"sha": "new"}}).encode())
        raise AssertionError(f"unexpected {req.method} {url}")

    s = GitHubSync(owner="o", repo="r", branch="dev", token="t")
    with patch("urllib.request.urlopen", handler):
        s.push_task(_make_task("a", "A"))

    get_urls = [u for u in seen if u.endswith(".json?ref=dev") or "ref=dev" in u]
    assert get_urls, f"取 sha 的请求缺少 ref 参数：{seen}"


def test_push_task_propagates_auth_error():
    """401/403 等非 404 错误必须抛出，不能被当成「文件不存在」而静默创建。"""
    def unauthorized(req, *args, **kwargs):
        import urllib.error
        raise urllib.error.HTTPError(req.full_url, 401, "unauthorized", {}, None)

    s = GitHubSync(owner="o", repo="r", branch="main", token="bad")
    with patch("urllib.request.urlopen", unauthorized):
        with pytest.raises(GitHubSyncError):
            s.push_task(_make_task("a", "A"))


def test_socket_error_becomes_github_sync_error():
    """socket 层异常应被转换为 GitHubSyncError，避免 UI 收到裸 traceback。"""
    def aborted(req, *args, **kwargs):
        raise ConnectionAbortedError("连接被中止")

    s = GitHubSync(owner="o", repo="r", branch="main", token="t")
    with patch("urllib.request.urlopen", aborted):
        # list_remote_tasks 会向上抛（test_connection 则转为 (False, msg) 返回）
        with pytest.raises(GitHubSyncError) as exc:
            s.list_remote_tasks()
    assert "网络错误" in str(exc.value)

    # test_connection 应优雅返回失败而不是抛出
    with patch("urllib.request.urlopen", aborted):
        ok, msg = s.test_connection()
    assert ok is False and "网络错误" in msg


# --------------------------------------------------------------------------- worker 生命周期
def test_worker_attach_and_shutdown(app):
    """worker 应登记到宿主并在 shutdown 后停止，避免 QThread 被提前回收。"""
    from ui.widgets.github_worker import GitHubTaskWorker

    class Host:
        pass

    host = Host()
    worker = GitHubTaskWorker(lambda: 42)
    worker.attach(host)
    assert getattr(host, "_gh_workers") == [worker]

    worker.start()
    worker.wait(3000)
    assert not worker.isRunning()
    worker.shutdown()
    assert not worker.is_busy()


def test_worker_reports_exception(app):
    """worker 内部异常应转为 (False, 错误文本) 而不是抛出到 Qt 事件循环。"""
    from ui.widgets.github_worker import GitHubTaskWorker

    def boom():
        raise ValueError("炸了")

    worker = GitHubTaskWorker(boom)
    result = {}
    worker.done.connect(lambda ok, payload: result.update(ok=ok, payload=payload))
    worker.start()
    worker.wait(3000)
    # 跨线程信号需主线程泵事件
    for _ in range(50):
        app.processEvents()
        if result:
            break
    assert result.get("ok") is False
    assert "炸了" in result.get("payload", "")


def test_dialog_shutdown_workers_waits(app):
    """对话框关闭时（走 done()）应等待后台线程结束。"""
    from ui.dialogs.assignment_dialog import AssignmentManageDialog
    from ui.widgets.github_worker import GitHubTaskWorker

    dlg = AssignmentManageDialog(parent=None)
    worker = GitHubTaskWorker(lambda: 1)
    worker.attach(dlg)
    worker.start()
    dlg.done(0)
    assert not worker.isRunning()


# --------------------------------------------------------------------------- UI 接线（offscreen）
def test_ui_wiring_builds(app):
    """设置页（含 GitHub 分组）与管理对话框（含同步按钮）应能无错构建。"""
    from ui.pages.setting_page import SettingPage
    from ui.dialogs.assignment_dialog import AssignmentManageDialog

    sp = SettingPage(services=None)
    assert hasattr(sp, "_github_busy")          # GitHub 分组已构建

    dlg = AssignmentManageDialog(parent=None)
    # 同步按钮通过 _add_sync_buttons 加入；至少有一拉一推两个
    from qfluentwidgets import PushButton
    labels = [b.text() for b in dlg.findChildren(PushButton) if b.text()]
    assert "从 GitHub 拉取" in labels
    assert "上传全部到 GitHub" in labels


def test_setting_page_has_github_switch(app):
    """设置页应提供「启用 GitHub 同步」开关，且绑定到 github_enabled 配置项。"""
    from qfluentwidgets import SwitchSettingCard
    from ui.pages.setting_page import SettingPage

    sp = SettingPage(services=None)
    switches = sp.findChildren(SwitchSettingCard)
    assert switches, "未找到启用开关"
    # 找到绑定 github_enabled 的那个
    bound = [s for s in switches if getattr(s, "configItem", None) is not None]
    assert bound, "开关未绑定配置项"
    names = {getattr(s.configItem, "name", "") for s in bound}
    assert "github_enabled" in names
