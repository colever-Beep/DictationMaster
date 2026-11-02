"""GitHub 同步端到端联调：用本地 HTTP 服务器模拟 GitHub Contents API。

验证真实链路：教师端 push_task → 仓库 → 教室端 pull_tasks → upsert 到本地
assignments 目录 → build_wordlist_from_assignment 重建词表（无需原词表）。
"""
import base64
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 模拟仓库内容：path -> (content_bytes, sha)
REPO: dict[str, tuple[bytes, str]] = {}
_counter = {"n": 0}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 静音
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = urlparse(self.path)
        parts = p.path.strip("/").split("/")
        # /repos/{owner}/{repo}
        if len(parts) == 3:
            return self._json({"full_name": f"{parts[1]}/{parts[2]}",
                               "default_branch": "main"})
        # /repos/{owner}/{repo}/contents/{path...}
        if len(parts) >= 5 and parts[3] == "contents":
            path = "/".join(parts[4:])
            # 目录：GitHub Contents API 返回数组
            prefix = path + "/"
            children = [p for p in REPO if p.startswith(prefix)]
            if children:
                entries = []
                for cp in sorted(children):
                    content, sha = REPO[cp]
                    entries.append({
                        "name": cp.split("/")[-1],
                        "path": cp,
                        "sha": sha,
                        "size": len(content),
                        "type": "file",
                    })
                return self._json(entries)
            # 单文件：GitHub 返回对象
            if path in REPO:
                content, sha = REPO[path]
                return self._json({
                    "name": path.split("/")[-1],
                    "path": path,
                    "sha": sha,
                    "size": len(content),
                    "content": base64.b64encode(content).decode(),
                })
            return self._json({"message": "Not Found"}, 404)
        return self._json({"message": "Not Found"}, 404)

    def do_PUT(self):
        p = urlparse(self.path)
        parts = p.path.strip("/").split("/")
        path = "/".join(parts[4:])
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode())
        content = base64.b64decode(body["content"])
        _counter["n"] += 1
        sha = f"sha{_counter['n']}"
        REPO[path] = (content, sha)
        return self._json({"commit": {"sha": sha}, "content": {"sha": sha}})

    def do_DELETE(self):
        p = urlparse(self.path)
        parts = p.path.strip("/").split("/")
        path = "/".join(parts[4:])
        # 必须读掉请求体，否则客户端连接会被中止
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length:
            self.rfile.read(length)
        REPO.pop(path, None)
        return self._json({})


def main() -> int:
    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()

    import core.github_sync as gs
    gs.API_ROOT = f"http://127.0.0.1:{port}"

    # 隔离本地 assignments 目录
    import data.assignments_repo as R
    tmp = tempfile.mkdtemp(prefix="e2e_assign_")
    R.ASSIGNMENTS_DIR = __import__("pathlib").Path(tmp)

    teacher = gs.GitHubSync("teacher", "tasks-repo", branch="main", token="t")
    classroom = gs.GitHubSync("teacher", "tasks-repo", branch="main", token="t")

    print("=" * 60)
    print("[1] 教师端测试连接")
    ok, msg = teacher.test_connection()
    print(f"    ok={ok}  msg={msg}")
    assert ok, msg

    print("[2] 教师端上传一份听写任务")
    task = {
        "id": "asg_e2e_001",
        "name": "高一 Unit 1 听写",
        "subject": "english",
        "done": False,
        "created_at": "2026-10-31 09:00:00",
        "words": [
            {"text": "apple", "meaning": "苹果"},
            {"text": "banana", "meaning": "香蕉"},
            {"text": "orange", "meaning": "橙子"},
        ],
    }
    res = teacher.push_task(task)
    print(f"    commit={res['commit']['sha']}  仓库文件数={len(REPO)}")
    assert len(REPO) == 1

    print("[3] 教师端再次上传同一任务（更新，应带 sha）")
    teacher.push_task(task)
    print(f"    仓库文件数仍为 {len(REPO)}（未产生副本）")
    assert len(REPO) == 1

    print("[4] 教室端列目录")
    remote = classroom.list_remote_tasks()
    print(f"    远端任务：{[e['name'] for e in remote]}")
    assert len(remote) == 1

    print("[5] 教室端拉取并导入本地（按 id 去重）")
    pulled = classroom.pull_tasks()
    assert len(pulled) == 1
    assert pulled[0]["id"] == "asg_e2e_001"
    local_ids = {a.id for a in R.list_assignments()}
    added = skipped = 0
    for d in pulled:
        if d.get("id") in local_ids:
            skipped += 1
            continue
        R.upsert_assignment_dict(d)
        added += 1
    print(f"    新增 {added} 个，跳过 {skipped} 个")
    assert added == 1 and skipped == 0

    print("[6] 再次拉取（应全部跳过，幂等）")
    pulled = classroom.pull_tasks()
    local_ids = {a.id for a in R.list_assignments()}
    added = skipped = 0
    for d in pulled:
        if d.get("id") in local_ids:
            skipped += 1
            continue
        R.upsert_assignment_dict(d)
        added += 1
    print(f"    新增 {added} 个，跳过 {skipped} 个")
    assert added == 0 and skipped == 1

    print("[7] 从任务重建词表（无需原词表存在）")
    wl = R.build_wordlist_from_assignment(R.list_assignments()[0])
    print(f"    重建词表：{wl.name}  单词数={len(wl.items)}")
    assert len(wl.items) == 3
    assert [w.text for w in wl.items] == ["apple", "banana", "orange"]

    print("[8] 教师端删除任务")
    teacher.delete_task("asg_e2e_001")
    print(f"    仓库文件数={len(REPO)}")
    assert len(REPO) == 0

    print("=" * 60)
    print("端到端联调全部通过 ✅")
    server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
