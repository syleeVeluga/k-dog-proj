# K-DOG 360 통합 MP4 구현 실행 기록

버전: v1.0 · 2026-10-12 · 상위: [전체 계획](K-DOG_360통합MP4업로드계획_v1.0_20261012.md)

## MP01 계약·보관·분석 입력 경계

착수 기준은 ES03 [PR #89](https://github.com/syleeVeluga/k-dog-proj/pull/89) 병합 `5ef483f`다. 브랜치는 `veluga/mp01-external-360-media`다.

- `external_360_mp4`는 MP4·typed external_processing·부모0·conversion null로 접수한다. 기존 종류의 부모 요구와 기존 null 직렬화를 유지한다. EXT360/null 원본 번호를 서버에서 검사한다. DB 테이블 재구축·이전 점수 이관·산식 변경은 없다.
- PATCH는 같은 video/upload/hash의 새 입력 판본으로 처리 정보만 정정한다. 원래 receipt request_json/hash/link_json와 이전 manifest는 보존한다. 현재 actor·로그인 세션·선택 회차·revision·파일 identity/hash·불변 출처를 저장 직전에 재확인한다. 시간 근거에 쓰인 timeline 정정은 촬영 재확정을 요구한다.
- flat/preserved만 클립 후보다. 나머지는 conversion_required와 파일별 사유로 남는다. projection과 timeline은 별개다. 펼침/preserved는 촬영 시간 근거로 사용할 수 있다. edited/unknown의 기준·사건·coverage·확정 offset은 촬영 확정 및 전처리에서 거절한다. 값 없는 offset과 초안은 보존한다.
- 고정 batch 검증은 해당 manifest 판본의 유효 metadata와 source snapshot을 대조한다. 현재 입력 재사용과 과거 pin 제공을 구분한다. revision 변경 guard·ES 실행별 actor/result pointer와 이력을 유지한다.
- 새 시험 `backend/tests/test_external_media_v4.py`는 단일 파일 공유 등록/재시작·정정·기존 canonical JSON·보존 파일 등록·9조합·영상 전송 후보 제외·시간 앵커·과거 실행/outdated·진행 중 정정 guard·backup/restore/clean을 검증한다. 합성 bytes/FFmpeg 영상과 기존 fixture만 사용했다. 유료/실제 외부 공급자 요청0이다.

독립 reviewer `mp01_cold_review`가 읽기 전용 검토했다. 아래 2건을 수용했고 보류/거절0이다.

| 발견 | 결정과 수정 |
| --- | --- |
| CR-IMP01 / P2: PATCH가 request hash·kind/camera/binding 손상을 거절하지 않음 | 수용. `_external_source`로 읽기/쓰기 양 단계의 원장 해시·불변 출처를 대조하고 hash 검사 중 JSON/hash/binding 변화도 거절한다. 최초 external_processing과 유효 metadata는 등치하지 않는다. 변조 및 로그인 변경 회귀 추가 |
| CR-IMP02 / P2: 선택 expected_sha256과 실제 hash 대조 누락 | 수용. 선언 hash가 있으면 실제 SHA-256과 대조한다. linked state·scope·binding 대상도 검사하고 변조 회귀 추가 |

시험 fixture의 frozen model 직접 변경·누락 evidence_id·restore 인자·clean 예외 기대는 실제 기존 계약에 맞춰 수정했다. 제품 변경을 위해 기존 보관 정책을 느슨하게 하지 않았다.

기존 지정 회귀111개와 새 계약/합성8개가 통과했다. 최초 통합 실행117개/431.794초에서 clean 시험의 기대 예외1건만 실패했고, fixture 수정 뒤 신규7개/21.582초·보존등록1개/1.180초를 통과했다. 수용 수정 후 API4개/4.990초, 최종 request ID·scope·binding·hash 변조7종/로그인 race1개/1.577초도 통과했다. 기존 입력·수신·촬영·전처리·보관·업무권한·ES 실행 조회 회귀에 제품 실패는 없었다. 중복 실행은 고유 시험 개수에 더하지 않았다.

reviewer는 두 수용 건의 코드상 해결과 신규 독립 결함0을 확인했다. 마지막 원장 request ID 대조 권고도 같은 범위로 수용·시험했다. `git diff --check` 통과. PR/commit/병합은 아래에 연결한다.

## 의존성 확인 — 2026-10-12

| 대상 | 최신 안정판 / 선택 잠금판 | 근거 |
| --- | --- | --- |
| Pydantic | 2.14.1 / 2.13.5 | [PyPI](https://pypi.org/pypi/pydantic/json), [선택판](https://pypi.org/pypi/pydantic/2.13.5/json), [model serializer](https://docs.pydantic.dev/latest/concepts/serialization/) |
| FastAPI | 0.143.0 / 0.141.1 | [PyPI](https://pypi.org/pypi/fastapi/json), [선택판](https://pypi.org/pypi/fastapi/0.141.1/json), [PATCH](https://fastapi.tiangolo.com/tutorial/body-updates/), [release notes](https://fastapi.tiangolo.com/release-notes/) |
| HTTPX | 0.28.1 / 0.28.1 | [PyPI](https://pypi.org/pypi/httpx/json) |
| React/react-dom | 19.3.0 / 19.2.8 | [React versions](https://react.dev/versions), [React registry](https://registry.npmjs.org/react/latest), [DOM registry](https://registry.npmjs.org/react-dom/latest) |
| Playwright | 1.64.0 / 1.63.0 | [registry](https://registry.npmjs.org/@playwright/test/latest), [release notes](https://playwright.dev/docs/release-notes) |
| Vite | 8.3.4 / 8.2.2 | [registry](https://registry.npmjs.org/vite/latest) |
| TypeScript | 7.0.2 / 7.0.2 | [registry](https://registry.npmjs.org/typescript/latest) |

기존 Python3.14/Node 잠금 조합을 유지한다. 선택 Pydantic은 Python>=3.9, FastAPI는 >=3.10·Pydantic>=2.9이며 프로젝트 Python3.14와 호환된다. 최신 React DOM은 React^19.3.0을 요구하므로 관련 없는 업그레이드를 섞지 않는다. Playwright 최신 Node>=20, Vite 최신 Node^20.19 또는 >=22.12, TypeScript Node>=16.20 조건을 확인했다. 새 의존성·SDK·잠금 파일 변경은 없다. 선택판 UI API/peer와 실제 runtime은 MP02에서 대조한다.

## 실제 파일·현장 인수

실제 Studio 파일이 제공되지 않았다. 360 직접 AI 시야/미세 행동 판독, 원본 대비 품질, 장시간 오디오/시각 정확도, GB급 성능은 미실행이며 [실측 후속 대장](../../archive/개발반영_20261003/K-DOG_실측및확인후속대장_v1.0_20261003.md)의 E01~E05/P01을 따른다. 합성 기술 인수를 실측 완료로 표시하지 않는다.
