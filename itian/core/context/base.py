import asyncio
import time
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager, contextmanager
from enum import Enum
from threading import Lock, Event
from typing import Any, Dict, Optional, TypeVar, Generic, Callable, Awaitable, Union

from loguru import logger

T = TypeVar("T")

class ContextState(Enum):
    """ 上下文状态枚举 """
    UNINITIALIZED = "uninitialized" # 未初始化
    INITIALIZING = "initializing" # 初始化中
    READY = "ready" # 准备就绪
    ERROR = "error" # 错误
    CLOSING = "closing" # 关闭中
    CLOSED = "closed"

class ContextError(Exception):
    """Context-dependent exception base class"""
    pass


class ContextInitializationError(ContextError):
    """Context initialization exception"""
    pass


class ContextTimeoutError(ContextError):
    """Context operation timeout exception"""
    pass


class ContextStateError(ContextError):
    """Context status exception"""
    pass

class BaseContextManager(ABC, Generic[T]):
    """
    底层管理器抽象类
    定义了所有上下文管理器必须实现的接口 提供线程安全的懒加载、缓存和生命周期管理
    """

    name: str
    _default_timeout: float = 30.0 # 默认超时时间
    _default_retry_count: int = 3 # 默认重试次数

    def __init__(self, name: str = None, timeout: float = None, retry_count: int = None, **kwargs):
        self.name = name or getattr(self.__class__, 'name', self.__class__.__name__.lower())
        self.timeout = timeout or self._default_timeout
        self.retry_count = retry_count or self._default_retry_count

        self.state = ContextState.UNINITIALIZED
        self._instance: Optional[T] = None
        self._error: Optional[Exception] = None

        # 同步锁和异步锁
        self._sync_lock = Lock()
        self._async_lock = asyncio.Lock()

        # 同步等待事件
        self._sync_ready_event = Event()
        self._async_ready_event = asyncio.Event()

    @abstractmethod
    async def _async_initialize(self) -> T:
        """ 异步初始化方法 """
        pass

    @abstractmethod
    def _sync_initialize(self) -> T:
        """ 同步初始化方法 """
        pass

    @abstractmethod
    async def _async_cleanup(self) -> None:
        """ 异步清理方法 """
        pass

    @abstractmethod
    def _sync_cleanup(self) -> None:
        """ 同步清理方法 """
        pass

    def _validate_state_for_access(self) -> None:
        """ 验证状态是否可以访问这个实例 """
        if self.state == ContextState.ERROR:
            error_msg = f"上下文 '{self.name}' 处在错误状态，无法访问实例"
            if self._error:
                error_msg += f": {self._error}"
            raise ContextStateError(error_msg)

        if self.state == ContextState.CLOSED:
            raise ContextStateError(f"上下文 '{self.name}' 已经关闭，无法连接实例")

    async def _wait_for_initialization_async(self) -> None:
        """ 异步等待初始化完成 """
        try:
            await asyncio.wait_for(self._async_ready_event.wait(), timeout=self.timeout)
        except:
            raise ContextTimeoutError(f"经过 {self.timeout}后,等待初始化 '{self.name}' 超时")

    def _wait_for_initialization_sync(self) -> None:
        """ 同步等待初始化完成 """
        if not self._sync_ready_event.wait(timeout=self.timeout):
            raise ContextTimeoutError(f"经过 {self.timeout}后,等待初始化 '{self.name}' 超时")

    async def async_get_instance(self) -> T:
        """异步获取上下文实例
        :return
            T：初始化后的上下文实例
        :raise
            ContextStateError：上下文处于错误状态或已关闭
            ContextTimeoutError：初始化超时
            ContextInitializationError：初始化失败
        """
        # 快速路径：实例预备
        if self.state == ContextState.READY and self._instance is not None:
            return self._instance

        self._validate_state_for_access()

        async with self._async_lock:
            # 双锁检查模式
            if self.state == ContextState.READY and self._instance is not None:
                return self._instance

            # 如果正在初始化，等待初始化完成
            if self.state == ContextState.INITIALIZING:
                await self._wait_for_initialization_async()
                self._validate_state_for_access()
                if self.state == ContextState.READY and self._instance is not None:
                    return self._instance

            # 开始初始化
            return await self._perform_initialization_async()

    async def _perform_initialization_async(self) -> T:
        """ 异步执行初始化逻辑 """
        self.state = ContextState.INITIALIZING
        self._async_ready_event.clear()

        last_error = None
        for attempt in range(self.retry_count):
            try:
                logger.debug(f"正在初始化上下文 '{self.name}'")
                self._instance = await self._async_initialize()
                self.state = ContextState.READY
                self._async_ready_event.set()
                self._sync_ready_event.set()
                logger.debug(f"初始化 '{self.name}' 完成")
                return self._instance
            except Exception as e:
                last_error = e
                if attempt < self.retry_count - 1:
                    wait_time = 2 ** attempt
                    logger.warning(f"初始化 '{self.name}' 失败，正在重试... (尝试次数: {attempt + 1}/{self.retry_count}, 等待时间: {wait_time}秒)")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"初始化 '{self.name}' 失败 (尝试次数: {self.retry_count}): {e}")

        # 所有尝试都失败了
        self.state = ContextState.ERROR
        self._error = last_error
        self._async_ready_event.set()
        self._sync_ready_event.set()
        raise ContextInitializationError(f"初始化 '{self.name}' 失败: {last_error}") from last_error

    def sync_get_instance(self) -> T:
        """同步获取上下文实例
        :return
            T：初始化后的上下文实例
        :raise
            ContextStateError：上下文处于错误状态或已关闭
            ContextInitializationError：初始化失败
        """
        # 快速路径：实例预备
        if self.state == ContextState.READY and self._instance is not None:
            return self._instance

        self._validate_state_for_access()

        with self._sync_lock:
            # 双锁检查模式
            if self.state == ContextState.READY and self._instance is not None:
                return self._instance

            # 如果正在初始化，等待初始化完成
            if self.state == ContextState.INITIALIZING:
                self._wait_for_initialization_sync()
                self._validate_state_for_access()
                if self.state == ContextState.READY and self._instance is not None:
                    return self._instance

            # 开始初始化
            return self._perform_initialization_sync()

    def _perform_initialization_sync(self) -> T:
        """ 同步执行初始化逻辑 """
        self.state = ContextState.INITIALIZING
        self._sync_ready_event.clear()
        self._async_ready_event.clear()

        last_error = None
        for attempt in range(self.retry_count):
            try:
                logger.debug(f"正在初始化上下文 '{self.name}'")
                self._instance = self._sync_initialize()
                self.state = ContextState.READY
                self._sync_ready_event.set()
                self._async_ready_event.set()
                logger.debug(f"初始化 '{self.name}' 完成")
                return self._instance
            except Exception as e:
                last_error = e
                if attempt < self.retry_count - 1:
                    wait_time = 2 ** attempt  # 指数退避
                    logger.warning(f"初始化 '{self.name}' 失败，正在重试... (尝试次数: {attempt + 1}/{self.retry_count}, 等待时间: {wait_time}秒)")
                    time.sleep(wait_time)
                else:
                    logger.error(f"初始化 '{self.name}' 失败 (尝试次数: {self.retry_count}): {e}")

        # All retries failed
        self.state = ContextState.ERROR
        self._error = last_error
        self._sync_ready_event.set()  # Failed to notify waiter
        self._async_ready_event.set()
        raise ContextInitializationError(
            f"Failed to initialize context '{self.name}': {last_error}") from last_error

    async def async_close(self) -> None:
        """ 异步关闭上下文实例 """
        if self.state in [ContextState.CLOSING, ContextState.CLOSED]:
            return

        async with self._async_lock:
            if self.state in [ContextState.CLOSING, ContextState.CLOSED]:
                return

            self.state = ContextState.CLOSING

            try:
                if self._instance is not None:
                    logger.debug(f"正在关闭上下文 '{self.name}'")
                    await self._async_cleanup()
                    self._instance = None
                    logger.debug(f"关闭 '{self.name}' 完成")
            except Exception as e:
                logger.error(f"关闭 '{self.name}' 失败: {e}")
            # 即使清理失败，也要标记为已关闭以避免资源泄漏
            finally:
                self.state = ContextState.CLOSED
                self._error = None
                # 确保事件设置能够防止等待器出现无限等待时间
                self._async_ready_event.set()
                self._sync_ready_event.set()

    def sync_close(self) -> None:
        """ 同步关闭上下文实例 """
        if self.state in [ContextState.CLOSING, ContextState.CLOSED]:
            return

        with self._sync_lock:
            if self.state in [ContextState.CLOSING, ContextState.CLOSED]:
                return

            self.state = ContextState.CLOSING

            try:
                if self._instance is not None:
                    logger.debug(f"正在关闭上下文 '{self.name}'")
                    self._sync_cleanup()
                    self._instance = None
                    logger.debug(f"关闭 '{self.name}' 完成")
            except Exception as e:
                logger.error(f"关闭 '{self.name}' 失败: {e}")
            # 即使清理失败，也要标记为已关闭以避免资源泄漏
            finally:
                self.state = ContextState.CLOSED
                self._error = None
                # 确保事件设置能够防止等待器出现无限等待时间
                self._async_ready_event.set()
                self._sync_ready_event.set()

    async def async_reset(self) -> None:
        """重置上下文管理器

        关闭当前实例并将其重置为未初始化状态，下次访问时将重新初始化
        """
        await self.async_close()
        async with self._async_lock:
            self.state = ContextState.UNINITIALIZED
            self._error = None
            self._async_ready_event.clear()
            self._sync_ready_event.clear()

    def sync_reset(self) -> None:
        """重置上下文管理器

        关闭当前实例并将其重置为未初始化状态，下次访问时将重新初始化
        """
        self.sync_close()
        with self._sync_lock:
            self.state = ContextState.UNINITIALIZED
            self._error = None
            self._async_ready_event.clear()
            self._sync_ready_event.clear()

    def is_ready(self) -> bool:
        """检查一下是否准备好了

        :return:
            bool类型: 如果上下文已初始化且可用，则为True；否则为False，
        """
        return self.state == ContextState.READY and self._instance is not None

    def get_state(self) -> ContextState:
        """获取当前状态

        :return:
            ContextState: 当前上下文状态
        """
        return self.state

    def get_error(self) -> Optional[Exception]:
        """获取最后的错误信息

        :return:
            Optional[Exception]: 若处于错误状态，则返回错误信息，否则返回None
        """
        return self._error

    def get_info(self) -> Dict[str, Any]:
        """获取上下文信息

        :return:
            Dict[str, Any]：包含上下文详细信息的字典
        """
        return {
            'name': self.name,
            'state': self.state.value,
            'is_ready': self.is_ready(),
            'timeout': self.timeout,
            'retry_count': self.retry_count,
            'error': str(self._error) if self._error else None,
            'has_instance': self._instance is not None
        }

    @contextmanager
    def sync_context(self):
        """同步上下文管理器

        与Statements一起使用，可自动获取和释放资源

        示例：使用 `my_context.sync_context()` 函数作为实例：
            # 使用实例
            pass
        """
        instance = self.sync_get_instance()
        try:
            yield instance
        finally:
            # 注意：由于该文档可能在其他地方使用，因此不会自动关闭
            pass

    @asynccontextmanager
    async def async_context(self):
        """异步上下文管理器

        使用带有async的语句可以自动获取并释放资源

        示例：使用 `my_context.async_context()` 函数获取一个实例，然后使用该实例进行操作:
        # 使用实例
            pass
        """
        instance = await self.async_get_instance()
        try:
            yield instance
        finally:
            # 注意：由于该文档可能在其他地方使用，因此不会自动关闭
            pass

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name='{self.name}', state='{self.state.value}')>"


class FunctionContextManager(BaseContextManager[T]):
    """基于函数的上下文管理器

    允许通过函数定义初始化和清理逻辑
    """

    def __init__(
            self,
            name: str,
            init_func: Union[Callable[[], Awaitable[T]], Callable[[], T]],
            cleanup_func: Optional[Union[Callable[[T], Awaitable[None]], Callable[[T], None]]] = None,
            **kwargs
    ):
        super().__init__(name, **kwargs)
        self.init_func = init_func
        self.cleanup_func = cleanup_func
        self._is_async = asyncio.iscoroutinefunction(init_func)

    async def _async_initialize(self) -> T:
        """使用初始化汉纳树来初始化实例"""
        if not self._is_async:
            # 如果初始化函数不是异步大的，则在线程池中执行
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self.init_func)
        return await self.init_func()

    def _sync_initialize(self) -> T:
        """同步初始化"""
        if self._is_async:
            raise TypeError(f"无法调用异步初始化函数 '{self.init_func.__name__}' 在同步上下文中")
        return self.init_func()

    async def _async_cleanup(self) -> None:
        """使用cleanup()函数来清理实例"""
        if self.cleanup_func and self._instance:
            if asyncio.iscoroutinefunction(self.cleanup_func):
                await self.cleanup_func(self._instance)
            else:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self.cleanup_func, self._instance)

    def _sync_cleanup(self) -> None:
        """同步清理"""
        if self.cleanup_func and self._instance:
            if asyncio.iscoroutinefunction(self.cleanup_func):
                raise TypeError(f"无法调用异步清理函数 '{self.cleanup_func.__name__}' 在同步上下文中")
            self.cleanup_func(self._instance)


class ContextRegistry:
    """上下文注册表

    管理多个上下文管理器的注册与生命周期
    """
    def __init__(self):
        self._contexts: Dict[str, BaseContextManager] = {}
        self._lock = Lock()

    def register(self, context_manager: BaseContextManager):
        """注册上下文管理器

        :arg context_manager：要注册的上下文管理器

        :raise ValueError：如果已存在同名上下文
        """
        with self._lock:
            if context_manager.name in self._contexts:
                logger.warning(f"上下文'{context_manager.name}' 已存在，请勿重复注册")
                raise ValueError(f"上下文'{context_manager.name}' 已存在，请勿重复注册")
            self._contexts[context_manager.name] = context_manager
            logger.debug(f"上下文'{context_manager.name}' 注册成功")

    def unregister(self, name: str):
        """注销上下文管理器

        :arg name: 要注销的上下文管理器的名称

        :raise ValueError：如果上下文不存在
        """
        with self._lock:
            if name in self._contexts:
                context = self._contexts[name]
                # 在删除之前关闭上下文
                try:
                    context.async_close()
                except Exception as e:
                    logger.warning(f"注销上下文,在关闭上下文'{name}'时出错：{e}")
                del self._contexts[name]
                logger.debug(f"注销上下文'{name}'成功")

    def get_context(self, name: str) -> BaseContextManager:
        """获取上下文管理

        :arg name: 上下文名称

        :returns BaseContextManager: 
        """