import uuid

import pytest

from app.modules.case_categories.service import (
    CaseCategoryNotFoundError,
    DuplicateCategoryNameError,
    create_category,
    get_category,
    list_categories_for_course,
    update_category,
)


async def test_create_category_defaults_to_active(db_session, make_course):
    course = await make_course(slug="1")
    category = await create_category(db_session, course_id=course.id, name="CAD")

    assert category.course_id == course.id
    assert category.name == "CAD"
    assert category.is_active is True
    assert category.sort_order == 0


async def test_create_category_blocks_duplicate_name_for_same_course(db_session, make_course):
    course = await make_course(slug="1")
    await create_category(db_session, course_id=course.id, name="CAD")

    with pytest.raises(DuplicateCategoryNameError):
        await create_category(db_session, course_id=course.id, name="CAD")


async def test_create_category_allows_same_name_across_different_courses(db_session, make_course):
    course_a = await make_course(slug="1")
    course_b = await make_course(slug="2")
    await create_category(db_session, course_id=course_a.id, name="CAD")

    category_b = await create_category(db_session, course_id=course_b.id, name="CAD")

    assert category_b.course_id == course_b.id


async def test_get_category_raises_not_found_for_unknown_id(db_session):
    with pytest.raises(CaseCategoryNotFoundError):
        await get_category(db_session, uuid.uuid4())


async def test_list_categories_for_course_excludes_inactive_by_default(db_session, make_course, make_case_category):
    course = await make_course(slug="1")
    active = await make_case_category(course, name="CAD", is_active=True, sort_order=0)
    await make_case_category(course, name="Plaque", is_active=False, sort_order=1)

    categories = await list_categories_for_course(db_session, course.id)

    assert [c.id for c in categories] == [active.id]


async def test_list_categories_for_course_includes_inactive_when_requested(db_session, make_course, make_case_category):
    course = await make_course(slug="1")
    active = await make_case_category(course, name="CAD", is_active=True, sort_order=0)
    inactive = await make_case_category(course, name="Plaque", is_active=False, sort_order=1)

    categories = await list_categories_for_course(db_session, course.id, include_inactive=True)

    assert {c.id for c in categories} == {active.id, inactive.id}


async def test_list_categories_for_course_orders_by_sort_order(db_session, make_course, make_case_category):
    course = await make_course(slug="1")
    second = await make_case_category(course, name="Plaque", sort_order=1)
    first = await make_case_category(course, name="CAD", sort_order=0)

    categories = await list_categories_for_course(db_session, course.id)

    assert [c.id for c in categories] == [first.id, second.id]


async def test_update_category_renames(db_session, make_course, make_case_category):
    course = await make_course(slug="1")
    category = await make_case_category(course, name="CAD")

    updated = await update_category(db_session, category, name="CAD Renamed")

    assert updated.name == "CAD Renamed"


async def test_update_category_blocks_rename_to_duplicate_name(db_session, make_course, make_case_category):
    course = await make_course(slug="1")
    await make_case_category(course, name="CAD", sort_order=0)
    plaque = await make_case_category(course, name="Plaque", sort_order=1)

    with pytest.raises(DuplicateCategoryNameError):
        await update_category(db_session, plaque, name="CAD")


async def test_update_category_allows_renaming_to_its_own_current_name(db_session, make_course, make_case_category):
    course = await make_course(slug="1")
    category = await make_case_category(course, name="CAD")

    updated = await update_category(db_session, category, name="CAD")

    assert updated.name == "CAD"


async def test_update_category_can_deactivate(db_session, make_course, make_case_category):
    course = await make_course(slug="1")
    category = await make_case_category(course, name="CAD", is_active=True)

    updated = await update_category(db_session, category, is_active=False)

    assert updated.is_active is False
