import pytest

from app.naming import guess_product_name, product_code


@pytest.mark.parametrize("name,code", [
    ("id260_Max_rk1_блендер_16.09_50$", "id260"),
    ("aerogril_id20_07.07_Maks_BIT", "id20"),
    ("SASHA_Аплікатор-Кузнецова_ID144_05.08_test-12$_1/1/4", "id144"),
    ("id72_Vlasnyk_podribnyuvach_0505_100$", "id72"),
    ("15/04 Blender-Zepline-5v1 │Lead │CBO 1-1-3 │test", None),
    ("rapid_test", None),
])
def test_product_code(name, code):
    assert product_code(name) == code


def test_guess_name():
    assert guess_product_name("id260_Max_rk1_блендер_16.09_50$") == "блендер"
    assert guess_product_name("SASHA_Аплікатор-Кузнецова_ID144_05.08_test-12$_1/1/4") == "Аплікатор-Кузнецова"
    assert guess_product_name("kompresor_id51_Maks_19.06_11$ test") == "kompresor"
