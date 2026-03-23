from typing import Dict, Any

from pydantic import ConfigDict
from sqlmodel import SQLModel

class SQLModelSerializable(SQLModel):
    """所有数据模型的序列化器基类"""

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def create (cls, **data) -> "SQLModelSerializable":
        """ 创建一个新实例 """
        return cls(**data)

    def model_dump(self, **kwargs):
        """ 默认返回模式是json """
        if 'mode' not in kwargs:
            kwargs['mode'] = 'json'
        return super().model_dump(**kwargs)