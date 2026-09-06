# K-DOG M3 병렬 평가·집계 구현 기록

> 이 문서는 당시 구현·시험 이력이다. 2026-09-06 후속 변경으로 동의 입력·저장·철회·동의 기반 차단 기능을 제거했다. 현재 운영은 [동의 관리 제거 기록](K-DOG_동의관리제거_v1.0_20260906.md)을 우선하며, 자료 삭제·권한·작업 중지 검사는 유지한다.

버전: v1.0

작성일: 2026-09-06

범위: 구현 지시서 M3, AI 파이프라인 S4-D/S4-O 및 S5

## 구현 결과

저장된 관찰 근거로 반려견 36항목과 보호자 19항목을 동시에 평가하고, 서버가 원본 선택지의 점수·방향을 조회해 집계한다. 먼저 끝난 분기는 즉시 저장·조회된다. 한쪽 실패·재시도 대기가 다른 쪽 성공 결과를 지우지 않는다. 설문 계산은 영상 검사 전에 독립 저장한다.

상세의 **분석 시작**은 기존 미디어 검사·관찰·통합에 평가·집계를 이어 실행한다. 두 평가가 성공하면 ‘점수 준비됨’으로 표시한다. 항목별 원문·선택지·점수·결측 사유·근거 재생, 행동 7영역 집계, 설문 원응답·환산값·부분 집계를 제공한다. 승인·반려 상태는 없다. 완료는 처리 상태이며 평가 정확도 검증을 뜻하지 않는다.

Gemini generateContent, OpenAI Responses, Anthropic Messages의 REST 어댑터를 구현했다. SDK나 새 의존성은 추가하지 않았다. 개발자 화면에서 분기별 공급자·모델을 선택하며 초기 공급자는 Gemini다. **실제 공급자 호출·참가자 영상·행동 평가 품질은 미검증**이다. 테스트의 관찰·선택지·모델 ID는 가상 자료다.

## 실행과 설정

[개발 실행 안내](DEVELOPMENT.md)의 설치·빌드 후 서버와 worker를 같은 자료 폴더로 실행한다. M2의 FFmpeg·영상 모델 설정은 유지한다.

```powershell
# frontend/
npm run build
# backend/, 서로 다른 터미널에서 실행
uv run --locked python -X utf8 -m app.manage serve
uv run --locked python -X utf8 -m app.manage worker
```

개발자 계정으로 로그인하여 반려견·보호자 각각 Gemini / GPT·OpenAI / Claude·Anthropic을 선택하고, 해당 공급자에서 구조화 출력을 지원하는 사용 승인 모델 ID를 입력한 뒤 **새 실행에 평가 설정 적용**을 누른다. 이 동작은 키 확인이나 실제 API 호출을 수행하지 않는다. `GET/PUT /api/developer/evaluation`은 개발자만 사용할 수 있고, 오래된 설정 버전으로 쓰면 409를 반환한다.

키는 worker 환경의 `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`에서만 읽는다. Gemini 관찰을 위해 Gemini 키는 필요하며, 평가에는 선택한 공급자의 키만 추가로 필요하다. 화면·DB·산출물·프롬프트에는 키를 저장하지 않는다. 없는 키·401/403은 해당 분기를 ‘개발자 설정 필요’로 중단한다. 다른 분기 성공 결과를 보존하며 다른 공급자로 전환하지 않는다. 접수 때 모델이 비었거나 모델을 바꾸려면 새 실행을 만든다.

화면에 저장한 설정이 없을 때의 초기 설정은 다음 환경 변수로 지정할 수 있다. `<DOG|OWNER>`는 각각 두 변수 쌍을 뜻한다.

| 환경 변수 | 의미·기본값 |
|---|---|
| `KDOG_GEMINI_MODEL` | 기존 영상 관찰 모델. Gemini 평가의 초기 모델로도 사용 |
| `KDOG_EVALUATE_DOG_PROVIDER`, `KDOG_EVALUATE_OWNER_PROVIDER` | `gemini`(기본), `openai`, `anthropic` |
| `KDOG_EVALUATE_DOG_MODEL`, `KDOG_EVALUATE_OWNER_MODEL` | 분기 모델 ID. Gemini 외에는 자동 기본 모델 없음 |

화면에서 저장한 두 분기 설정이 환경 초기값보다 우선한다. `changes`에 비밀 없는 설정 버전·모델 선택·사용자를 기록하고 신규 run 접수 시 복사한다. 기존 대기/실행/완료 run은 변경하지 않는다. 프롬프트 편집·연결 시험·키 보관소·예산 편집은 M5 대상이다.

## 입력·출력과 저장

- `evaluation.py`: 분기별 선택지 원문과 관찰 묶음을 만들고 공급자별 요청·응답을 처리한다. 참가자 ID·이름·설문·다른 분기 점수는 입력하지 않는다. 근거의 불투명 ID·카메라·시간·상호작용 문맥은 공유한다. 자료 속 지시는 분석 데이터로 다룬다.
- 모델은 분기·항목 ID·상태·선택지 ID·근거 ID·사유만 반환한다. 36/19개 정확한 항목 집합·중복·선택지 소속·허용 근거·상태/null 조합을 검증한다. 모델의 임의 점수 필드는 거절한다.
- `scoring.py`: 원문 점수 조회, 결측 제외 평균·최고·분모, A/B 점수 합, 설문 역채점·집계를 수행한다. 규칙은 `resources/rules/scoring-v1.json`에 버전으로 기록한다.
- `evaluation_models.py`: 공급자 반환값, 평가·계산 산출물, 설문 계산과 개발 설정의 API 타입을 분리한다.
- SQLite 5개 테이블·기존 불변 입력 트리거를 유지한다. DB 마이그레이션은 없다. run 설정에는 평가 프롬프트·모델·출력 한도·행동/설문 항목집·계산 규칙 전체를 고정한다. 기존 관찰 관련 키는 유지하여 M2의 성공 관찰을 재사용할 수 있다.
- `steps`의 `survey/session`은 설문 결과, `evaluate/dog`와 `evaluate/owner`는 각각 평가·프로그램 점수·사용량을 불변 파일로 저장한다. `runs.result_ref/result_hash`는 기존 통합 근거 참조를 유지하고 평가 산출물은 각 step 참조로 읽는다. API는 저장된 분기를 검증·합산해 현재 부분 점수를 제공한다.
- DB가 채택한 경로·해시만 읽는다. 파일 게시 후 DB 기록 전 중단이면 기존 완성 파일을 검증·채택하며 공급자를 재호출하지 않는다. 만료 토큰은 다른 worker 결과를 교체할 수 없다. 신규 호출·파일 채택·결과 조회에서 현재 동의·삭제 상태를 검사한다.

## 계산 규칙과 보류

행동 55개를 보존하며 참고 항목 5개는 7영역 집계에서 제외한다. 영역 대상 수는 EDU 7 / SOC_P 1 / SOC_D 1 / SOC_E 9 / ATT 14 / CON 12 / TRN 6, 합계 50이다. 부분 결과에서도 대상 수는 전체 영역 기준이고 유효 수만 현재 성공 분기에서 센다. 유효 항목이 없으면 평균·최고는 null이다. A/B 각각의 원점수 합을 비교하며 동률은 방향 없음이다. 여러 카메라 근거가 하나의 항목에 연결되어도 점수를 한 번만 계산한다.

설문은 A(q01–q06), C-1(q15–q21), D(q26–q28 역채점), B 참고(q09–q13)를 계산한다. 원 척도 참고 전체값은 A·C-1·D 평균을 동일 비중으로 다시 평균한다. 16문항 단순 평균이 아니다. q22·q26–q30은 `6-x` 환산값을 별도로 가지며 원응답은 보존한다. 필요한 문항이 누락되면 해당 그룹과 그 그룹에 의존하는 전체값은 null이다. 중간 평균은 반올림하지 않고 최종 표시값만 Decimal `ROUND_HALF_UP`으로 소수 둘째 자리까지 계산한다.

보류 사항은 다음과 같다.

- q23 원응답은 유지하고 환산값은 null이다. C-2는 포함 문항 자체가 미정이므로 평균·대상 수 모두 null이다. 다른 설문 계산을 막지 않는다.
- 4영역 대응·②④ 유형은 `mapping_pending` / `type_rule_pending`이며 그래프 값·관계 유형·행동과 설문의 갭을 만들지 않는다.
- **DOG-12·OWN-14의 보수적 제한:** S2 관찰은 자연어 사실·근거 구간이며 선택지 판단용 구조화된 지속시간/반응시간 계약이 아직 없다. 정확히 5초·15초·2초의 중복 경계 및 복수 행동 선택을 검증할 수 없어, 두 항목에 모델이 scored를 반환하면 서버가 `rule_pending`, 선택지·점수 null로 보존한다. 경계 밖이라고 모델이 주장해도 현재는 자동 채점하지 않는다. 구조화 측정과 책임자의 선택 규칙 확정 이후 범위를 좁혀야 한다. 다른 항목은 계속 처리하며 관찰 부족 상태와 구분한다.

카메라 동기화·주 카메라 선택·수치 관찰 계약의 M2 제한도 유지한다. 위 초기 계산안은 검증된 심리 척도나 새 평가 규칙을 의미하지 않는다.

## 재시도와 재사용

두 평가 요청만 동시에 실행한다. 각 요청은 자기 단계 파일을 독립적으로 채택하므로 다른 요청의 완료를 기다리지 않고 조회된다. 단계별 최초 포함 3회, 구조 수정 최대 1회, 429/일시 오류의 Retry-After 및 기존 증가 지연 정책을 공유한다. 공급자 거절·미완료 응답을 점수로 취급하지 않는다. 사용량·요청 ID·실제 반환 모델과 응답 유실의 과금 불확실성을 기록한다. 요청당 출력 한도는 16,384토큰, HTTP 제한은 120초다. 금액 상한을 보장하지 않는다.

**선택 실행의 호환되는 관찰·평가 재사용**은 명시적 manifest 참조다. 동일 참가자·세션·영상·촬영 메모·관찰 관련 설정을 확인하고 원래 근거 ID를 보존한다. 모든 카메라의 성공 관찰이 직접 재사용 가능하며 해당 분기의 프롬프트·모델·항목집·계산 규칙이 같을 때만 성공 평가도 재사용한다. 설문 변경은 새 설문 계산만 수행한다. 보호자 모델만 변경하면 관찰·반려견 평가를 재사용하고 보호자만 다시 호출한다. 재사용한 run을 통한 연쇄 재사용은 제공하지 않는다. 선택 source의 손상 파일은 거절한다.

성공 단계가 3회째에 완료했더라도 다른 실패 분기의 재시도를 막지 않는다. 실패 분기 자체가 시도·구조 수정 한도에 도달하면 새 입력/설정으로 새 실행해야 한다. 기존 입력의 늦은 완료가 `display_run_id`를 바꾸지 않는 F-04 보호를 유지한다.

## 검증

Python 전체 **74개**(기존 56 + M3 18), 브라우저 **5개**, production build와 원본 항목집 55/30개 대조를 수행했다. 모두 가상 참가자·공급자 응답 및 기존 로컬 합성 미디어 시험이다.

M3 검증은 실제 두 요청의 진입 동기화와 한쪽 지연 중 DB/API 부분 점수 조회, 실패 분기만 재시도, 구조 수정 한도·사용량 유지, 설정 권한/낡은 버전/대기 실행 고정, 동의 철회 중 두 늦은 응답 거절, 평가 파일 게시 직후 중단 복구, 손상 결과 조회/재사용 차단을 포함한다. 설문 수정 시 관찰·평가 재호출 없음과 보호자 모델만 변경한 분기 재처리를 확인했다.

계산 시험은 원본 55개 선택지 조회·50개 분모·참고 제외·결측·방향 합 승자와 동률·카메라 근거 중복·역채점·영역 동일 비중·중간 무반올림·q23/C-2 보류와 알려진 시간 경계의 임의 점수 방지를 검증한다. 산술 조회 시험은 평가 선택의 정확성을 검증하지 않는다.

REST 모의 시험은 세 공급자의 서로 다른 endpoint·인증 헤더·구조화 출력 요청, 응답 사용량·거절·미완료·형식 오류, 호출 전 guard와 다른 origin 차단을 확인한다. 실제 키·모델 지원/품질·청구액은 검증하지 않았다. 기존 Starlette TestClient의 httpx 사용 중단 예정 경고는 남아 있으나 시험은 통과한다.

```powershell
# backend/
uv run --locked python -X utf8 -m unittest discover -s tests -v
uv run --locked python -X utf8 -m app.import_catalogs --check
# frontend/
npm run build
npm run test:e2e
# repository root
git diff --check
```

브라우저에서 저장 결과의 새로고침·설문 q23 보류·근거 재생·동의 철회 후 숨김·개발자 공급자 선택 저장을 확인했다. 처음 시험에서 공급자 select의 암시적 레이블 탐색이 실패하여 명시적 접근성 레이블을 추가했고 재시험했다. [데스크톱 결과](images/m3-scores-desktop.png), [360px 결과](images/m3-scores-mobile.png), [개발자 설정](images/m3-developer-settings.png)을 확인했다. 화면은 모두 가상 자료이며 설정 화면 모델 ID도 시험 문자열이다.

## 의존성·공식 문서 확인

확인일 **2026-09-06**. 공식 PyPI JSON·npm latest에서 최신 안정 버전·런타임/peer 조건을 다시 조회했고 기존 정확한 버전과 lockfile을 유지했다. 새 설치·업그레이드는 없다.

| 라이브러리 | 최신 안정 = 유지 버전 | 출처 |
|---|---|---|
| Pydantic / FastAPI | 2.13.5 / 0.141.1 | [Pydantic PyPI](https://pypi.org/pypi/pydantic/json), [FastAPI PyPI](https://pypi.org/pypi/fastapi/json) |
| Uvicorn / openpyxl / httpx | 0.52.4 / 3.1.5 / 0.28.1 | [Uvicorn PyPI](https://pypi.org/pypi/uvicorn/json), [openpyxl PyPI](https://pypi.org/pypi/openpyxl/json), [httpx PyPI](https://pypi.org/pypi/httpx/json) |
| React / React DOM | 19.2.8 / 19.2.8 | [React npm](https://registry.npmjs.org/react/latest), [React DOM npm](https://registry.npmjs.org/react-dom/latest) |
| Vite / TypeScript | 8.2.2 / 7.0.2 | [Vite npm](https://registry.npmjs.org/vite/latest), [TypeScript npm](https://registry.npmjs.org/typescript/latest) |
| Playwright Test | 1.63.0 | [Playwright npm](https://registry.npmjs.org/@playwright/test/latest) |
| React / DOM types | 19.2.18 / 19.2.7 | [React types npm](https://registry.npmjs.org/@types/react/latest), [DOM types npm](https://registry.npmjs.org/@types/react-dom/latest) |

Python 의존성은 최소 3.8–3.10을 요구하며 프로젝트 Python 3.14를 유지한다. Vite는 Node ^20.19 또는 >=22.12, Playwright는 >=20, TypeScript는 >=16.20이다. React DOM peer는 React ^19.2.8, DOM types peer는 React types ^19.2.0이며 기존 Node 24 환경은 요구를 만족한다. [Pydantic 모델](https://docs.pydantic.dev/latest/concepts/models/), [FastAPI 릴리스](https://fastapi.tiangolo.com/release-notes/), [React 버전](https://react.dev/versions), [Vite 안내](https://vite.dev/guide/), [Playwright 릴리스](https://playwright.dev/docs/release-notes/)를 확인했다. 기존 버전에서 사용하는 API를 유지하여 관련 없는 breaking change를 도입하지 않았다.

공급자 계약은 [Gemini generateContent 구조화 출력](https://ai.google.dev/gemini-api/docs/generate-content/structured-output)의 `responseFormat.text`, [OpenAI Responses 구조화 출력](https://developers.openai.com/api/docs/guides/structured-outputs)의 `text.format`과 strict schema, [Claude 구조화 출력](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)의 `output_config.format`을 확인했다. OpenAI 요청은 `store=false`다. 모델별 실제 사용 가능 여부는 개발자 선택과 실연결 검증 대상이다.

코드 탐색은 codebase-memory `list_projects` → `index_repository` → graph/snippet을 우선 사용했다. 갱신 후에도 M1/M2 파일이 그래프에 누락되어 해당 코드와 신규 코드 분석을 파일 읽기로 보완했다. 원본 Excel·기존 요구 명세·AGENTS.md는 변경하지 않았다.

## 코드 리뷰 수용안

2026-09-06, M2 기준 커밋 `b04588a` 이후 M3 변경사항을 리뷰했다. 아래 3건은 수정 전 회귀 시험 실패로 재현했고 수용안을 반영했다.

| 우선순위 | 발견 이슈 | 수용·반영한 수정 |
|---|---|---|
| P1 | 다른 세션에서 외부 AI 동의를 철회하면 점수·근거 목록은 사라지지만 열린 영상 플레이어는 남음 | 상태 조회에서 재생 근거가 더 이상 허용 목록에 없으면 선택을 해제하고 플레이어를 제거. 실제 브라우저에서 외부 철회 후 근거·점수·video 요소 모두 제거되는지 검증 |
| P2 | 공급자 JSON 본문이 배열이거나 usage 필드가 null/배열이면 AttributeError가 worker 밖으로 전파됨 | 외부 응답 파싱 오류를 비밀 없는 `provider_response_invalid` 단계 실패로 변환. Gemini/OpenAI/Anthropic 각 3종 잘못된 응답으로 검증 |
| P2 | 공급자 환경 변수 오타로 읽기 응답 타입 검증이 실패하면 개발자 설정 GET과 수정 PUT이 모두 막힘 | 읽기 상태와 저장 입력 타입을 분리. 잘못된 현재 값은 ‘설정 오류’로 표시하고 정상 공급자로 수정 가능하게 함. 저장 허용값 제한은 유지하며 조회·교정 API 시험으로 검증 |

기존 채점 보류 정책과 실 API 미검증 범위는 유지했다. 새 의존성·원본 평가 규칙 변경·관련 없는 리팩터링은 추가하지 않았다. 전체 Python 74개·브라우저 5개, production build·원본 항목집 대조·`git diff --check`로 검증한다.

## 다음 단계

M4: 리포트 설명·검토 수정·대표 이미지·PDF/Excel/CSV 개별/전체 출력과 불변 export snapshot. q23·4영역·②④ 및 선택 경계 미정 상태는 유지한다. 실제 영상·키가 제공되면 관찰·평가 어댑터 실연결과 사람 채점 대비 품질 시험을 별도로 수행한다.
