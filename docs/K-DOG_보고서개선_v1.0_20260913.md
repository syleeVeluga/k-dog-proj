# K-DOG 보고서 개선 계획·검증 기록

## 범위와 기준

- 참가자 상세의 분석·검토와 보고서를 별도 화면 탭으로 분리한다. 선택 run과 편집기를 유지해 탭 이동으로 미저장 입력을 잃지 않는다.
- 보고서는 이번 평가 요약, 평가 주제별 설명, 관계 스타일 해설, 오늘의 팁, 참고 안내 순으로 읽는다. 편집 도구는 기본 접힘 상태로 제공한다.
- [PRD §8.3.1](K-DOG_PRD_v0.4_20260905.md)의 교육태도·사회화·친밀·애착·정서적 일관성은 **잠정 주제명**으로만 표시한다. 이름·번호·가중치·관계 유형을 승인하거나 점수를 배정하는 변경이 아니다.
- `resources/report-presentation-v1.json`은 화면·출력물의 안내용 문구다. `resources/rules/pending-v1.json`과 계산·AI 생성 규칙은 유지한다. 저장된 설명과 근거는 삭제하거나 다시 쓰지 않으며 화면에서 펼쳐 확인한다. 새 설명 저장 시 붙는 고정 보류 안내만 쉬운 문장으로 바꾼다.
- PDF·Excel·CSV의 보고서 제목과 보류 안내를 맞춘다. 기존 시트명과 점수 열 위치는 유지한다.

## 적용 순서와 합격 기준

1. 탭과 읽기 화면 적용 → 보고서에서 분석 도구가 보이지 않고, 미실행 시 다음 행동 안내가 보인다.
2. 용어·본문·출력 적용 → 잠정 주제의 뜻을 알 수 있고, 4개 비교 점수는 계속 null이다.
3. 검증 → 빌드, backend unittest, 원본 카탈로그 대조, browser E2E, 360px/desktop 및 PDF 렌더 확인.
4. Cold review → 상태 보존·이전 실행·권한·부분 결과·출력 일관성을 다시 검토하고 이슈별 수용 판단을 기록한다.
5. 수용 이슈 수정·재검증 → 커밋하고 현재 브랜치를 origin에 push한다.

## 의존성 확인 (2026-09-13)

이번 변경은 기존 API만 사용하며 새 의존성을 추가하지 않는다. UI 변경과 무관한 업그레이드는 하지 않는다.

| 패키지 | 공식 registry 최신 stable | 선택(기존 pin) | 근거 |
|---|---|---|---|
| react / react-dom | 19.3.0 | 19.2.8 | [npm](https://registry.npmjs.org/react/latest), [React 릴리스](https://react.dev/blog/2026/09/09/react-19-3), 기존 state API 유지 |
| vite | 8.3.0 | 8.2.2 | [npm](https://registry.npmjs.org/vite/latest), [Vite 8](https://vite.dev/blog/announcing-vite8), Node 24.13.0은 >=22.12 조건 충족 |
| TypeScript | 7.0.2 | 7.0.2 | [npm](https://registry.npmjs.org/typescript/latest) |
| @playwright/test | 1.63.0 | 1.63.0 | [npm](https://registry.npmjs.org/@playwright/test/latest), [릴리스](https://playwright.dev/docs/release-notes), Node >=20 충족 |
| reportlab | 5.0.1 | 5.0.1 | [PyPI](https://pypi.org/pypi/reportlab/json), [Paragraph API](https://docs.reportlab.com/reportlab/userguide/ch6_paragraphs/), Python 3.14 호환 범위 |
| openpyxl | 3.1.5 | 3.1.5 | [PyPI](https://pypi.org/pypi/openpyxl/json), [스타일 API](https://openpyxl.readthedocs.io/en/stable/styles.html) |
| pypdf | 6.18.1 | 6.17.0 | [PyPI](https://pypi.org/pypi/pypdf/json), 기존 PDF 검사 환경 보존 |

PDF 시각 검증에는 Poppler가 설치되지 않아 격리된 uv 실행 환경의 `PyMuPDF==1.28.2`를 사용했다. [PyPI 최신 stable](https://pypi.org/pypi/PyMuPDF/json)과 [페이지 렌더 API](https://pymupdf.readthedocs.io/en/latest/recipes-images.html)를 같은 날짜에 확인했다. 앱 의존성과 lockfile에는 추가하지 않았다.

## 검증 및 cold review

### 검증 결과

- `frontend/`: `npm run build` 통과.
- `backend/`: `uv run --locked python -X utf8 -m unittest discover -s tests -v` — **167개 통과**.
- `backend/`: `uv run --locked python -X utf8 -m app.import_catalogs --check` — 행동 55개·설문 30개 원본 대조 통과.
- `frontend/`: `npm run test:e2e` — **18개 통과** (cold review 수정 전 전체 검사).
- 수용 이슈 반영 후 `uv run --locked python -X utf8 -m unittest tests.test_reporting tests.test_workspace -v` — **23개 통과**.
- 수용 이슈 반영 후 `npm run test:e2e -- reporting.spec.ts workspace.spec.ts` — **9개 통과**. 원본 영상 재생·일시정지, 초안 보존, 보고서의 부분 평가 안내, 조회 오류 알림 단일 표시 포함.
- 최종 캡처 방식 보정 후 `npm run test:e2e -- reporting.spec.ts` — **2개 재통과**. 앱의 CSP를 완화하지 않고 캡처 중에만 메뉴의 CSSOM 위치를 바꾼다.
- `git diff --check` 통과. PDF·Excel·CSV에 잠정 주제명과 설명을 표시하며 비교 값 8개(4주제×설문/영상)가 계속 비어 있음을 검사했다.
- 합성 자료로 생성한 최종 PDF 3쪽 전체를 PNG로 렌더해 한글·줄바꿈·표·페이지 경계를 확인했다. Excel은 실제 파일을 다시 열어 제목, 설명, 부분 평가 안내, 빈 점수, 안내 행 높이를 검사했다.
- 1440px/360px 화면과 긴 보고서 본문을 확인했다. 긴 본문 캡처 때만 sticky 메뉴를 static으로 바꿔 화면 중간을 가리지 않게 했다. 실제 앱에서는 sticky 메뉴를 유지한다.

재현 명령:

```powershell
# backend/
uv run --locked python -X utf8 -m tests.report_preview ../frontend/test-results/report-pdf
# 저장소 루트
uv run --no-project --with PyMuPDF==1.28.2 python -X utf8 -c "import pymupdf; from pathlib import Path; root=Path('frontend/test-results/report-pdf'); doc=pymupdf.open(root/'m4-synthetic.pdf'); [page.get_pixmap(dpi=110).save(str(root/f'page-{page.number+1}.png')) for page in doc]"
```

### Cold review와 수용 판단

전체 검사 후 구현 변경분·상태 전환·출력물을 별도 단계에서 재검토했다. 별도 에이전트나 외부 리뷰어를 사용하지 않은 자체 cold review다.

| 발견/검토 항목 | 수용 여부 | 반영·검증 |
|---|---|---|
| 숨긴 탭의 영상이 계속 재생될 수 있음 | 수용 | 일반 영상은 탭 이동 시 닫고 대표 프레임 영상은 일시정지. 선택 시간과 수정 초안은 유지. 실제 합성 MP4 재생 후 탭 전환 검사 |
| 분석 점수 화면이 가려지면서 부분 결과를 완전 평가로 오해할 수 있음 | 수용 | 보고서·PDF·Excel에 반려견/보호자 평가 완료 여부와 채점 수·미채점 안내 표시 |
| Notification이 portal이라 숨긴 컨테이너에서도 중복 알림을 표시함 | 수용 | 분석 조회 오류를 공통 알림 하나로 표시. 보고서 탭의 503 오류를 1건으로 검사 |
| 탭 이동 후 기존 스크롤 위치 때문에 보고서 중간부터 읽게 됨 | 수용 | 전환 시 결과 화면 시작 위치로 이동 |
| 모바일 중첩 여백, 짧은 PDF 페이지, Excel 안내 잘림 가능성 | 수용 | 모바일 외부 패딩 축소, PDF 마지막 강제 페이지 나눔 제거, Excel 안내 행 높이 확보 및 검사 |
| 평가 주제명·통합 가중치·관계 유형 확정 | 미수용 | 잠정 표시만 적용. 원본 규칙 승인 근거가 없으므로 계산과 null 상태 유지 |
| 기존 저장 설명의 자동 재작성 | 미수용 | 과거 설명·근거·수정 이력을 보존. 새로 저장하는 고정 보류 안내만 개선 |

알려진 한계: 실제 공급자 응답의 설명 품질은 이번 검증 대상이 아니다. 이전에 저장된 설명에는 기존 전문 용어가 남을 수 있다. 내보내기 시트 이름은 기존 연동을 위해 유지하며 `영역비교` 시트/CSV에 잠정 주제명 열을 추가했다. 새 내보내기는 표시 문구도 스냅샷에 보관하며 이미 생성한 파일은 그대로 재다운로드한다.

### 화면 기록

합성 참가자·가상 관찰 자료만 사용했다.

- [데스크톱 보고서 탭](images/report-tab-desktop-20260913.png)
- [모바일 보고서 본문](images/report-body-mobile-20260913.png)
