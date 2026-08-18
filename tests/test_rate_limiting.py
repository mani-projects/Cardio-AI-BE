import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.database import get_db
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


async def test_faculty_application_endpoint_is_rate_limited_per_ip(engine):
    # Unlike the login test above, this endpoint actually writes rows on
    # success — route get_db at the isolated test-schema engine (same one
    # db_session uses) so this doesn't insert real rows into the dev DB.
    limiter.reset()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            statuses = []
            for i in range(11):
                response = await client.post(
                    "/api/v1/faculty-applications",
                    json={
                        "full_name": "Dr. Rate Limit",
                        "email": f"ratelimit{i}@example.com",
                        "specialty": "Cardiology",
                        "institution": "City Hospital",
                        "country": "United Arab Emirates",
                        "years_experience": 5,
                    },
                )
                statuses.append(response.status_code)
    finally:
        app.dependency_overrides.pop(get_db, None)

    # The faculty-application limit is 5/hour — the 6th request from the
    # same client must be rejected with 429.
    assert statuses[:5].count(429) == 0
    assert statuses[5] == 429
