"""GitHub 同步后台 worker：在子线程执行同步函数，避免阻塞 UI。

调用方传入一个无参可调用对象（如 ``lambda: sync.push_task(d)``），
worker 在子线程运行它，完成时通过 ``done`` 信号返回：
- ``done(True, result)``：成功，携带被调函数的返回值；
- ``done(False, error_message)``：失败，携带异常的可读描述。

生命周期约定（重要）：
``QThread`` 若在运行中被 Python GC 回收，Qt 会报
``QThread: Destroyed while thread is still running`` 并可能崩溃。
因此调用方必须持有 worker 引用 —— 本类通过 ``attach()`` 把自己登记到宿主
（对话框 / 页面）上，由宿主的 ``closeEvent`` 负责在销毁前 ``wait()``。
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QThread, Signal


class GitHubTaskWorker(QThread):
    """在子线程执行一个同步函数并回报结果。"""

    done = Signal(bool, object)  # (ok, result_or_error_message)

    def __init__(self, fn: Callable[[], object], parent: object | None = None) -> None:
        super().__init__(parent)
        self._fn = fn
        self._finished_flag = False

    def run(self) -> None:  # noqa: D401
        try:
            result = self._fn()
            self.done.emit(True, result)
        except Exception as exc:  # noqa: BLE001  统一把异常转成可读字符串
            self.done.emit(False, f"{type(exc).__name__}: {exc}")
        finally:
            self._finished_flag = True

    # ------------------------------------------------------------------ 生命周期
    def is_busy(self) -> bool:
        """线程是否仍在运行中。"""
        return not self._finished_flag or self.isRunning()

    def attach(self, host: object) -> "GitHubTaskWorker":
        """把自身登记到宿主对象上，避免被 GC 回收。

        宿主（对话框 / 页面）应在其 ``closeEvent`` 中调用 ``shutdown()``。
        """
        existing = getattr(host, "_gh_workers", None)
        if existing is None:
            existing = []
            setattr(host, "_gh_workers", existing)
        existing.append(self)
        return self

    def shutdown(self, timeout_ms: int = 3000) -> None:
        """等待线程结束（宿主销毁前调用）。"""
        if self.isRunning():
            self.wait(timeout_ms)
