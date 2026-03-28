"""数据库连接管理模块"""
import logging
from typing import Optional, Dict, Any, Generator
from contextlib import asynccontextmanager, contextmanager
from sqlalchemy import create_engine, Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker

logger = logging.getLogger(__name__)


class DatabaseConnectionManager:
    """数据库连接管理器

    负责管理数据库引擎的创建、连接池的配置以及生命周期管理
    """

    def __init__(self, database_url: str, **engine_kwargs):
        self.database_url = database_url
        self.async_database_url = self._convert_to_async_url(database_url)
        self.engine_kwargs = engine_kwargs

        self._engine: Optional[Engine] = None
        self._async_engine: Optional[AsyncEngine] = None
        self._async_session_maker: Optional[async_sessionmaker] = None

    def _convert_to_async_url(self, url: str) -> str:
        """数据库将从同步URL转换为异步URL"""
        if 'pymysql' in url:
            return url.replace("pymysql", "aiomysql")
        elif 'psycopg2' in url:
            return url.replace("psycopg2", "asyncpg")
        return url

    def _get_default_engine_config(self) -> Dict[str, Any]:
        """获取默认引擎配置"""
        config = {
            'pool_size': 100,
            'max_overflow': 20,
            'pool_timeout': 30,
            'pool_pre_ping': True,
            'pool_recycle': 3600 # 1小时
        }

        # SQLiteSPECIAL CONFIGURATION
        if self.database_url.startswith('sqlite'):
            config.update({
                'connect_args': {'check_same_thread': False},
                'poolclass': StaticPool,
                'pool_size': 1,
                'max_overflow': 0,
            })
        # MySQLSPECIAL CONFIGURATION
        elif "mysql" in self.database_url:
            if 'connect_args' not in config:
                config['connect_args'] = {}
            config['connect_args']['charset'] = 'utf8mb4'

        return config

    @property
    def engine(self) -> Engine:
        """获取同步数据库引擎"""
        if self._engine is None:
            config = self._get_default_engine_config()
            config.update(self.engine_kwargs)

            self._engine = create_engine(
                self.database_url,
                **config
            )
            logger.debug(f"创建同步数据库引擎: {self.database_url}")

        return self._engine

