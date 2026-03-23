# 설계

## 목표

서브모듈 기반 의존성을 제거하고 `pywowlib`가 이 저장소만으로 동작하도록 정리한다.

## 결정 사항

### 1. MPQ / StormLib 제거

- `WOD` 미만 WoW 클라이언트 지원을 중단한다.
- `StormLib` 및 `MPQ` 관련 빌드/런타임 경로를 제거한다.
- 자원 접근 경로는 `CASC`만 유지한다.

### 2. `pyCASCLib` 를 `pycasc` 로 대체

- `archives/pycasc` 에 vendored `pycasc` 를 사용한다.
- `archives/casc` 서브모듈 의존성을 제거한다.
- `archives/wow_filesystem.py` 는 기존 `pyCASCLib` API 대신 `pycasc` 를 직접 사용하도록 정리한다.

### 3. `wdbx` 완전 내장화

- 외부 `wdbx/dbd` 서브모듈 의존성을 제거한다.
- 파서와 래퍼 구현은 `wdbx` 내부에 유지한다.
- DBD 정의 데이터는 저장소 내부 자산으로 관리한다.
- `DBDefinition` 은 로컬 저장소 소스만 읽도록 한다.

## 목표 구조

- `archives/wow_filesystem.py`
  - CASC 전용 경로만 유지
  - `MPQFile` import 제거
  - 구 `pyCASCLib` 호환 계층에 의존하지 않음
- `archives/pycasc/`
  - vendored 런타임 구현
- `archives/mpq/`
  - 제거 대상
- `archives/casc/`
  - 제거 대상
- `wdbx/`
  - 파서, 래퍼, 로컬 정의 소스만 유지
- `.gitmodules`
  - 제거하거나 비운다

## 마이그레이션 순서

1. `MPQ` 런타임 및 빌드 경로 제거
2. CASC 접근을 `pyCASCLib` 에서 `pycasc` 로 전환
3. `wdbx/dbd` 외부 정의 소스를 저장소 내부 데이터로 대체
4. 서브모듈 메타데이터와 죽은 경로 정리
5. 문서를 `WOD+` 지원 기준으로 갱신

## `wdbx` 설계 원칙

- 런타임에 `WoWDBDefs` 별도 클론이 필요하면 안 된다.
- 정의 데이터는 vendored `.dbd` 파일, 내장 Python 정의, 또는 둘 다로 구성할 수 있다.
- 런타임 기준의 단일 소스 오브 트루스는 이 저장소여야 한다.

## 비목표

- `WOD` 미만 클라이언트 지원 유지
- `StormLib` / `MPQ` API 호환성 유지
- 서브모듈 기반 의존성 관리 유지

## 완료 조건

- 새 클론에서 `git submodule update --init --recursive` 없이 동작한다.
- 지원 대상 클라이언트의 자원 접근은 `pycasc` 만 사용한다.
- `wdbx` 가 외부 저장소 없이 DB 정의를 해석한다.
