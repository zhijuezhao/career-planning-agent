"""B1（2026-10-03）单元测试：由**城市**反查省份。

为什么单独一个文件（而不是放进 `test_company_service.py`）：
    后者有 `@pytest.fixture(autouse=True)` 开数据库连接，**每个**用例都依赖真实 dev DB；
    这里全是纯函数，放进去会在无 DB 环境下整体 error。

存在的原因（业务背景）：
    用户的 524 行导入表**没有「省份」列**（那 12 列里确实没有）→ 不做推导的话
    `companies.region` 全为 `None`，管理端「先选省、再选市」的省份列表会是空的。
    实测这份表的 **70 个城市 70/70** 都能在 `geo_divisions.PROVINCE_CITIES` 里反查到省份。
"""

from __future__ import annotations

from app.domain.services.company_service import province_of_city


class TestProvinceOfCity:
    def test_municipalities_map_to_themselves(self):
        """直辖市：省短名就是它自己（`北京` 省 → `北京` 市）。"""
        assert province_of_city("上海") == "上海"
        assert province_of_city("北京") == "北京"
        assert province_of_city("重庆") == "重庆"

    def test_regular_cities(self):
        assert province_of_city("临沂") == "山东"
        assert province_of_city("乌鲁木齐") == "新疆"
        assert province_of_city("佛山") == "广东"
        assert province_of_city("保定") == "河北"
        assert province_of_city("南京") == "江苏"

    def test_accepts_full_city_names(self):
        """带「市」后缀也应先归一成短名再反查。"""
        assert province_of_city("南京市") == "江苏"
        assert province_of_city("临沂市") == "山东"

    def test_missing_and_unknown_return_none(self):
        assert province_of_city(None) is None
        assert province_of_city("") is None
        assert province_of_city("未知") is None
        assert province_of_city("不存在的城市名") is None
