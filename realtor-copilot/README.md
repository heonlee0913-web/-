# AI Co-Pilot for Realtor — 매물 스코어링 & 안심 진단 엔진

공인중개사용 B2B SaaS의 **백엔드 코어 연산 엔진 + 리포트 UI**. PRD의 기능 1(동적 스코어링)과 기능 2(종합 분석·안심 진단)를 구현했다.

```
[고객 요구사항·가중치] ─▶ [5대 지표 스코어링 + HUG 진단 + CMA + 후기 요약] ─▶ [중개사용 HTML 리포트 / JSON API]
                              ▲ Provider 인터페이스 (지도·공공데이터·실거래가·등기)
```

- 의존성 없음 (Python 3.10+ 표준 라이브러리). Claude 후기 요약만 `anthropic` 패키지를 선택적으로 사용한다.
- `data/sample_data.json` 은 **데모용 가상 데이터**다 (마포구 매물 5건, 고객 2명, 실거래 215건).

## 빠른 시작

```bash
cd realtor-copilot
python -m copilot demo --out report.html                 # 샘플 고객(김민지) 리포트
python -m copilot demo --customer 1 --out report2.html   # 슬라이더 가중치 고객(박준호)
python -m copilot score --name 홍길동 --work "서울 강남구 테헤란로 152 (강남역)" \
    --keywords 출퇴근이 중요해요 가성비가 1순위예요 --exclude-uninsurable
python -m copilot score --name 홍길동 --work default --weights 3 5 1 1 2 --json
python -m copilot serve --port 8000                       # http://127.0.0.1:8000/demo/0
python -m unittest discover -s tests -t .                 # 28개 테스트
```

### HTTP API

| Method | Path | 설명 |
|---|---|---|
| POST | `/api/score` | `{customer_name, work_address, weights? \| keywords?, property_ids?, exclude_uninsurable?}` → 순위·점수·진단 JSON |
| POST | `/api/report` | 같은 요청 → 리포트 HTML |
| GET | `/api/weights/keywords` | 선택 가능한 키워드 목록 |
| GET | `/demo/{n}` | 샘플 고객 n의 리포트 |

`weights` 는 임의 스케일 중요도(예: 슬라이더 0~10)를 받아 **총합 1.0으로 자동 정규화**한다.

## 모듈 구성

| 파일 | PRD | 내용 |
|---|---|---|
| `copilot/weights.py` | 3.2 | 슬라이더 정규화(합 1.0 보장), 키워드 → 가중치 변환, 검증 |
| `copilot/scoring.py` | 3.1, 3.3 | 5대 지표 점수 + 패널티/가산점 규칙 |
| `copilot/insurance.py` | 4.1 | HUG 전세보증보험 진단 (안전/주의/위험) + 조율 보증금 제안 |
| `copilot/market.py` | 4.2 | CMA(반경 300m·유사평형·1년), 적정 전세가, 네고 코멘트, 월세 환산 |
| `copilot/reviews.py` | 4.3 | 후기 긍정/부정 3줄 요약 (규칙 기반 / Claude API) |
| `copilot/engine.py` | 3.3 | 종합 점수 `Σ(점수×가중치)`, 순위, 브리핑 포인트·경고 |
| `copilot/providers.py` | 3.1 | 외부 데이터 Provider 인터페이스, Mock, 카카오 로컬 POI 어댑터 |
| `copilot/report.py` | 2 | 중개사용 리포트 HTML (다크모드·모바일 대응, CMA SVG 차트) |
| `db/schema.sql` | 5 | PostgreSQL 스키마 (PRD 테이블 + 실거래·하자이력·결과 스냅샷) |

## 점수 산정 규칙

PRD에 수치가 명시된 규칙은 그대로, 명시되지 않은 부분은 아래처럼 정했다. 상수는 각 모듈 상단에 모여 있어 조정이 쉽다.

| 지표 | 규칙 |
|---|---|
| **교통** | 10분 이내 100점, 10~45분 분당 -0.6점(45분=79점). **45분 초과 분당 -2점**, **환승 2회 이상 회당 -10점**(PRD), 도보 800m 초과 100m당 -1점 |
| **안전** | 금융 70% (시세 대비 `근저당+보증금` 비율: 50% 이하 100점 → 100% 0점) + 치안 30% (200m CCTV·가로등, 500m 치안센터). 위반건축물 -30점. **부채비율 > 80% 또는 HUG 가입 불가 → 30점 이하 락**(PRD) |
| **인프라** | 반경 500m: 지하철역 25 · 병원 20 · 마트 15 · 편의점 15 · 카페 15 · 약국 10점, 카테고리별 만점 기준 개수(1~5개)까지 비례 |
| **환경** | 연식 5년 이하 85점, 이후 연 -1.5점(최저 30). **남향 +10**, 남동/남서 +5, 북향 -10. **주차 1.2대 이상 +5**(PRD), 0.5대 미만 -10. 대로변 -10 |
| **가성비** | 적정 전세가 대비 시세 수준 70점, 1% 저렴할 때마다 +2점(15% 저렴 = 100점). 전세가율(매매 대비) 80% 초과 -15, 90% 초과 -30 |

### HUG 진단

`한도 = 공시가격 × 140% × 90% (= 126%)`, `여유율 = (한도 − (선순위채권 + 보증금)) / 한도`

| 판정 | 조건 | 출력 |
|---|---|---|
| 안전 - 가입 확실 | 여유율 ≥ 10% | — |
| 주의 - 조율 필요 | 여유율 0~10%, 또는 보증금을 15% 이내로 낮추면 가입 가능 | 가입 가능 최대 보증금, 여유율 10% 확보 **조율 제안가** (100만원 단위 내림) |
| 위험 - 가입 불가 | 선순위 채권만으로 한도 초과, 또는 필요한 인하폭 > 15% (깡통전세) | 사유 + 최대 가능 보증금 |

> PRD 6.1 의사코드와 다른 점: 의사코드는 가입 가능이면 안전 100점에서 부채비율로 감점, 불가면 30점 기준이었다. 본 구현은 3.3의 "80% 락" 규칙과 3.1의 CCTV·불법건축물 기준을 함께 반영하도록 안전 점수를 재구성했고, 의사코드에 없던 **주의(조율 필요)** 등급을 4.1 명세대로 추가했다.

## Claude 후기 요약 (선택)

```bash
pip install anthropic
export ANTHROPIC_API_KEY=...
python -m copilot demo --claude --out report.html
```

`ClaudeSummarizer` 는 후기 원문과 하자 접수 이력을 넣어 JSON 스키마(긍정/부정 각 3줄)로 구조화 출력을 받는다. 모델은 `claude-opus-5-5`, 요약 작업이므로 effort `low`, 안전 분류기 거절에 대비해 서버측 `fallbacks: "default"` 를 켜 두었다. API 오류·거절 시 규칙 기반 요약으로 자동 폴백하므로 리포트 생성은 중단되지 않는다.

## 운영 연동 시 할 일

- **Provider 교체**: `RouteProvider`(ODsay 대중교통 / 네이버·카카오 Directions), `SafetyProvider`(경찰청 CCTV·치안센터, 지자체 가로등), `TransactionProvider`(국토부 RTMS 실거래가) 실제 어댑터 구현. 인프라는 `KakaoLocalPOIProvider`(환경변수 `KAKAO_REST_API_KEY`)가 이미 구현되어 있다.
- **등기·건축물대장**: `senior_bond`, `illegal_building`, `official_price` 는 배치로 `properties_data` 에 적재하고, 계약 직전 등기부 재조회(`registry_checked_at`)를 강제할 것.
- **HUG 실제 심사 차이**: 실제 심사는 주택 유형별 시세 산정(KB시세·감정가 우선), 다가구 선순위 보증금, 임대인 보증사고 이력 등을 추가로 본다. 본 진단은 PRD 기준 1차 스크리닝이며, 리포트에도 그렇게 고지한다.
- **전월세 전환율**: `market.CONVERSION_RATE`(기본 5%)를 기준금리 변동에 맞춰 갱신.
