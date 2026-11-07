"""도메인 모델 (PRD 5장 DB 스키마와 1:1 대응되는 dataclass + 외부 데이터 스냅샷)."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class UserPreference:
    """users_preference 테이블."""
    customer_name: str
    work_address: str
    weight_traffic: float = 0.20
    weight_safety: float = 0.20
    weight_infrastructure: float = 0.20
    weight_environment: float = 0.20
    weight_value: float = 0.20
    user_id: Optional[int] = None


@dataclass
class Property:
    """properties_data 테이블 (+ 진단에 필요한 확장 컬럼)."""
    property_id: int
    address: str
    property_type: str                 # 아파트 / 빌라 / 오피스텔 ...
    price_deposit: int                 # 보증금 (원)
    official_price: int                # 공시가격 (원)
    price_monthly: int = 0             # 월세 (원)
    senior_bond: int = 0               # 선순위 채권/근저당 (원)
    direction: Optional[str] = None    # 남향, 남동향, 동향 ...
    parking_ratio: Optional[float] = None
    built_year: Optional[int] = None
    resident_reviews: str = ""
    # --- 확장 컬럼 (properties_data 확장, db/schema.sql 참고) ---
    exclusive_area_m2: Optional[float] = None   # 전용면적
    market_price: Optional[int] = None          # 매매 시세 (없으면 공시가 기반 추정)
    lat: Optional[float] = None
    lng: Optional[float] = None
    illegal_building: bool = False              # 건축물대장 위반건축물 표기
    near_main_road: bool = False                # 대로변 인접 (소음 요인)


@dataclass
class TransitRoute:
    """지도 API Directions 결과 (대중교통)."""
    total_minutes: float
    transfers: int
    walk_meters: float


@dataclass
class SafetyFacilities:
    """경찰청 공공데이터 - 반경 200m."""
    cctv_count: int
    streetlight_count: int
    police_box_within_500m: bool = False


@dataclass
class Transaction:
    """국토부 실거래가 1건."""
    deal_date: str            # YYYY-MM-DD
    deal_type: str            # 매매 / 전세
    price: int                # 원
    area_m2: float
    distance_m: float = 0.0


@dataclass
class PropertyContext:
    """한 매물에 대해 외부 Provider 들로부터 수집된 원천 데이터 묶음."""
    route: TransitRoute
    safety: SafetyFacilities
    poi_counts: dict                       # {"mart": 2, "convenience": 5, ...}
    transactions: list = field(default_factory=list)   # list[Transaction]


def to_dict(obj) -> dict:
    return asdict(obj)
