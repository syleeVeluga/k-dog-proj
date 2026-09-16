# PR-R08 인쇄·전달과 패키징·운영 문서

버전: v1.0 · 2026-09-16 · 상태: 구현 계획 · 의존: [R06](K-DOG_PR-R06_리포트메뉴_v1.0_20260916.md) · 고객 확인 Q-R3·Q-R4

상위: [리포트 구현 계획](K-DOG_리포트_구현계획_v1.0_20260916.md). 근거: 06b `00_읽어주세요` 「브라우저로 열어 보세요. 인쇄하면 A4 2~3장」, 01 §1 ⑥ 「PDF 또는 웹 링크」, 01 §7 개인정보(「보호자 이름·연락처는 어떤 파일에도」 — 연구 파일 기준; 리포트는 보호자 본인에게 가는 문서), 변경검토 §6 P4 「리포트 전달 방식은 고객 결정 대기」, P1 계획 §6 PR-11(패키징·리허설 방식).

## 목적

승인된 리포트를 **보호자에게 건네는 형태**로 만든다: A4 2~3장 인쇄 검증, 행사 단위 승인본 묶음 내려받기, 시작 요건·릴리즈·운영 문서·리허설 확장. 웹 링크 전달은 고객 회신(Q-R4) 전까지 만들지 않는다.

## 설계 결정

1. **PDF는 브라우저 인쇄로 만든다.** reportlab 재작성은 06b 디자인을 잃고, 헤드리스 브라우저 동봉(Playwright/Chromium ≈ 150 MB)은 운영 PC 설치 요건을 키운다. 운영 절차는 「새 탭에서 열기 → Ctrl+P → PDF로 저장 / 인쇄」. 프로그램은 `@media print` CSS(R03)로 A4 2~3장을 보장하고, 이 PR에서 실제 페이지 수를 확인한다. 헤드리스 변환은 고객이 「PDF 파일 일괄 생성」을 요구할 때 별도 PR로 검토한다(그때 버전 검증·용량·오프라인 조건을 PR 본문에 기록).
2. **행사 묶음은 승인본만.** `GET /api/events/{event_id}/reports.zip`(writer): `report_status=approved`인 참가자의 승인 HTML(standalone 렌더)을 `{순번:02d}_{참가자ID}_리포트.html`로 담는다. 파일명에 보호자·반려견 이름 없음(파일 목록만 봐도 개인정보가 드러나지 않게). 미승인·이전 입력 기준 참가자 목록은 `00_목록.csv`(순번·참가자ID·상태)로 함께 넣는다.
   **인쇄용 묶음** `GET /api/events/{event_id}/reports.print.html`(writer): 같은 승인본을 순번 순으로 한 HTML에 이어 붙이고 리포트 사이에 `break-before: page`를 둔다. 운영자가 72개 파일을 하나씩 열어 인쇄하는 대신 새 탭 하나에서 Ctrl+P 한 번으로 전부 인쇄한다. 각 리포트 첫 장 머리에 순번을 작게 넣어 배부 시 접수 목록과 맞춘다. 선택한 참가자만(`?participants=…`)도 가능.
3. **연구용 내보내기와 분리.** 이 ZIP은 보호자 전달용이며 N10(원자료·파생값·설문)과 섞지 않는다. `exports.py` 기계는 쓰지 않고 `zipfile`로 직접 만든다(스냅샷·잠금이 필요 없는 읽기 전용 묶음).
4. **글꼴.** R03은 NanumGothic만 썼다. 제목 명조(06b Gowun Batang)를 동봉할지 여기서 결정한다: Google Fonts OFL 원본을 `resources/fonts/`에 추가하고 README·SHA-256·`launcher.REQUIRED` 갱신, 앱 내 미리보기만 사용(단독 파일은 시스템 글꼴). 동봉하지 않으면 CSS의 명조 스택을 `'Nanum Myeongjo','Batang',serif`로 유지.

## 변경 범위

| 파일 | 구분 | 내용 |
| --- | --- | --- |
| `resources/report/report-v2.css` | 변경 | 인쇄 검증 결과 반영: `@page{size:A4;margin:16mm}`, 장 머리 `h2{break-after:avoid}`, 차트·카드 `break-inside:avoid`, 표지 뒤 강제 개행 없음(06b는 이어 흐름), 다크 모드 인쇄 무효, 링크 색 제거 |
| `backend/app/report/store.py` | 변경 | `event_bundle(store, event_id, participants=None) -> bytes`(승인본 standalone 렌더 + 목록 CSV), `print_bundle(store, event_id, participants=None) -> str`(이어 붙인 인쇄용 HTML), 삭제 요청 참가자 제외, 각 HTML 해시를 목록 CSV에 기록 |
| `backend/app/api.py` | 변경 | `GET /api/events/{event_id}/reports.zip`·`GET /api/events/{event_id}/reports.print.html`(writer; 리포트 HTML과 같은 자체 CSP), `GET /api/events`(reader: 행사 ID·참가자 수·승인 수·다시 만들기 필요 수 — 리포트 메뉴 머리에 표시) |
| `frontend/src/pages/Report.tsx` | 변경 | 머리에 행사 선택 + 「승인본 묶음 내려받기」「승인본 모두 인쇄(새 탭)」(writer; 승인 수와 미승인 수를 버튼 옆에 표시), 미리보기 옆 「새 탭에서 열기 → 인쇄(Ctrl+P)」 안내와 브라우저 인쇄 설정(A4·여백 기본·배경 그래픽 켬) 한 줄, 인쇄 미리보기 확인 체크리스트(A4 2~3장·잘린 그림 없음) |
| `backend/app/launcher.py` | 변경 | `REQUIRED`에 (동봉 시) 추가 글꼴. R04에서 넣은 `report-v2.json`·`report-v2.css` 확인 |
| `scripts/rehearsal.py` · `backend/tests/test_rehearsal.py` | 변경 | 리허설 단계 추가: 합성 채점 시트를 `POST /sheets`로 저장(05 6쌍 값을 72쌍에 순환 배정, 채점 화면 대신 리허설 스크립트가 API를 직접 호출) → 리포트 선택 일괄 생성(worker `once()` 반복, 서술 없음) → 승인 → 행사 묶음 ZIP·인쇄용 HTML. 단계별 시간·HTML 크기·장 수 분포를 JSON 보고서에 추가. 72쌍 기준 목표 시간을 PR 본문에 기록 |
| `scripts/build_release.py` · `verify_release.py` | 변경 | `resources/report/`·`resources/reference/`(있으면)·글꼴 포함, 누출 필터에 `reports/`·`sheets/`·`population/` 자료 폴더 패턴 추가(자료 폴더는 저장소 밖이지만 실수 방지). 릴리즈 검증에 「로그인 → 리포트 메뉴 진입」 추가 |
| `backend/pyproject.toml` · `frontend/package.json` | 변경 | 버전 `0.3.0` |
| `docs/PILOT_OPERATIONS.md` | 변경 | 「촬영 뒤 절차」 완성: ① 채점·검수 확정(P2 화면) ② 리포트 만들기(선택 일괄) ③ 장 구성·서술 확인·수정 ④ 승인 ⑤ 인쇄(「승인본 모두 인쇄」 새 탭 → Ctrl+P → A4·배경 그래픽 켬) 또는 행사 묶음 내려받기. 인쇄본에 보호자 이름이 들어가므로 배부 시 본인 확인. 「설문·구간·시트가 바뀌면 승인이 풀리고 다시 만들어야 합니다」 |
| `docs/DEVELOPMENT.md` | 변경 | 리포트 절에 인쇄 검증 방법(Playwright `page.pdf()`를 **개발 검증에만** 사용, 운영 패키지에는 없음), 리허설 확장, 릴리즈 절 갱신 |
| `docs/README.md` · `README.md`(루트) | 변경 | 리포트 계획 폴더·운영 절차 링크, 버전 |
| `frontend/tests/report.spec.ts` | 변경 | 묶음 내려받기(응답 `application/zip`, 파일명 규칙), 인쇄 안내 표시 |
| `frontend/tests/print.spec.ts` | 신설(개발 검증) | 6쌍 fixture 리포트를 `page.pdf({format:'A4'})`로 만들어 **페이지 수 2~3**, 잘린 SVG 없음(각 `svg` bounding box가 페이지 경계를 넘지 않음) 확인. 실행 시간이 길면 `--grep print`로 분리 |

## 시험·검증

- 백엔드: `event_bundle`이 승인본만 담고, 파일명에 이름이 없고, 목록 CSV 상태가 `report_status`와 같으며, 삭제 요청 참가자가 빠진다. reviewer 403. 행사에 승인본이 없으면 목록 CSV만.
- 리허설 72쌍: 생성·승인·묶음까지 끝나고 보고서 JSON에 장 수 분포(06b처럼 쌍마다 다름)가 남는다. 임시 폴더만 사용.
- 인쇄: 6쌍 fixture 모두 A4 2~3장. 1번(가장 긴 12~13장)이 3장을 넘으면 CSS 여백·글자 크기를 조정한다(내용을 줄이지 않음).
- 릴리즈: `build_release` → `verify_release`가 새 한글 경로에서 설치·로그인·리포트 메뉴 진입까지 통과. `launcher --check` 통과.

## 완료 조건

1. 승인본이 인쇄로 A4 2~3장이 되고, 행사 묶음 ZIP이 승인본만 개인정보 없는 파일명으로 담으며, 인쇄용 HTML은 리포트마다 새 쪽에서 시작한다.
2. 리허설 스크립트가 접수→설문→영상→구간→전처리→**시트→리포트→승인→묶음·인쇄용 HTML**을 합성 자료로 끝까지 돈다.
3. v0.3.0 시험 릴리즈가 만들어지고 운영 문서가 실제 화면 라벨·명령과 일치한다.
4. 백엔드·e2e·릴리즈 검증 전부 통과.

## 미결 (고객 회신)

- Q-R3 제목의 보호자 이름: 기본은 반려견 이름 우선. 회신에 따라 `report-v2.json.title_priority`만 바꾼다.
- Q-R4 웹 링크 전달: 필요하면 익명 토큰 URL·만료·접속 기록·IRB 보관 조건을 담은 별도 계획(R09)을 쓴다. 이 PR은 파일·인쇄까지다.
- 헤드리스 PDF 일괄 생성: 요구가 확정되면 별도 PR. 동봉 용량과 오프라인 설치 절차가 쟁점.

권장 PR 제목: `feat: 리포트 인쇄 검증·행사 승인본 묶음·리허설 확장·v0.3.0`
