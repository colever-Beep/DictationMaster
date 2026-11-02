"""M2 手动功能验证脚本（需要联网 + 音频设备/扬声器）。

非 pytest 用例，需手动在已安装依赖的全局 Python 3.14.7 下运行：
    python tests/manual_m2_test.py

它真实合成一段语音、校验缓存文件生成，并验证二次播放命中缓存（秒开）。
离线降级部分会尝试用系统 SAPI 朗读，验证兜底链路可用。
"""

from __future__ import annotations

import asyncio
import sys
import time

sys.path.insert(0, ".")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app_config import init_config, cfg  # noqa: E402
from core.cache import cache_key, cache_path, has  # noqa: E402
from core.services import Services  # noqa: E402


def _wait(cond, timeout: float = 30.0) -> bool:
    """轮询等待条件成立（避免 time.sleep 阻塞且不可中断的写法）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def main() -> int:
    app = QApplication(sys.argv)
    init_config()

    services = Services()
    services.apply_config(cfg)

    params = __import__("data.models", fromlist=["SpeakParams"]).SpeakParams()
    text = "床前明月光，疑是地上霜。"
    voice = "zh-CN-XiaoxiaoNeural"

    ready: dict[str, str] = {}

    def on_ready(req_id: str, path: str) -> None:
        ready[req_id] = path

    def on_failed(req_id: str, err: str) -> None:
        ready[req_id] = f"FAIL:{err}"

    services.tts.single_ready.connect(on_ready)
    services.tts.single_failed.connect(on_failed)

    # 第一次：应联网合成
    key1 = cache_key(text, voice, params.rate, params.volume, params.pitch)
    cached_before = has(key1)
    services.tts.synthesize("first", text, voice, params.rate, params.volume, params.pitch)
    ok = _wait(lambda: "first" in ready, 40.0)
    print(f"[1] 合成前缓存命中={cached_before}  结果={ready.get('first')}")
    assert ok and not ready["first"].startswith("FAIL"), "首次合成失败"

    path1 = ready["first"]
    services.player.play_file(path1)
    print("[1] 已触发播放（请听扬声器）。")
    time.sleep(2.0)  # 仅用于人工确认声音，非逻辑依赖

    # 第二次：应命中缓存（秒开，无网络开销）
    ready.clear()
    t0 = time.monotonic()
    services.tts.synthesize("second", text, voice, params.rate, params.volume, params.pitch)
    ok2 = _wait(lambda: "second" in ready, 10.0)
    dt = time.monotonic() - t0
    print(f"[2] 二次合成耗时={dt:.3f}s  缓存命中={has(key1)}  结果={ready.get('second')}")
    assert ok2, "二次合成未完成"
    assert has(key1), "缓存未落盘"

    # 离线降级：用系统 SAPI 朗读
    print("[3] 尝试离线试听（系统 SAPI）...")
    if services.fallback.is_available():
        services.fallback.say(text, "chinese")
        time.sleep(2.0)
        print("[3] 离线试听已触发。")
    else:
        print("[3] 本机无可用离线引擎（SAPI），跳过。")

    services.shutdown()
    print("\nM2 语音层验证通过：合成 / 缓存命中 / 离线降级链路均可用。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
