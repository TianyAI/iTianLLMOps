"""应用上下文管理器

全局上下文管理器，集成了懒加载和缓存功能
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
        try:
            from itian.core.database.manager import DatabaseContextManager
        except ImportError:
            logger.error("")
        except Exception as e:
            logger.error(f"初始化失败: {e}")

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

        :param context: 上下文管理器注册
        :param dependencies: 上下文所依赖的其他上下文名称列表
        :param initialize_order: 初始化顺序（数字越小，初始化越早）
        :raises: ValueError: 如果上下文名称已存在
        """
        self._registry.register(context)

        # 记录依赖
        if dependencies:
            self._dependencies[context.name] = dependencies

        # 更新初始化顺序
        if initialize_order is not None:
            # 插入到特定位置
            if context.name in self._initialization_order:
                self._initialization_order.remove(context.name)

            insert_pos = 0
            for i, existing_name in enumerate(self._initialization_order):
                existing_context = self._registry.get_context(existing_name)
                if getattr(existing_context, '_initialize_order', float('inf')) > initialize_order:
                    insert_pos = i
                    break
                insert_pos = i + 1
            self._initialization_order.insert(insert_pos, context.name)
            context._initialize_order = initialize_order
        elif context.name not in self._initialization_order:
            # 添加到末尾
            self._initialization_order.append(context.name)

        logger.debug(f"上下文'{context.name}' 注册成功，依赖：{dependencies or []}")

    def unregister_context(self, name: str) -> None:
        """注销一个上下文管理器"""
        self._registry.unregister(name)
        # 删除依赖
        if name in self._dependencies:
            del self._dependencies[name]
        # 删除初始化顺序
        if name in self._initialization_order:
            self._initialization_order.remove(name)
        logger.debug(f"上下文'{name}' 注销成功")

    async def health_check(self, include_details: bool = False) -> Union[Dict[str, bool], Dict[str, Dict[str, Any]]]:
        """检查所有上下文健康状态

        :param include_details: 是否返回详细信息
        :return: 一个字典，键是上下文名称，值是上下文健康状态
        """
        results = await self._registry.health_check()

        if not include_details:
            return results

        # 返回详细信息
        detailed_results = {}
        for name, is_healthy in results.items():
            try:
                context = self._registry.get_context(name)
                detailed_results[name] = {
                    'healthy': is_healthy,
                    'state': context.get_state().value,
                    'error': str(context.get_error()) if context.get_error() else None,
                    'info': context.get_info() if hasattr(context, 'get_info') else {}
                }
            except Exception as e:
                detailed_results[name] = {
                    'healthy': False,
                    'error': f"无法获取到上下文信息：{e}"
                }
        return detailed_results

    async def async_close(self) -> None:
        """关闭应用上下文

        按初始化时的相反顺序关闭所有上下文
        """
        if not self._initialized:
            return
        try:
            # 按初始化相反的顺序关闭所有上下文
            await self._close_contexts_in_reverse_order()

            # 清理状态
            self._initialized = False
            self._initialization_order.clear()
            self._dependencies.clear()
        except Exception as e:
            logger.error(f"关闭应用上下文时出错：{e}")
            raise

    async def _close_contexts_in_reverse_order(self) -> None:
        """反向顺序关闭所有上下文"""
        close_order = list(reversed(self._initialization_order))
        for context_name in close_order:
            try:
                if self._registry.has_context(context_name):
                    context = self._registry.get_context(context_name)
                    await context.async_close()
            except Exception as e:
                logger.error(f"关闭上下文'{context_name}'时出错：{e}")

        # 确保所有上下文都关闭了
        await self._registry.async_close_all()

    def is_initialized(self) -> bool:
        """检查是否初始化"""
        return self._initialized

    def get_registry(self) -> ContextRegistry:
        """
        获取上下文注册表
        :return: 上下文注册表实例
        """
        return self._registry

    def get_context_info(self) -> Dict[str, Any]:
        """
        获取应用上下文详细
        :return: Dict
        """
        return {
            'initialized': self._initialized,
            'context_count': len(self._registry),
            'initialization_order': self._initialization_order.copy(),
            'dependencies': self._dependencies.copy(),
            'context_states': self._registry.get_context_states()
        }

    @contextmanager
    def sync_context(self, *context_names: str):
        """同步上下文管理器以批量获取多个上下文

        :param context_names: 要获取的上下文名称列表
        :return:
        """
        instances = []
        try:
            for name in context_names:
                instance = self.sync_get_instance(name)
                instances.append(instance)

            if len(instances) == 1:
                yield instances[0]
            else:
                yield tuple(instances)
        finally:
            # Note: This does not close automatically as it may be used elsewhere
            pass

    @asynccontextmanager
    async def async_context(self, *context_names: str):
        """用于批量获取多个上下文的异步上下文管理器

        :param context_names: 要获取的上下文名称列表
        :return:
        """
        instances = []
        try:
            for name in context_names:
                instance = await self.async_get_instance(name)
                instances.append(instance)

            if len(instances) == 1:
                yield instances[0]
            else:
                yield tuple(instances)
        finally:
            # Note: This does not close automatically as it may be used elsewhere
            pass

# 全局应用上下文实例
app_context = ApplicationContextManager()


async def initialize_app_context(config: Settings) -> None:
    """
    初始化全局应用上下文
    :param config:
    :return:
    """
    await app_context.initialize(config)

def get_context(name: str) -> BaseContextManager:
    """
    便利方法获取上下文
    :param name: 上下文名称
    :return:
    """
    return app_context.get_context(name)

async def async_get_instance(name: str) -> Any:
    """
    便利方法异步获取上下文实例
    :param name: 上下文名称
    :return:
    """
    return await app_context.async_get_instance(name)

def sync_get_instance(name: str) -> Any:
    """
    便利方法获取上下文实例
    :param name:
    :return:
    """
    return app_context.sync_get_instance(name)

async def close_app_context() -> None:
    """
    关闭全局应用上下文
    :return:
    """
    await app_context.async_close()

def register_context(
        context: BaseContextManager,
        dependencies: Optional[List[str]] = None,
        initialize_order: Optional[int] = None
) -> None:
    """
    便利方式注册一个上下文
    :param context:
    :param dependencies:
    :param initialize_order:
    :return:
    """
    app_context.register_context(context, dependencies, initialize_order)

async def health_check(include_details: bool = False) -> Union[Dict[str, bool], Dict[str, Dict[str, Any]]]:
    """
    检查全局应用上下文的健康状态
    :param include_details:
    :return:
    """
    return await app_context.health_check(include_details)