from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # 基础
    DATABASE_URL: str = "sqlite:///./dev.db"
    REDIS_URL: str = "redis://localhost:6379/0"
    LOG_LEVEL: str = "INFO"  # 排查问题时置 DEBUG：输出每步决策日志

    # JWT
    JWT_SECRET: str = "dev-only-secret-change-me-in-production-0123456789"
    JWT_EXPIRE_MINUTES: int = 10080  # 7 天
    JWT_ALGORITHM: str = "HS256"

    # 微信
    WX_APPID: str = ""
    WX_SECRET: str = ""
    WX_MOCK_LOGIN: bool = False  # 本地开发无密钥时置 true
    # 订阅消息模板（两条：课前/调课、假期/时令，拷问 Q4 定稿）
    WX_SUBSCRIBE_TEMPLATE_LESSON: str = ""
    WX_SUBSCRIBE_TEMPLATE_HOLIDAY: str = ""

    # 调度器：单元测试置 false，避免后台线程干扰 SQLite 内存库
    SCHEDULER_ENABLED: bool = True

    # AI（移动云 MoMA）
    AI_BASE_URL: str = "https://moma.cmecloud.cn/v1"
    AI_API_KEY: str = ""
    AI_MODEL: str = ""

    # 文件
    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_SIZE_MB: int = 10

    # 时区约束：全项目统一 Asia/Shanghai（任务书 7.1.1）
    TIMEZONE: str = "Asia/Shanghai"


@lru_cache
def get_settings() -> Settings:
    return Settings()
