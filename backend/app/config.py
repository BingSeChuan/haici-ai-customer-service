"""应用配置：全部通过环境变量 / .env 注入，.env.example 提供模板。"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 服务
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # MySQL
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "haici"
    mysql_password: str = "haici_2026"
    mysql_database: str = "haici_cs"

    # JWT
    jwt_secret: str = "change-me-to-a-long-random-string"
    jwt_expire_minutes: int = 10080  # 7 天

    # LLM（DeepSeek / 任意 OpenAI 兼容端点）
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_timeout: int = 60

    # Embedding
    embedding_provider: str = "local_bge"  # local_bge | openai_compatible
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_model: str = ""
    hf_endpoint: str = "https://hf-mirror.com"  # 中国大陆网络下载镜像

    # RAG 参数
    rag_top_k: int = 8
    rag_similarity_threshold: float = 0.45
    rag_context_budget_chars: int = 4000   # 检索片段拼入 Prompt 的字符预算
    rag_history_rounds: int = 6            # 多轮对话携带最近 N 轮
    chunk_size: int = 500                  # 分块长度（字符）
    chunk_overlap: int = 50                # 分块重叠

    # 业务规则
    max_question_length: int = 500
    daily_question_limit: int = 100
    fallback_reply: str = "抱歉，我在知识库中暂时没有找到与您的问题相关的信息。建议您换一种问法，或直接联系人工客服处理。"

    # 数据目录
    upload_dir: str = "./uploads"
    chroma_dir: str = "./chroma_data"
    seed_docs_dir: str = "./data/seed_docs"

    @property
    def mysql_url(self) -> str:
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
