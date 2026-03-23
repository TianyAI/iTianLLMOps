from typing import Optional
from pydantic import BaseModel, ConfigDict, Field
from itian.common.constants.enums.telemetry import ApplicationTypeEnum

class iTianBase(BaseModel):
    """所有 iTian 模型的基础类"""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        validate_by_name=True,
        validate_by_alias=True,
    )

    # 核心标识
    model_id: int = Field(description="模型唯一量化ID")
    model_name: str = Field(description="模型名称")

    # 遥测字段
    app_id: str = Field(..., description="应用ID")
    app_type: ApplicationTypeEnum = Field(..., description="应用类型")
    app_name: str = Field(..., description="应用名称")
    user_id: int = Field(..., description="调用用户ID")

    # 配置信息
    model_info: Optional[LLMModel] = Field(default=None, description="模型信息")
    server_info: Optional[LLMServer] = Field(default=None, description="服务供应商信息")


