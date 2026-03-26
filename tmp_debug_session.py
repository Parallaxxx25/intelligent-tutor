import asyncio
import fakeredis
from backend.memory.redis_session import SessionManager

async def debug_session():
    fake_client = fakeredis.FakeAsyncRedis(decode_responses=True)
    manager = SessionManager(url="redis://localhost:6379/1")
    manager._client = fake_client

    uid, pid = 1, 1
    # Test update
    await manager.update_session(uid, pid, {"test": "val"})
    # Test fetch
    s = await manager.get_session(uid, pid)
    print(f"FETCHED: {s}")
    # Test clean
    await manager.clear_session(uid, pid)
    s2 = await manager.get_session(uid, pid)
    print(f"CLEARED: {s2}")

if __name__ == "__main__":
    asyncio.run(debug_session())
