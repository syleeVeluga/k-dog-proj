# K-DOG AR07 잔존 조건 검토

버전: v1.0 · 2026-10-12 · 기준: AR01~AR06 병합 + AR07 통합 수정

[상위 결정](K-DOG_업무권한단순화계획_v1.1_20261011.md) AR-R01~R12를 기준으로 Graft exhaustive 검색과 호출 관계를 대조했다. 아래 숫자는 검색 hit이며 결함 수가 아니다. 같은 파일/조건의 중복 hit를 성공 수로 합산하지 않는다. 실제 검증 결과는 [실행 기록 §10](K-DOG_업무권한구현실행기록_v1.0_20261011.md#10-ar07-통합검증과릴리스)에 기록한다.

## 1 검색 범위와 분류

`role/manager/owner/assigned_username/score_grants/viewer_sheet_id/403`, `consent_confirmed/consents/declined/deletion_requested/deletion.record/purge/withdrawn`, `approval/approved/activate/confirmation`을 backend/app·frontend/src·scripts에서 검색했다. backend 접근군 291 hit/39파일, 보관·상태군 88 hit/28파일, frontend 합집합 186 hit/37파일, scripts 22 hit/4파일이다. Graft가 색인한 scripts는 6파일이므로 미색인 scripts/windows는 별도 literal 검색했다. Windows installer의 operator/developer 생성과 CPython 라이선스의 저작권 owner만 남았다.

| 경로/조건 | 분류 | 실제 효과·검증 근거 |
| --- | --- | --- |
| api/auth/manage/input_models/storage의 role·활성·session | 로그인 식별 / 개발자 설정 | 네 기존 계정 형식은 업무 동등. developer 설정/키만 별도 보호. 비활성 현재 actor·만료 세션 거절. 웹 승격 없음. AR01 행렬·AR06 일반 계정 provision·AR07 ZIP |
| sheets/disclosures/scoring/basic/final/opinions의 assigned_username·rater_id·owner/grants 호환 인수 | 과거 metadata 읽기 / 자료 출처 | 최초 원평가자·노출·후속 판본 분류에 사용. 타인 시트/의견 조회·새 판본 편집 제한 없음. 제3자 후행 열람은 최초 독립본 유지. grants는 새 허가가 아님. AR03 독립성·AR05 export·AR06 UI |
| uploads/forms/validation/exports/report_runs/comparisons의 creator/request ID | 로그인 식별 / 자료 출처 | 생성 중복 식별·원본 출처. 공통 목록/읽기/쓰기/다운로드는 활성 현재 actor로 검사. 다른 creator의 같은 요청 ID는 서로 다른 수신물. 유실·변조·잘못된 대상만 기술 실패 |
| run_v4/report_runs_v4의 원 생성자 활성 검사 | 제거 → 실제 실행 계정 검사 | AR07에서 두 재시도 경로의 잔존 차단 재현·수정. immutable snapshot.requested_by는 출처로 보존. 최신 retry 사건의 실제 actor를 Worker 검사/발급 기록에 사용. 원 생성자 비활성→타인 재시도 성공, 현재 재시도 actor 비활성→채택 중단 3개 회귀 |
| attachment_runs/scoring_ai/worker/preprocess의 snapshot·lease/token·stop·budget | 자료 기술 검증 / 실제 실행 식별 | 실제 요청/재시도 계정·근거 hash·판본·lease/token·stop·예산 유지. 옛 동의/삭제 flag는 실행·재사용·채택 조건 아님. 응답 유실·미확인 과금·명시 재사용·입력 pin 회귀 |
| intake/input_models_v3/v4/domain.recording/storage의 consent/deletion 필드·manifest 비교 | 과거 metadata 읽기 / 자료 기술 검증 | 새 양식/UI/행 투영에서는 제외. 구 raw cell·매핑·JSON·DB metadata 불변. 생략 수정은 옛값 보존. DB와 immutable manifest의 일치 검사는 동의 판정이 아닌 변조 검사. 12상태 live/frozen/Worker 종단 |
| maintenance/reset_s1/secrets/gemini/launcher의 삭제·purge 문자열 | 제거 / 자료 기술 검증 | product 사례 삭제/purge 없음. clean은 전체 참조 검증 후 관리 고아파일만 제거. restore는 snapshot DB/자료/changes 복원, 삭제대장/백업 후 사건 병합 없음. S1 이전 백업 거절·세션 초기화·원격 임시 공급자 파일/폐기한 키/실제 미연결 수신 정리는 기술 수명 관리 |
| external_comparisons/domain.comparisons/report_profile/render/exports의 approved·activation·confirmation | 과거 metadata 읽기 / 자료 기술 검증 | 새 기준 정의의 실제 수치·문항·척도·산식·표본·조건·근거 hash 검증만 유지. 결재/여섯 confirmed/별도 활성화 API 없음. 구 연구확인/activation은 출처로 읽고 재승인하지 않음. 과거 출력 당시 정의·bytes 유지, 새 선택은 최신 사용중단/조건 검사 |
| opinions의 withdrawn, validation 정답의 participation·confirmation | 자료 출처 / 연구 분류 | 의견 사용중단과 사람 정답 분모 분류. 참가자 자료 접근 허가/연쇄 삭제 아님. completed 의견·정확한 근거는 새 최종본의 값 조건 |
| survey/contracts/catalog/import/s1_workbook의 owner_type·approved·pending·confirmed | 자료 기술 검증 / 역사 계약 | owner_type은 보호자 교육 영역. source manifest/hash와 확정 산식·미정 항목을 구분. 미수령 Excel/비교표를 승인값으로 생성하지 않음. 역사 catalog/legacy는 현재 점수 실행에 재연결하지 않음 |
| App/Lnb/navigation/progressText/CaseProgressList·pages의 role/isStaff·메뉴 alias | 로그인 식별 / 개발자 설정 | 공통 메뉴와 입력·진행·다음 작업. isStaff 상수/호환 인수는 모두 업무 허용이며 역할 차이 없음. 개발자 기본 설정 진입·다른 업무 주소 허용 |
| ScoreSheets/Basic/Final/AiRuns/ReportRuns/Preprocessing/Recording/PreservedMedia/UploadInbox/Forms/Validation/Comparison 화면 | 제거 / 자료 기술 검증·출처 | 소유·배정·동의·삭제·재개방 허가 UI 제거. 확정 촬영/시트의 불변 보존본 읽기 전용은 새 수정판 진입과 공존. 명시 원본/클립 열기는 실제 open 사건을 기록. 폴링/Range 요청은 새 사건 아님 |
| ResearchExports/ScoringTypes/researchTypes/reportTypes/finalTypes/externalTypes/types/API/ActivityLog·Notification/Prerequisites·MetadataEditors | 과거 metadata 읽기 / 기술 검증·출처 | viewer_sheet_id 호환 값은 서버 허가 판정에 사용하지 않음. readonly는 보존 판본/확정 입력 표시. 구 ConsentState 타입은 역사 DTO이며 현행 접수 입력 아님. 실제 판본·행위자·누락/오류 안내 유지 |
| settings_v4/AiSettings/DeveloperSettings | 개발자 설정 / 자료 기술 검증 | 모델·scope·활성 설정 판본·schema 시험·키 관리만 보호. 이 기술 설정의 activate/confirmation은 업무 역할 승인 아님 |
| scripts/issue_release·windows/online/install·verify_release·build_release | 로그인 식별 / 기술 검증 | 새 발행/설치는 operator 업무 계정. 옛 --admin 호환 유지. 일반 계정 업무+settings403, 개발자 설정+공유 업무, 재설치 데이터/비밀번호 보존. 제품 allowlist에 현재 plans Markdown/합성 PNG 포함, 고객 원본·운영 데이터·키 제외 |
| scripts/benchmark_s1/rehearsal | 로그인 식별 / 자료 출처·기술 검증 | benchmark는 실제 활성 actor와 source hash를 검사. 리허설의 legacy 동의 열은 raw 입력 호환 fixture이며 허가가 아님. 실제 교수 품질/물리 PC/정확도 승인으로 표시하지 않음 |

## 2 검사 원칙

문자열을 지우기 위해 구 문서 bytes·역사 parser·역할 enum을 재작성하지 않았다. 제거 대상은 현재 접근/실행 차단이며 source identity·실제 실행 계정·기술 무결성은 유지했다. 임의 새 정책 marker·로그 이관/병합·다운그레이드 차단은 추가하지 않았다. API 거절은 미로그인/비활성 현재 계정·개발자 설정·변조·대상/판본 충돌·중지/lease/token/예산 등 현재 검증에서만 발생한다.

옛 삭제/소유/승인 성공 시험은 현행 정책 기대와 구분해 갱신했다. 구 flag로 감춰지던 이력/사용량은 공유 목록에 남고 실제 손상 파일은 409로 격리된다. 최초 전체 실행 실패와 수정 후 집중/전체 성공은 실행 기록에서 분리한다. 운영 DB·실자료·고객 원본은 변경하지 않았다.
