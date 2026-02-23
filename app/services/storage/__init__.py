from app.core.config import settings
from .local import LocalStorage
from .s3 import S3Storage

def get_storage():
    if settings.FILE_STORAGE == "s3":
        return S3Storage(settings.S3_BUCKET)
    return LocalStorage()