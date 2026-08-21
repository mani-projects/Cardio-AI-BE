from app.modules.courses.service import update_course


async def test_update_course_updates_title(db_session, make_course):
    course = await make_course(title="Old Title")

    updated = await update_course(db_session, course, title="New Title")

    assert updated.title == "New Title"


async def test_update_course_updates_price_cents(db_session, make_course):
    course = await make_course(price_cents=25000)

    updated = await update_course(db_session, course, price_cents=30000)

    assert updated.price_cents == 30000


async def test_update_course_updates_is_active(db_session, make_course):
    course = await make_course(is_active=True)

    updated = await update_course(db_session, course, is_active=False)

    assert updated.is_active is False


async def test_update_course_leaves_omitted_fields_unchanged(db_session, make_course):
    course = await make_course(title="Keep Me", price_cents=25000, is_active=True)

    updated = await update_course(db_session, course, price_cents=30000)

    assert updated.title == "Keep Me"
    assert updated.price_cents == 30000
    assert updated.is_active is True
