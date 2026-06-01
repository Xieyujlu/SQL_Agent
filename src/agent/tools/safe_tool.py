"""工具熔断保护 — 连续失败 N 次后自动短路，避免反复无效重试。"""

import time


class CircuitBreakerMixin:
    """熔断保护 Mixin：连续失败 max_failures 次后，cooldown_seconds 内拒绝执行。"""

    def __init__(self, max_failures: int = 3, cooldown_seconds: int = 30, **kwargs):
        super().__init__(**kwargs)
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._max_failures = max_failures
        self._cooldown = cooldown_seconds

    def _is_open(self) -> bool:
        """熔断器是否打开（拒绝执行）。"""
        if self._failure_count < self._max_failures:
            return False
        if time.time() - self._last_failure_time > self._cooldown:
            self._failure_count = 0
            return False
        return True

    def _record_failure(self):
        self._failure_count += 1
        self._last_failure_time = time.time()

    def _check_circuit(self):
        """电路检查：打开时抛异常让 LangGraph 感知为 tool error，强制终止当前路径。"""
        if self._is_open():
            raise RuntimeError("数据库服务暂不可用（连续多次失败），请告知用户稍后重试。")

    def _record_success(self):
        self._failure_count = 0
