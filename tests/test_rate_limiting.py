import httpx

from app.core.limiter import limiter
from app.main import app


async def test_login_endpoint_is_rate_limited_per_ip():
    # In-memory limiter state is process-global — start from a clean slate so
    # this test doesn't depend on how many requests earlier tests happened to
    # send through the same app instance.
    limiter.reset()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        statuses = []
        for _ in range(11):
            response = await client.post(
                "/api/v1/auth/login",
                json={"email": "nobody@example.com", "password": "wrong"},
            )
            statuses.append(response.status_code)

    # The login limit is 10/minute — the 11th request from the same client
    # must be rejected with 429, regardless of credentials being wrong.
    assert statuses[:10].count(429) == 0
    assert statuses[10] == 429
