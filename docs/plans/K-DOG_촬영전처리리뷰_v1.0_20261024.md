# K-DOG 촬영·전처리 변경 리뷰

- 날짜: 2026-10-24
- 대상: `veluga/preprocess-tab-only`, `ec58b34` 이후 변경
- 범위: 참가자 전처리 탭, CSV 우선 입력, 중립 영상 출처, 촬영 확정 통합

## 리뷰 결과

카메라 연결·원본 파일·해시·입력 판본·이전 회차와 명시적 변환 출처 보호를 검토했다. 제거한 `AnalysisTargets`, `SessionEditor`의 잔존 호출이 없음을 Graft로 확인했다. 참가자별 실행 필터는 페이지 분할 전에 적용하며, 이전 회차 실행 조회 후 현재 회차 복귀를 검증한다.

수용한 추가 수정: S1 목록의 구간 상태가 `confirmed`만 확인하여 이전·미확인 절차도 확정으로 표시했다. 서버와 촬영 편집 화면의 조건에 맞춰 `s1_confirmed`까지 확인한다. 기존 기록은 변경하지 않는다. 미확인 절차의 목록 초안 표시 → 촬영 화면 재확정 → 목록 확정 표시를 브라우저 회귀에 추가했다.

## 검증 기록

- 집중 백엔드 92건 통과: 전처리 실행·촬영·전처리·업로드·보존 영상·폐기 형식 검사.
- 집중 브라우저 44건 통과: CSV·촬영·업로드·참가자 동선·전처리 실행 복구.
- 상태 표시 오류를 기존 조건으로 재현하고, 미확인·이전·현재 절차의 수정 결과를 확인했다.
- 빌드 통과. 기존 500 kB 번들 경고는 유지된다.
- 전체 브라우저 179개 시나리오의 최종 결과가 모두 통과했다. 전체 실행 177개 통과 후, 빌드와 겹친 재로딩 404 및 연결 갱신 대기 누락 2건은 관련 2개 파일 재실행에서 통과했다. 새로 추가한 재확정 회귀는 참가자 선택 유지 동선과 구간 칸 locator를 바로잡아 별도 통과했다.
- 합성 촬영 화면: [PC](images/촬영확정_PC_20261024.png), [모바일](images/촬영확정_모바일_20261024.png).
- 전체 백엔드 `uv run --locked python -X utf8 -m unittest discover -s tests -q`: 865건, 1135.212초, 실패 0·skip 3. skip을 검증 완료로 간주하지 않는다.
- 변경 문서의 저장소 내부 링크 및 `git diff --check` 통과. `graft build` 후 wiring graph 동기화 확인.
- 병합 대상: [PR #140](https://github.com/syleeVeluga/k-dog-proj/pull/140).

실제 자료의 실행 기록과 산출물은 저장소 밖 운영 경로에 보관한다. 회귀 시험의 합성 입력을 실제 평가 결과로 사용하지 않는다. CSV에 없는 시작 시각·설문·관찰 사실은 임의로 채우지 않는다.

## 버전 확인

2026-10-24 공식 문서와 레지스트리를 확인했다. 최신/선택 버전은 React 19.3.1/19.2.8, FastAPI 0.161.1/0.141.1, Pydantic 2.14.1/2.13.5, Playwright 1.64.1/1.63.0, Vite 8.3.5/8.2.2, TypeScript 7.0.2/7.0.2다. 기존 API와 Python 3.14·Node 24 환경을 사용하며, 이번 수정과 무관한 의존성은 업그레이드하지 않는다. 설치·잠금 변경은 없다.

공식 근거: [React 버전](https://react.dev/versions), [React registry](https://registry.npmjs.org/react/latest), [FastAPI 릴리스](https://fastapi.tiangolo.com/release-notes/), [FastAPI registry](https://pypi.org/pypi/fastapi/json), [Pydantic 릴리스](https://github.com/pydantic/pydantic/releases), [Pydantic registry](https://pypi.org/pypi/pydantic/json), [Playwright 릴리스](https://playwright.dev/docs/release-notes), [Playwright registry](https://registry.npmjs.org/@playwright/test/latest), [Vite 릴리스](https://vite.dev/releases), [Vite registry](https://registry.npmjs.org/vite/latest), [TypeScript registry](https://registry.npmjs.org/typescript/latest).
