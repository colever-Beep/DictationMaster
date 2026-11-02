"""GitHub 同步服务：把「听写任务」推送到私有仓库 / 从仓库拉取。

采用 GitHub REST **Contents API**（无需本机安装 git，适合打包后的 exe）：
- 教师端：把一份布置任务（自包含 JSON）``PUT`` 到仓库的 ``tasks/`` 目录；
- 教室端：``GET tasks/`` 目录列表 + 逐个拉取 JSON，导入为本地待听写任务。

认证：Personal Access Token（需 ``repo`` 权限），配置在设置页。私有仓库两端都需填 token。
无 git 依赖、无第三方库（仅用标准库 ``urllib`` + ``base64`` + ``json``）。
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from typing import Any, Optional

API_ROOT = "https://api.github.com"

# 任务目录的占位说明：GitHub 无法提交空目录，故在首次「初始化仓库目录」时
# 写入这份说明文件，使仓库里真正出现一个可见的「用户数据文件夹」。
FOLDER_README = """# 听写任务（用户数据）

本目录由「听写助手」的 GitHub 同步功能读写，存放教师布置的听写任务。

- 文件名：`{task_id}.json`，内容为自包含 JSON（词表快照 + 报读参数 + 截止日期）。
- 教师端：「布置听写」→「上传到 GitHub」写入这里；
- 教室端：「管理布置」→「从 GitHub 拉取」按 ID 去重导入本地。

> 请勿手工改动文件结构；如需清空，直接删除对应 `.json` 即可。
"""


class GitHubSyncError(Exception):
    """GitHub 同步相关错误，``message`` 已是人类可读文本。"""


class GitHubSync:
    """围绕某个仓库 ``tasks/`` 目录的听写任务读写客户端。"""

    def __init__(self, owner: str, repo: str, branch: str = "main",
                 token: str = "", path: str = "tasks") -> None:
        self.owner = owner
        self.repo = repo
        self.branch = branch or "main"
        self.path = (path or "tasks").strip("/") or "tasks"
        self._token = token
        self._headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "DictationMaster/0.6",
        }
        if token:
            self._headers["Authorization"] = f"Bearer {token}"

    # ---------------------------------------------------------------- 底层
    def _url(self, *parts: str) -> str:
        return "/".join([API_ROOT, "repos", self.owner, self.repo, *parts])

    def _call(self, method: str, url: str,
              data: Optional[bytes] = None) -> Any:
        req = urllib.request.Request(url, data=data, method=method)
        for key, value in self._headers.items():
            req.add_header(key, value)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:  # 4xx / 5xx
            detail = exc.read().decode("utf-8", "replace")
            try:
                msg = json.loads(detail).get("message", detail)
            except Exception:
                msg = detail or str(exc.reason)
            raise GitHubSyncError(f"HTTP {exc.code}: {msg}") from exc
        except urllib.error.URLError as exc:  # DNS / 网络不可达
            raise GitHubSyncError(f"网络错误：{exc.reason}") from exc
        except OSError as exc:
            # socket 层异常（ConnectionAborted / ConnectionReset / timeout 等）不会被
            # urllib 包装成 URLError，需单独捕获，否则 UI 会收到裸 traceback
            raise GitHubSyncError(f"网络错误：{exc}") from exc

    # ---------------------------------------------------------------- 高层
    @staticmethod
    def _is_not_found(exc: GitHubSyncError) -> bool:
        """判断错误是否为「资源不存在」（GitHub 对不存在的文件/目录返回 404）。"""
        text = str(exc)
        return "404" in text or "Not Found" in text

    def test_connection(self) -> tuple[bool, str]:
        """验证仓库可访问且 token 有权限；返回 (是否成功, 说明文字)。"""
        try:
            info = self._call("GET", self._url())
            return True, f"仓库可访问：{info.get('full_name', self.repo)}"
        except GitHubSyncError as exc:
            return False, str(exc)

    def list_remote_tasks(self) -> list[dict]:
        """返回 ``tasks/`` 目录下所有 ``.json`` 文件的元数据 [{{name,path,sha,size}}]。"""
        url = self._url("contents", self.path) + f"?ref={self.branch}"
        try:
            entries = self._call("GET", url)
        except GitHubSyncError as exc:
            # 目录尚不存在（仓库刚建、还没有任何任务）=> 视为空
            if self._is_not_found(exc):
                return []
            raise
        if not isinstance(entries, list):
            return []
        return [{"name": e["name"], "path": e["path"], "sha": e["sha"],
                 "size": e.get("size", 0)}
                for e in entries if e.get("name", "").endswith(".json")]

    def fetch_task(self, entry: dict) -> dict:
        """拉取单个任务文件内容（base64 解码）为 dict。"""
        url = self._url("contents", entry["path"]) + f"?ref={self.branch}"
        data = self._call("GET", url)
        content = base64.b64decode(data["content"]).decode("utf-8")
        return json.loads(content)

    def push_task(self, task_dict: dict, overwrite: bool = True) -> dict:
        """把一份任务 ``PUT`` 到 ``tasks/{id}.json``（已存在则更新）。

        ``overwrite=False`` 时，若远端已存在同 ID 文件则**跳过不覆盖**，
        返回 ``{"skipped": True, "id": ...}``（用于「保留教室端已有内容」的策略）。
        """
        filename = f"{task_dict['id']}.json"
        url = self._url("contents", self.path, filename)
        sha = None
        try:
            # 必须带 ref：否则 sha 取自默认分支，与目标分支不一致会导致 409 冲突
            existing = self._call("GET", url + f"?ref={self.branch}")
            sha = existing.get("sha")
        except GitHubSyncError as exc:
            # 仅「文件不存在」才走创建分支；其它错误（401/403/网络）应直接抛出
            if not self._is_not_found(exc):
                raise
            sha = None
        if sha and not overwrite:
            return {"skipped": True, "id": task_dict.get("id"), "name": filename}
        payload = json.dumps(task_dict, ensure_ascii=False, indent=2).encode("utf-8")
        content = base64.b64encode(payload).decode("ascii")
        body = {"message": f"add/update task {filename}",
                "content": content, "branch": self.branch}
        if sha:
            body["sha"] = sha  # 更新需带上原文件 sha
        result = self._call("PUT", url, json.dumps(body).encode("utf-8"))
        if isinstance(result, dict):
            result.setdefault("skipped", False)
        return result

    def ensure_folder(self) -> str:
        """确保仓库内存在任务目录（写入占位 README），返回 ``created`` / ``exists``。"""
        url = self._url("contents", self.path, "README.md")
        try:
            self._call("GET", url + f"?ref={self.branch}")
            return "exists"
        except GitHubSyncError as exc:
            if not self._is_not_found(exc):
                raise
        payload = FOLDER_README.format(task_id="asg-xxxxxxxx").encode("utf-8")
        content = base64.b64encode(payload).decode("ascii")
        body = {"message": f"init task folder {self.path}/",
                "content": content, "branch": self.branch}
        self._call("PUT", url, json.dumps(body).encode("utf-8"))
        return "created"

    def delete_task(self, task_id: str) -> None:
        """从仓库删除某个任务文件。"""
        filename = f"{task_id}.json"
        url = self._url("contents", self.path, filename)
        try:
            existing = self._call("GET", url + f"?ref={self.branch}")
            sha = existing.get("sha")
        except GitHubSyncError as exc:
            if not self._is_not_found(exc):
                raise
            return
        if not sha:
            return
        body = {"message": f"delete task {filename}",
                "sha": sha, "branch": self.branch}
        self._call("DELETE", url, json.dumps(body).encode("utf-8"))

    def pull_tasks(self) -> list[dict]:
        """拉取全部远程任务内容，返回 dict 列表（单个失败则跳过）。"""
        out: list[dict] = []
        for entry in self.list_remote_tasks():
            try:
                out.append(self.fetch_task(entry))
            except GitHubSyncError:
                continue
        return out


def make_github_sync() -> Optional[GitHubSync]:
    """从全局配置构造一个同步客户端。

    未启用（``github_enabled`` 为 False）或未填 owner/repo 时返回 ``None``，
    调用方据此提示用户去「设置 → GitHub 同步」配置。
    """
    from app_config import cfg  # 延迟导入，避免循环依赖

    if not cfg.github_enabled.value:
        return None
    if not (cfg.github_owner.value and cfg.github_repo.value):
        return None
    return GitHubSync(
        owner=cfg.github_owner.value,
        repo=cfg.github_repo.value,
        branch=cfg.github_branch.value or "main",
        token=cfg.github_token.value or "",
        path=cfg.github_tasks_path.value or "tasks",
    )
