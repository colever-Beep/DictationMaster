"""edge-tts 合成服务：常驻 asyncio 事件循环的 QThread + 磁盘缓存 + 重试 + 并发控制。

设计要点（对应规范 §4.2 / §8.2）：

- **绝不在 Qt 主线程调用 ``asyncio.run()``**；edge-tts 是异步库，所有协程统一提交到
  后台 loop 线程调度，主线程只通过 ``asyncio.run_coroutine_threadsafe`` 投递任务。
- 缓存 key 覆盖 ``text|voice|rate|volume|pitch`` 五个维度；改语速会产生新缓存属预期行为。
- 信号是跨线程安全的投递方式，UI 侧直接 ``connect`` 即可，不要自己起 ``QTimer`` 轮询。
- 断网时缓存里的旧音频仍可播放，这是课堂场景的兜底能力，必须保证。
- 单条合成失败自动重试 3 次（指数退避 1.5s / 3s / 6s），仍失败则经 ``failed`` 信号上报，
  由上层决定是否降级到 ``QtTextToSpeech``（见 ``core/fallback_tts``）。

已知限制（edge-tts 7.2.8）：``Communicate`` 的 ``__init__`` 不含 ``ssml`` 参数，故 **SSML
多音字高级读法暂不支持**；当前别名 ``alias`` 直接作为纯文本报读，已能满足绝大多数多音字场景。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import edge_tts
from PySide6.QtCore import QObject, QThread, Signal

from core.cache import cache_key, cache_path
from core.tts_backend import BaseBackend, make_backend

logger = logging.getLogger(__name__)

# 单次合成重试次数与退避序列（秒）
_MAX_RETRIES = 3
_BACKOFF = (1.5, 3.0, 6.0)


class _LoopThread(QThread):
    """后台线程：常驻一个 asyncio 事件循环，供 edge-tts 协程调度。"""

    def __init__(self, loop: asyncio.AbstractEventLoop, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.loop = loop

    def run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def stop_loop(self) -> None:
        """让常驻 loop 停止（线程安全）。"""
        self.loop.call_soon_threadsafe(self.loop.stop)


class TTSService(QObject):
    """edge-tts 合成服务：带磁盘缓存、重试与并发控制。"""

    # 批量预合成
    prepared = Signal(str, str)   # item_id, mp3_path
    failed = Signal(str, str)     # item_id, error_message
    progress = Signal(int, int)   # done, total

    # 单条合成（测试 / 试听 / 单条报读）
    single_ready = Signal(str, str)   # request_id, mp3_path
    single_failed = Signal(str, str)  # request_id, error_message

    # 引擎切换（edge / kokoro）通知
    engine_changed = Signal(str)

    def __init__(self, cache_dir: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cache_dir = Path(cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._proxy: str | None = None
        # 引擎选择与后端实例（按名懒加载，避免未装 kokoro 时影响启动）
        self._engine = "edge"
        self._backends: dict[str, BaseBackend] = {}
        # 在主线程创建事件循环，交由 worker 线程 run_forever，避免 __init__ 竞态
        self._loop = asyncio.new_event_loop()
        self._thread = _LoopThread(self._loop, self)
        self._thread.start()

    # ---------- 配置 ----------
    def set_proxy(self, proxy: str) -> None:
        """设置网络代理（http / socks5），空串表示直连。"""
        self._proxy = proxy or None

    def set_cache_dir(self, path) -> None:
        """运行期切换缓存目录（§F5 存储：用户可改）。"""
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True)
        self._cache_dir = p

    def cache_dir(self) -> Path:
        """当前缓存目录。"""
        return self._cache_dir

    # ---------- 引擎切换 ----------
    def set_engine(self, name: str) -> None:
        """切换合成引擎：``"edge"``（在线）/ ``"kokoro"``（离线）。"""
        if name not in ("edge", "kokoro"):
            return
        if name == self._engine:
            return
        self._engine = name
        self.engine_changed.emit(name)

    def engine(self) -> str:
        """当前引擎名。"""
        return self._engine

    def _active_backend(self) -> BaseBackend:
        """取得当前引擎对应的后端（懒加载并缓存实例）。"""
        if self._engine not in self._backends:
            self._backends[self._engine] = make_backend(self._engine)
        return self._backends[self._engine]

    # ---------- 对外同步接口（主线程调用） ----------
    def synthesize(self, request_id: str, text: str, voice: str,
                   rate: str, volume: str, pitch: str) -> None:
        """提交单条合成。结果经 ``single_ready`` / ``single_failed`` 返回。

        ``request_id`` 由调用方自定义（如词条 id、试听标记），用于回查。
        """
        asyncio.run_coroutine_threadsafe(
            self._synthesize_one(request_id, text, voice, rate, volume, pitch),
            self._loop,
        )

    def prepare(self, items, voice_of, params, concurrency: int = 4) -> None:
        """提交整表预合成任务。

        ``voice_of(item) -> str`` 决定每条使用的音色（支持男女声混读轮换）。
        ``params`` 需含 ``rate`` / ``volume`` / ``pitch`` 属性。
        结果经 ``prepared`` / ``failed`` / ``progress`` 信号返回。
        """
        asyncio.run_coroutine_threadsafe(
            self._prepare_all(items, voice_of, params, concurrency),
            self._loop,
        )

    # ---------- 协程实现（loop 线程执行） ----------
    async def _prepare_all(self, items, voice_of, params, concurrency: int) -> None:
        from typing import Optional

        total, done = len(items), 0
        sem = asyncio.Semaphore(concurrency)  # 在 loop 内创建，避免 loop 参数被移除的坑

        async def one(item) -> None:
            nonlocal done
            text = getattr(item, "alias", "") or getattr(item, "text", "")
            voice = voice_of(item)
            try:
                path = await self._synthesize(
                    text=text, voice=voice,
                    rate=params.rate, volume=params.volume, pitch=params.pitch,
                )
                self.prepared.emit(item.id, str(path))
            except Exception as exc:  # noqa: BLE001
                self.failed.emit(item.id, str(exc))
            finally:
                done += 1
                self.progress.emit(done, total)

        await asyncio.gather(*(one(i) for i in items))

    async def _synthesize_one(self, request_id: str, text: str, voice: str,
                              rate: str, volume: str, pitch: str) -> None:
        try:
            path = await self._synthesize(text, voice, rate, volume, pitch)
            self.single_ready.emit(request_id, str(path))
        except Exception as exc:  # noqa: BLE001
            self.single_failed.emit(request_id, str(exc))

    async def _synthesize(self, text: str, voice: str, rate: str,
                          volume: str, pitch: str) -> Path:
        key = cache_key(text, voice, rate, volume, pitch, self._engine)
        backend = self._active_backend()
        # 使用本服务持有的缓存目录（支持用户自定义缓存位置，见 §F5）；
        # 后缀随引擎变化（edge->.mp3，kokoro->.wav）
        out = cache_path(key, self._cache_dir, suffix=backend.suffix)
        if out.exists() and out.stat().st_size > 0:
            return out  # 缓存命中，零网络开销

        last: Optional[Exception] = None
        for attempt in range(_MAX_RETRIES):
            try:
                await backend.synth(
                    text=text, voice=voice, rate=rate, volume=volume,
                    pitch=pitch, proxy=self._proxy, out_path=str(out),
                )
                return out
            except Exception as exc:  # noqa: BLE001
                last = exc
                logger.warning("合成失败(第%d次): %s | %s", attempt + 1, text, exc)
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(_BACKOFF[attempt])
        reason = str(last)[:240] if last else "未知错误"
        raise RuntimeError(f"语音合成失败：{text} | {reason}") from last

    # ---------- 生命周期 ----------
    def shutdown(self) -> None:
        """停止后台 loop 线程（应用退出时调用）。"""
        if self._thread.isRunning():
            self._thread.stop_loop()
            self._thread.quit()
            self._thread.wait(3000)
