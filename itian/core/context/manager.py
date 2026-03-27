"""应用上下文管理器

全局上下文管理器，集成了延迟加载和缓存功能
提供便捷的依赖注入和生命周期管理
"""
import asyncio
from contextlib import asynccontextmanager, contextmanager
from typing import Optional, Dict, Any, TypeVar, List, Union

from loguru import logger

from itian.core.config.settings import Settings
from itian.core.context.base import (
    ContextRegistry,
    BaseContextManager,
    ContextState,
    ContextError
)

T = TypeVar("T")


class ApplicationContextManager:
    """应用上下文管理器

    负责管理整个应用基础设施服务的生命周期，
    并提供统一的访问接口 支持依赖注入、批量操作和健康检查
    """

    def __init__(self):
        self._registry = ContextRegistry()
        self._initialized = False
        self._initialization_lock = asyncio.Lock()
        self._initialization_order: List[str] = []
        self._dependencies: Dict[str, List[str]] = {}

    async def initialize(self, config: Settings) -> None:
        """初始化应用上下文

        :param config: 用于传递给单个上下文管理器的可选配置字典
        :return: 初始化失败时抛出
        """
        async with self._initialization_lock:
            if self._initialized:
                logger.debug("应用已经初始化了")
                return

            try:
                # 注册默认的上下文管理器
                self._register_default_contexts(config or {})

                # 按依赖顺序初始化所有上下文
            except ContextError as e:
                logger.error(f"初始化失败: {e}")
                raise

    def _register_default_contexts(self, config: Settings) -> None:
        """初始化默认上下文管理器"""
        pass

    async def _initialize_context_in_order(self) -> None:
        """按依赖顺序初始化"""
        if not self._initialization_order:
            self._initialization_order = list(self._registry.get_all_contexts().keys())

        initialized = set()

        for context_name in self._initialization_order:
            if context_name not in initialized:
                await self._initialize_context_with_dependencies(context_name, initialized)

    async def _initialize_context_with_dependencies(self, context_name: str, initialized: set) -> None:
        """递归初始化上下文及其依赖项"""
        if context_name in initialized:
            return

        # 初始化依赖
        dependencies = self._dependencies.get(context_name, [])
        for dep_name in dependencies:
            if dep_name not in initialized:
                await self._initialize_context_with_dependencies(dep_name, initialized)

        # 初始化当前上下文
        try:
            context = self._registry.get_context(context_name)
            await context.async_get_instance() # 会触发初始化
            initialized.add(context_name)
            logger.debug(f"初始化成功: {context_name}")
        except Exception as e:
            logger.error(f"初始化失败: {context_name}: {e}")
            raise

    async def async_get_instance(self, name: str) -> T:
        """获取异步上下文实例

        :param name: 上下文名称
        :returns: 上下文实例
        :raise KeyError 如果上下文资源不存在
        """
        context = self.get_context(name)
        return await context.async_get_instance()

    def sync_get_instance(self, name: str) -> T:
        """获取同步上下文实例

        :param name: 上下文名称
        :returns: 上下文实例
        :raise KeyError 如果上下文资源不存在
        """
        context = self.get_context(name)
        return context.sync_get_instance()

    def get_context(self, name: str) -> BaseContextManager:
        """获取上下文管理器实例"""
        return self._registry.get_context(name)

    def register_context(
            self,
            context: BaseContextManager,
            dependencies: Optional[List[str]] = None,
            initialize_order: Optional[int] = None
    ) -> None:
        """注册一个新的上下文管理器

        :param context:
        :param dependencies:
        :param initialize_order:
        :raises:
        """