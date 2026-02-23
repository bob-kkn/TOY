# CAU159: Polygon-to-Centerline Skeletonization Engine

CAU159는 도로 면형(Polygon) 데이터를 분석하여 중심선(LineString Network)을 생성하는 GIS 공간 데이터 처리 파이프라인 엔진입니다. 면형 중심의 선형 추출, 네트워크 연결성 구성, 교차로 위상 정규화 기능을 포함하고 있습니다.

---

## 1. System Architecture
객체 생성과 비즈니스 로직을 분리하여 구성했습니다.

* **Composition Root:** `Service.container.py`를 통해 애플리케이션의 객체 생성 및 의존성 주입(DI)을 중앙에서 관리합니다.
* **Layered Architecture:** 사용자 인터페이스(`UIService`), 데이터 입출력 및 파이프라인 제어(`GISService`), 알고리즘 모듈(`GIS_Modules`) 계층으로 분리되어 있습니다.
* **Strategy Pattern:** 위상 정제 및 노이즈 제거 로직을 `CoordinateSnapper`, `Planarizer`, `IntersectionMerger` 등의 개별 전략 클래스로 분리하여 순차적으로 실행합니다.
* **Async Worker:** UI 스레드 블로킹을 방지하기 위해 `PySide6`의 `QThread`를 상속한 `GISWorker`에서 중심선 추출 연산을 수행합니다.

---

## 2. Core GIS Pipeline
파이프라인은 원시 뼈대 추출(Skeleton) 단계와 위상 정규화(Topology) 단계로 나뉩니다.

### 🧩 2.1. Skeletonization Module (`Service.gis_modules.skeleton`)
보로노이 다이어그램(Voronoi Diagram)을 활용하여 면형 내부의 중심선을 추출합니다.
* **Voronoi Generator:** 폴리곤 경계를 조밀화(Segmentize)한 후 보로노이 다이어그램을 생성하여 면형 내부와 교차하는 원시 뼈대를 생성합니다.
* **Graph-based Pruning:** 추출된 선분을 NetworkX 그래프로 변환한 뒤, 노드와 경계 간 거리(Radius) 정보를 기반으로 `RatioPruner`, `BoundaryNearPruner`, `ComponentPruner`, `SpurPruner`를 순차 적용해 잔가지를 제거합니다.

### 🛠️ 2.2. Topology Optimization Module (`Service.gis_modules.topology`)
추출된 중심선을 네트워크 데이터 형태로 정제합니다.
* **Planarization:** 교차하는 모든 선분을 분할하여 교차 노드를 생성합니다.
* **Intersection Normalization:** `IntersectionMerger`로 임계값(1.5m) 이하의 다중 간선을 병합하고, `IntersectionSmoother`로 교차점 진입부의 굴곡을 직선화합니다.
* **Intelligent Cleaning:** `TerminalForkCleaner`를 이용해 원본 폴리곤 외곽선에 근접한 Y자 및 단일 꺾임 형태의 노이즈를 추적하여 삭제합니다.
* **Network Simplification:** `NetworkSimplifier`를 통해 위상(Topology)을 보존하는 범위 내에서 선형의 좌표를 단순화합니다.

---

## 3. Data Integrity & Observability
데이터 검증 및 실행 상태 로깅을 수행합니다.

* **QA Validator (`ResultValidator`):** 연산 완료 후 네트워크의 파편화 그룹 수와 도로 끝점의 경계면 이탈 거리를 연산하여 경고 로그를 출력합니다.
* **Diagnostics (`TopologyDiagnostics`):** 엣지(Edge) 길이 분포, 노드 차수(Degree) 비율, 경계 근접 엣지 데이터를 요약하여 통계 로그를 기록합니다.
* **Intermediate Snapshots:** 설정(`GISConfig`)에서 `debug_export_intermediate` 활성화 시, Skeleton, Planarized, Cleaned, Final 단계의 중간 GeoDataFrame을 SHP 파일로 개별 저장합니다.

---

## 4. Current Engineering Focus
* **Staggered Junctions:** 미세하게 어긋나 교차하는 노드들을 하나의 십자형 교차로로 병합하기 위한 거리/각도 기반 정제 로직 조정.
* **Simplification Tolerance:** `NetworkSimplifier`의 허용 오차 값을 조절하여 도로의 곡선 형상 유지와 지그재그 노이즈 직선화 사이의 임계값 튜닝.

---

## 5. Technology Stack
* **Language:** Python 3.11+ 
* **GIS / Geometry:** GeoPandas, Shapely
* **Graph Theory:** NetworkX, Momepy
* **Config & Validation:** Pydantic (`BaseSettings`)
* **UI Framework:** PySide6