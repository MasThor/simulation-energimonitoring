from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = "redispass"

    influx_host: str = "http://localhost:8086"
    influx_token: str = "my-super-secret-admin-token-12345"
    influx_org: str = "manufacturing"
    influx_database: str = "energy_monitoring"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"

settings = Settings()
