from enum import Enum

# 生成式应用枚举
class ApplicationTypeEnum(str, Enum):
    """应用枚举"""

    # 工作流应用
    WORKFLOW = "workflow"
    # 技能应用
    SKILL = "skill"
    # 助手应用
    ASSISTANT = "assistant"
    # 创意应用
    CREATIVITY = "creativity"
    # 日常会话应用
    DAILY_CHAT = "daily_chat"
    # 知识库应用
    KNOWLEDGE_BASE = "knowledge_base"
    # RAGBack
    RAG_TRACEABILITY = "rag_traceability"
    # 审查模型
    EVALUATION = "evaluation"
    # 模型测试
    MODEL_TEST = "model_test"
    # ASR
    ASR = "asr"
    # TTS
    TTS = "tts"

    UNKNOWN = "unknown"