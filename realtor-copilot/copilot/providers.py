"""외부 데이터 Provider 인터페이스 + 구현체.

엔진은 아래 Protocol 에만 의존한다. 운영 환경에서는 실제 API 어댑터로 교체한다.

| 지표      | Protocol            | 실제 데이터 소스                                   | 제공 구현                 |
|-----------|---------------------|----------------------------------------------------|---------------------------|
| 교통      | RouteProvider       | ODsay 대중교통 길찾기 / 네이버·카카오 Directions   | Mock                      |
| 안전      | SafetyProvider      | 경찰청 CCTV·치안센터, 지자체 가로등 공공데이터     | Mock                      |
| 인프라    | POIProvider         | 카카오 로컬 API 카테고리 검색                      | Mock, KakaoLocalPOIProvider |
| 시세      | TransactionProvider | 국토교통부 실거래가 공개시스템 (RTMS) API          | Mock                      |
| 등기/건축 | (Property 컬럼)     | 대법원 등기부등본, 건축물대장 API → properties_data | 배치 적재                 |
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Protocol

from .models import Property, SafetyFacilities, Transaction, TransitRoute


class RouteProvider(Protocol):
    def route(self, prop: Property, work_address: str) -> TransitRoute: ...


class SafetyProvider(Protocol):
    def facilities(self, prop: Property) -> SafetyFacilities: ...


class POIProvider(Protocol):
    def counts(self, prop: Property) -> dict: ...


class TransactionProvider(Protocol):
    def transactions(self, prop: Property) -> list[Transaction]: ...


# --------------------------------------------------------------------- Mock
class MockDataStore:
    """data/sample_data.json 기반 (데모·테스트용). 4개 Protocol 을 모두 구현한다."""

    def __init__(self, data: dict):
        self.data = data
        self._ctx = {int(k): v for k, v in data["contexts"].items()}

    @classmethod
    def from_file(cls, path: str | Path) -> "MockDataStore":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def properties(self) -> list[Property]:
        return [Property(**p) for p in self.data["properties"]]

    def preferences(self) -> list[dict]:
        return self.data.get("customers", [])

    def _c(self, prop: Property) -> dict:
        try:
            return self._ctx[prop.property_id]
        except KeyError:
            raise LookupError(f"매물 {prop.property_id} 의 외부 데이터가 없습니다.") from None

    def route(self, prop: Property, work_address: str) -> TransitRoute:
        routes = self._c(prop)["routes"]
        r = routes.get(work_address) or routes.get("default")
        if r is None:
            raise LookupError(f"'{work_address}' 까지의 경로 데이터가 없습니다.")
        return TransitRoute(**r)

    def facilities(self, prop: Property) -> SafetyFacilities:
        return SafetyFacilities(**self._c(prop)["safety"])

    def counts(self, prop: Property) -> dict:
        return dict(self._c(prop)["poi"])

    def transactions(self, prop: Property) -> list[Transaction]:
        return [Transaction(*row) for row in self._c(prop)["transactions"]]


# --------------------------------------------------------------------- Kakao
class KakaoLocalPOIProvider:
    """카카오 로컬 API 카테고리 검색으로 반경 500m 내 POI 개수를 센다.

    REST API 키는 환경변수 KAKAO_REST_API_KEY. Property.lat/lng 필요.
    https://developers.kakao.com/docs/latest/ko/local/dev-guide#search-by-category
    """
    ENDPOINT = "https://dapi.kakao.com/v2/local/search/category.json"
    CATEGORY_CODES = {
        "mart": "MT1", "convenience": "CS2", "hospital": "HP8",
        "pharmacy": "PM9", "cafe": "CE7", "subway": "SW8",
    }

    def __init__(self, api_key: str | None = None, radius_m: int = 500, timeout: float = 5.0):
        self.api_key = api_key or os.environ.get("KAKAO_REST_API_KEY")
        if not self.api_key:
            raise ValueError("KAKAO_REST_API_KEY 가 필요합니다.")
        self.radius_m = radius_m
        self.timeout = timeout

    def _count(self, code: str, lat: float, lng: float) -> int:
        q = urllib.parse.urlencode({"category_group_code": code, "x": lng, "y": lat,
                                    "radius": self.radius_m, "size": 1})
        req = urllib.request.Request(f"{self.ENDPOINT}?{q}",
                                     headers={"Authorization": f"KakaoAK {self.api_key}"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return int(json.load(resp)["meta"]["total_count"])

    def counts(self, prop: Property) -> dict:
        if prop.lat is None or prop.lng is None:
            raise ValueError(f"매물 {prop.property_id} 의 좌표(lat/lng)가 없습니다.")
        return {k: self._count(c, prop.lat, prop.lng) for k, c in self.CATEGORY_CODES.items()}
