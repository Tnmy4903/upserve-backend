from motor.motor_asyncio import AsyncIOMotorClient

from app.config import (
    MONGO_URI,
    DB_NAME
)

client = AsyncIOMotorClient(
    MONGO_URI,
    maxPoolSize=50,
    minPoolSize=5,
    serverSelectionTimeoutMS=5000,
    connectTimeoutMS=5000,
    socketTimeoutMS=30000,
    retryWrites=True
)

db = client[DB_NAME]

