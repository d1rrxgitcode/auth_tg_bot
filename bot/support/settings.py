from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    TOKEN: str

    class Config:
        env_file = ".env"