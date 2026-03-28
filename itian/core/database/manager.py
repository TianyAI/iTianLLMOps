"""数据库全局管理器

提供全局管理并可轻松访问数据库上下文，
支持健康检查、连接池监控和事务管理
"""
import logging
from typing import Dict, Any, Optional, AsyncGenerator
from contextlib import asynccontextmanager, contextmanager

from sqlalchemy import text
from sqlmodel.ext.asyncio.session import AsyncSession

from itian.core.context import BaseContextManager
