import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # API Keys
    # os.getenv 兼容各部署平台的直接环境变量注入
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
    BAIDU_API_KEY: str = os.getenv("BAIDU_API_KEY", "")

    # Model Configuration
    # 默认使用 deepseek-chat
    MODEL_NAME: str = "deepseek-chat"
    EVALUATOR_MODEL_NAME: str = "deepseek-chat"

    # RAG Configuration
    RAG_ENABLED: bool = True  # Enable RAG for memory retrieval
    RAG_TOP_K: int = 3        # Number of documents to retrieve
    # 对话记忆检索的 Embedding 已统一为 Qwen3（与题库检索共用同一服务）。
    # 该字段仅作历史兼容保留，实际模型取 KNOWLEDGE_EMBEDDING_MODEL。
    RAG_EMBEDDING_MODEL: str = "Qwen3-Embedding-0.6B-4bit-DWQ"
    # 对话记忆向量检索的 L2 距离阈值：score（L2 距离，越小越相似）超过该值即丢弃。
    # 归一化向量 L2 距离范围约 [0, 2]；实测相关片段 ≈0.3，不相关 ≈1.0+。
    RAG_SIMILARITY_THRESHOLD: float = float(
        os.getenv("RAG_SIMILARITY_THRESHOLD", "0.8")
    )

    # Knowledge Base Configuration (面试知识库，独立于对话记忆 RAG)
    KNOWLEDGE_DB_PATH: str = os.getenv("KNOWLEDGE_DB_PATH", "data/knowledge.db")
    KNOWLEDGE_EMBEDDING_BASE_URL: str = os.getenv(
        "KNOWLEDGE_EMBEDDING_BASE_URL", "http://127.0.0.1:8000/v1"
    )
    KNOWLEDGE_EMBEDDING_MODEL: str = os.getenv(
        "KNOWLEDGE_EMBEDDING_MODEL", "Qwen3-Embedding-0.6B-4bit-DWQ"
    )
    KNOWLEDGE_EMBEDDING_API_KEY: str = os.getenv("KNOWLEDGE_EMBEDDING_API_KEY", "local")
    KNOWLEDGE_EMBEDDING_DIM: int = int(os.getenv("KNOWLEDGE_EMBEDDING_DIM", "1024"))

    # Constants
    MODE_ACTIVE: str = "active"
    MODE_SOCRATIC: str = "socratic"

    # Thresholds
    MAX_ITERATIONS: int = 5  # 防止苏格拉底模式下死循环追问的最大次数
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()
