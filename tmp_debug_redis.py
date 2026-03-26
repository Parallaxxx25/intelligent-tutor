import asyncio
import fakeredis

async def test_session():
    fake_client = fakeredis.FakeAsyncRedis(decode_responses=True)
    await fake_client.set("foo", "bar")
    val = await fake_client.get("foo")
    print(f"VAL: {val}")
    await fake_client.close()

if __name__ == "__main__":
    asyncio.run(test_session())
