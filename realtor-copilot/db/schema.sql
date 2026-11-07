-- AI Co-Pilot for Realtor — PostgreSQL 스키마
-- PRD 5.1 / 5.2 테이블 + 엔진 구동에 필요한 확장 테이블

-- 5.1 고객 가중치 및 요구사항 ------------------------------------------------
CREATE TABLE IF NOT EXISTS users_preference (
    user_id               SERIAL PRIMARY KEY,
    customer_name         VARCHAR(50)  NOT NULL,
    work_address          TEXT         NOT NULL,             -- 직장 주소 (교통 점수 계산용)
    weight_traffic        NUMERIC(3,2) DEFAULT 0.20,
    weight_safety         NUMERIC(3,2) DEFAULT 0.20,
    weight_infrastructure NUMERIC(3,2) DEFAULT 0.20,
    weight_environment    NUMERIC(3,2) DEFAULT 0.20,
    weight_value          NUMERIC(3,2) DEFAULT 0.20,
    created_at            TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT weights_range CHECK (
        weight_traffic BETWEEN 0 AND 1 AND weight_safety BETWEEN 0 AND 1 AND
        weight_infrastructure BETWEEN 0 AND 1 AND weight_environment BETWEEN 0 AND 1 AND
        weight_value BETWEEN 0 AND 1),
    -- PRD 3.2: 가중치 총합은 무조건 1.0
    CONSTRAINT weights_sum_one CHECK (
        weight_traffic + weight_safety + weight_infrastructure
        + weight_environment + weight_value = 1.00)
);

-- 5.2 매물 기본 및 행정 데이터 ----------------------------------------------
CREATE TABLE IF NOT EXISTS properties_data (
    property_id       SERIAL PRIMARY KEY,
    address           TEXT        NOT NULL,
    property_type     VARCHAR(20) NOT NULL,                 -- 아파트, 빌라, 오피스텔 등
    price_deposit     BIGINT      NOT NULL,                 -- 보증금
    price_monthly     INT         DEFAULT 0,                -- 월세
    official_price    BIGINT      NOT NULL,                 -- 공시가격 (보험 진단용)
    senior_bond       BIGINT      DEFAULT 0,                -- 선순위 채권/근저당
    direction         VARCHAR(10),                          -- 주향
    parking_ratio     NUMERIC(3,2),                         -- 세대당 주차 대수
    built_year        INT,
    resident_reviews  TEXT,
    -- 확장 컬럼 (엔진 입력) --------------------------------------------------
    exclusive_area_m2 NUMERIC(6,2),                         -- 전용면적 (CMA 유사평형 필터)
    market_price      BIGINT,                               -- 매매 시세 (없으면 실거래로 추정)
    lat               NUMERIC(9,6),
    lng               NUMERIC(9,6),
    illegal_building  BOOLEAN     DEFAULT FALSE,            -- 건축물대장 위반건축물
    near_main_road    BOOLEAN     DEFAULT FALSE,            -- 대로변 인접(소음)
    registry_checked_at TIMESTAMP,                          -- 등기부 최종 조회 시각
    CONSTRAINT price_positive CHECK (price_deposit >= 0 AND official_price > 0 AND senior_bond >= 0)
);
CREATE INDEX IF NOT EXISTS idx_properties_geo ON properties_data (lat, lng);

-- 국토부 실거래가 (CMA·가성비) ----------------------------------------------
CREATE TABLE IF NOT EXISTS real_transactions (
    tx_id        BIGSERIAL PRIMARY KEY,
    complex_key  TEXT,                                       -- 단지/건물 식별자
    address      TEXT        NOT NULL,
    deal_date    DATE        NOT NULL,
    deal_type    VARCHAR(10) NOT NULL CHECK (deal_type IN ('매매', '전세', '월세')),
    price        BIGINT      NOT NULL,                       -- 매매가 또는 보증금
    monthly_rent INT         DEFAULT 0,
    area_m2      NUMERIC(6,2) NOT NULL,
    lat          NUMERIC(9,6),
    lng          NUMERIC(9,6)
);
CREATE INDEX IF NOT EXISTS idx_tx_date ON real_transactions (deal_date);
CREATE INDEX IF NOT EXISTS idx_tx_geo  ON real_transactions (lat, lng);

-- 하자/층간소음 접수 이력 (후기 요약 보강) ----------------------------------
CREATE TABLE IF NOT EXISTS defect_history (
    defect_id   BIGSERIAL PRIMARY KEY,
    property_id INT REFERENCES properties_data(property_id) ON DELETE CASCADE,
    reported_on DATE,
    category    VARCHAR(30),                                 -- 층간소음, 누수, 방수 ...
    description TEXT
);

-- 스코어링 결과 스냅샷 (리포트 재현·감사용) ---------------------------------
CREATE TABLE IF NOT EXISTS scoring_results (
    result_id            BIGSERIAL PRIMARY KEY,
    user_id              INT REFERENCES users_preference(user_id) ON DELETE CASCADE,
    property_id          INT REFERENCES properties_data(property_id) ON DELETE CASCADE,
    total_score          NUMERIC(4,1) NOT NULL,
    score_traffic        NUMERIC(4,1),
    score_safety         NUMERIC(4,1),
    score_infrastructure NUMERIC(4,1),
    score_environment    NUMERIC(4,1),
    score_value          NUMERIC(4,1),
    safety_locked        BOOLEAN DEFAULT FALSE,
    insurance_status     VARCHAR(10) CHECK (insurance_status IN ('SAFE', 'CAUTION', 'DANGER')),
    insurance_limit      BIGINT,
    recommended_deposit  BIGINT,
    fair_jeonse          BIGINT,
    detail               JSONB,                              -- 산출 근거·후기 요약 전체
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_results_user ON scoring_results (user_id, total_score DESC);
