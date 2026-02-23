import boto3
from .base import FileStorage


class S3Storage(FileStorage):

    def __init__(self, bucket: str):
        self.bucket = bucket
        self.s3 = boto3.client("s3")

    async def save(self, path: str, content: bytes) -> str:
        self.s3.put_object(
            Bucket=self.bucket,
            Key=path,
            Body=content,
            ContentType="application/pdf"
        )
        return path  # store only key, not full s3:// url

    async def read(self, path: str) -> bytes:
        obj = self.s3.get_object(Bucket=self.bucket, Key=path)
        return obj["Body"].read()

    async def delete(self, path: str) -> None:
        self.s3.delete_object(
            Bucket=self.bucket,
            Key=path
        )