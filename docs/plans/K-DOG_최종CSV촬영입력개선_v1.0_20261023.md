# K-DOG 최종 CSV 촬영 입력 개선

버전: v1.0 · 2026-10-23 · 기준: `main / be77464` · 브랜치: `veluga/final-segments-csv-20261023` · 상태: 구현·국소 검증·독립 cold review 완료

## 결정과 적용 범위

2026-10-23 사용자는 [최종 segments.csv](확정%20영상%20및%20구분_20261014/segments.csv)를 기준으로 CSV 입력을 접힌 영역 밖에 노출하고, 입력·확정 조건을 맞춘 뒤 검증 → 독립 cold review(subagents) → 병합하도록 지시했다. 이 결정은 [VC03](4카메라구간CSV전환_20261014/K-DOG_PR-VC03_구간CSV가져오기_v1.0_20261014.md)의 퇴장 끝·걷기 6국면 필수 확정 조건을 대체한다. S1 채점 산식·관찰량 조건은 변경하지 않는다.

최종 파일은 별도 자동 구간 계획 브랜치의 `07c42aa`에서 교체한 5_2 회차 자료다. 이번 브랜치는 그 CSV만 반영하며 자동 분석 계획·스파이크 구현은 포함하지 않는다. 기존 `frontend/tests/fixtures/segments-sample.csv`는 이전 형식 회귀 자료로 유지하고, 새 최종 기준 시험은 위 원본 파일을 직접 읽는다. 과거 실행 기록의 수치·hash는 당시 샘플에 대한 이력이며 현행 값으로 덮어쓰지 않는다.

| 조건 | 적용 |
| --- | --- |
| 입력 위치 | 기준 영상 아래, `실제 8구간` 접힘 영역 밖에 CSV 입력·결과·안내 표시 |
| 기본 확정 | 실시 1~7구간의 시작·끝, 퇴장 시작 필요. 미실시는 기존 상태·사유 규칙 유지 |
| 퇴장 끝 | CSV에 없으므로 null 허용. 영상 길이·예정 길이로 생성하지 않음 |
| 걷기 상세 | 국면 레코드 없음 또는 모든 국면 시각 미입력 허용. 시각을 입력하면 기존 6국면 완결·순서·범위·연속성 검증 유지 |
| 직접 입력 | CSV와 같은 서버 확정 조건 적용. CSV 파일명·메모 문자열로 검증 우회하지 않음 |
| 상세 관찰 | 사건·관찰 근거·꼬리·개59·안전기지 입력 보존. 근거 없는 창은 미관찰, 관찰 초·점수 생성 없음 |
| 보호 | hash·영상 범위·회차 참조·수정 revision·실제 actor·비동기 CSV 경합 검증 유지 |

## 최종 파일 대조

CAM1 시작: `5.602 / 49.392 / 83.825 / 129.484 / 156.711 / 187.812 / 240.341 / 329.336`초. 1~7구간 끝은 다음 시작, 퇴장 끝은 null이다. CAM1 기준 평균 offset은 CAM2 `+0.067`, CAM3 `−0.048`, CAM4 `+0.100`초다. `경과초(녹화시작기준)` 대신 선택 카메라의 `CAMk_영상초`를 사용한다.

검증에 사용한 checkout 파일은 846bytes/LF, SHA-256 `8f003fab3cabf04044f41ea4276c57d74e7300edfec1c18e472995bde1ba66af`다. 최초 원인 분석 당시 작업트리의 CRLF 파일 hash `d90d5d3dc2e682fc814e22649d60e9225013366ca7c75835539c6863dbf9e39d`와 구분한다. 시험 영상은 350초 합성 영상이며 실제 참가자 영상·외부 AI는 사용하지 않는다.

## 검증과 검토

- `frontend/`: `npm run build` 통과(기존 500kB 번들 안내 유지).
- `backend/`: `python -m uv run --locked python -X utf8 -m unittest tests.test_recording_v4 tests.test_recording_api_v4 -v` 28건 통과.
- `backend/`: `python -m uv run --locked python -X utf8 -m unittest tests.test_preprocess_v4 tests.test_scoring_v4 tests.test_scoring_ai_v4 tests.test_sheets_v4 -v` 74건/50.263초 통과. 퇴장 끝·국면 없는 8구간의 실제 합성 영상 전처리 성공, 해당 관찰창 미관찰 유지 포함. 앞의 28건(10.103초)과 합계 102건이다.
- `frontend/`: `npm run test:e2e -- segments-csv.spec.ts recording-v4.spec.ts recording-split-v4.spec.ts copy-guard.spec.ts` 25건/1.1분 통과. 최종 CSV 직접 읽기→확정200→재조회, 상세 후입력, 이전 판본/파일·미실시 보존, 비동기 경합, CAM3 변경, 잘못된 CSV 거절 포함.
- [1440px](K-DOG_최종CSV촬영입력_1440_20261023.png)·[390px](K-DOG_최종CSV촬영입력_390_20261023.png): 합성 영상·대상만 사용. 접힌 영역 밖 CSV 입력, 미확인 상세 안내, 가로 넘침 없음을 자동 검사하고 이미지를 직접 확인했다.
- 전체 회귀·실제 AI 품질·실제 참가자 영상 실측을 완료했다고 주장하지 않는다. 기존 FastAPI testclient deprecation 안내와 빌드 번들 안내는 이번 변경 범위 밖이다.
- 독립 cold review: 두 에이전트가 읽기 전용으로 별도 검토했다. 서버·전처리·채점 소비자 검토 0건, 화면·CSV·시험·문서 검토 0건의 actionable finding. 수용 수정·보류·거절 각 0건. 서버 검토는 국면 없는 개38~43 근거를 `sheets_v4._source_evidence`가 거절하는 것도 확인했다. UI 검토는 두 폭의 화면과 비동기 경합·편집 잠금·기존 수동 기록 보존을 확인했다. 검토자가 전체 시험이나 실제 공급자 실측을 수행한 것은 아니다.

이 환경은 `uv`가 기본 PATH에 없어 같은 설치본을 `python -m uv`로 실행했다. 브라우저 테스트에는 설치된 uv 실행파일 디렉터리를 해당 프로세스의 PATH에 추가했다. 의존성을 새로 설치하지 않았다.

## 라이브러리 확인 (2026-10-23)

공식 registry·문서·릴리스 확인 후 기존 lock을 유지했다. 이번 변경은 기존 JSX·state·model validator·브라우저 파일 입력 API 범위이며, 별도 의존성 업그레이드는 하지 않는다.

| 라이브러리 | 최신 안정판 확인 | 선택한 기존 버전 | 근거 |
| --- | --- | --- | --- |
| React / React DOM | 19.3.1 | 19.2.8 / 19.2.8 | [npm](https://registry.npmjs.org/react/latest), [React 릴리스](https://github.com/react/react/releases), [state API](https://react.dev/reference/react/useState). DOM peer `react ^19.2.8` 충족 |
| Pydantic | 2.14.1 | 2.13.5 | [PyPI](https://pypi.org/project/pydantic/), [선택판](https://pypi.org/project/pydantic/2.13.5/), [릴리스](https://github.com/pydantic/pydantic/releases), [validator API](https://docs.pydantic.dev/latest/concepts/validators/). 기존 Python 3.14.6 사용 |
| Playwright | 1.64.1 | 1.63.0 | [npm](https://registry.npmjs.org/@playwright/test/latest), [릴리스](https://playwright.dev/docs/release-notes), [입력 API](https://playwright.dev/docs/input). Node ≥20 요구, 실제 Node 24.18.1 |
| TypeScript | 7.0.2 | 7.0.2 | [npm](https://registry.npmjs.org/typescript/latest), 기존 컴파일러 사용 |
| Vite | 8.3.5 | 8.2.2 | [npm](https://registry.npmjs.org/vite/latest), [호환성](https://vite.dev/guide/). Node ≥22.12 요구 충족 |

최신 React DOM은 React ^19.3.1을 요구하므로 한쪽만 올리지 않는다. Pydantic 2.14의 Python 3.9 지원 종료·새 Python 지원은 이번 앱 Python 범위를 변경할 이유가 아니다. 기존 API 범위에서 검증하며 manifest/lock 변경은 없다.
