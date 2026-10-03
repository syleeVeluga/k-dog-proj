# K-DOG S1 인수 검증 대장

버전: v1.0 · 2026-10-03 · 기준: 통합명세 v1.3/S1.1 · 상태: **자동·합성 시험 근거 갱신, 실측·실물·정책 확인 분리** · 갱신: 2026-10-04

상위: [전체 계획](K-DOG_개발반영계획_v1.0_20261003.md), [확인사항](K-DOG_확인사항과적용경계_v1.0_20261003.md). 표의 기대값은 주 문서 11절과 확정 규칙을 기본으로 하며 이전 앱 시험의 통과 기록을 전용하지 않는다.

현재 S00~S14 구현·단계별 자동 검증·cold review는 완료했다. S15 최종 전체 회귀·ZIP 검증은 진행 중이며 최종 수치와 commit은 [구현 실행 기록](K-DOG_구현실행기록_v1.0_20261003.md)과 [S15](K-DOG_PR-S15_배포와통합인수_v1.0_20261003.md)에 확정한다. S16은 실측 준비 도구 검증 완료·실제 측정 대기, S17은 승인 조건부 종단 출력 검증 완료·실제 D06 연구 확인 대기다. 이 대장의 자동 통과 표시는 각 행의 확정된 계약과 실행한 하위 사례에 한정한다.

2026-10-03 사용자 지시에 따라 기존 앱 점수·분석 결과는 제거하고 전부 재채점한다. **T15의 역사 보존은 고객 원본 자료에 적용하고 기존 앱 점수는 제외하며, T20은 의미 변경 5개에 더해 모든 기존 앱 점수의 복사를 금지한다.** 아래 해당 행은 이 적용 차이를 표시한다. 원본 영상·설문·검수 자료는 유지하고, S1 전환 후 새 결과의 이력·백업은 보호한다.

## 1 T01부터 T32까지

| ID | 입력·상황 | 기대 결과 | 담당 PR | 검증 종류 | 실행 상태 |
| --- | --- | --- | --- | --- | --- |
| T01 | 같은 슬롯1·서로 다른 batch, 대상의3CAM | 서로 다른 대상 분리·카메라는 한 대상 | [S01](K-DOG_PR-S01_초기화와S1전환_v1.0_20261003.md)·[S03](K-DOG_PR-S03_영상보관과동시업로드_v1.0_20261003.md)·[S14](K-DOG_PR-S14_검수자료와연구내보내기_v1.0_20261003.md) | 계약/통합 | 자동·합성 통과 (§5 근거) |
| T02 | 여러 S1 파일의 같은 항목 ID | 개체·회차·기준 분리, 해당 파일 D→J만 연결 | [S00](K-DOG_PR-S00_원본추출과S1계약_v1.0_20261003.md)·[S01](K-DOG_PR-S01_초기화와S1전환_v1.0_20261003.md)·[S06](K-DOG_PR-S06_독립채점과S1입력_v1.0_20261003.md) | 원본/계약 | 자동 매핑 통과 · G01/G04 실물 대기 |
| T03 | 60초 발성 0/20/40/40.1초, 음성 미판독 | 0/1/2/3, 미판독 null | [S07](K-DOG_PR-S07_계산과기본판정_v1.0_20261003.md)·[S08](K-DOG_PR-S08_AI채점과실행_v1.0_20261003.md) | 단위/계약 | 자동·합성 통과 (§5 근거) |
| T04 | 개19 미접촉, 개18=0·개58=−2 | 개19/44 null, W=+2 가능 | [S04](K-DOG_PR-S04_촬영사건과관찰창_v1.0_20261003.md)·[S07](K-DOG_PR-S07_계산과기본판정_v1.0_20261003.md) | 단위 | 자동·합성 통과 (§5 근거) |
| T05 | 개8=0·환경1=0·개23=0 | 탐색 없음/자연 대기, 구형 V 없음 | [S00](K-DOG_PR-S00_원본추출과S1계약_v1.0_20261003.md)·[S07](K-DOG_PR-S07_계산과기본판정_v1.0_20261003.md)·[S10](K-DOG_PR-S10_문장과장면선정_v1.0_20261003.md) | 단위/출력 | 자동·합성 통과 (§5 근거) |
| T06 | 거리0,0,2,3,2,0와 근접 예외 | 없음50%, 마지막 보호자접근33.3%, 미확인 보류·분모6 | [S04](K-DOG_PR-S04_촬영사건과관찰창_v1.0_20261003.md)·[S07](K-DOG_PR-S07_계산과기본판정_v1.0_20261003.md) | 단위/UI | 자동·합성 통과 (§5 근거) |
| T07 | 개9/10 −2~+2 전 조합 | 새 SEP25, 옛 조합/숫자 대소 해석 혼용 금지 | [S00](K-DOG_PR-S00_원본추출과S1계약_v1.0_20261003.md)·[S07](K-DOG_PR-S07_계산과기본판정_v1.0_20261003.md)·[S08](K-DOG_PR-S08_AI채점과실행_v1.0_20261003.md) | 골든 | 자동·합성 통과 (§5 근거) |
| T08 | 개9=+2·개10=+1 | 처음 문지향 없음→후기 문에서 떨어져 절반 초과 조용히 머묾 | [S07](K-DOG_PR-S07_계산과기본판정_v1.0_20261003.md)·[S10](K-DOG_PR-S10_문장과장면선정_v1.0_20261003.md) | 골든/출력 | 자동·합성 통과 (§5 근거) |
| T09 | 보22 있음·보38 미확인 | 해당 배점 제외, 기회 추정 금지 | [S06](K-DOG_PR-S06_독립채점과S1입력_v1.0_20261003.md)·[S07](K-DOG_PR-S07_계산과기본판정_v1.0_20261003.md) | 단위 | 자동·합성 통과 (§5 근거) |
| T10 | 8절 보호자5예시 | 허용/조율/통제/보류/근거 부족, 부족 시 비율 null | [S07](K-DOG_PR-S07_계산과기본판정_v1.0_20261003.md) | 골든 | 자동·합성 통과 (§5 근거) |
| T11 | 유형 선택·근거/작성자 누락 | 선택 미적용·자동 초안 유지·미완 표시 | [S07](K-DOG_PR-S07_계산과기본판정_v1.0_20261003.md)·[S09](K-DOG_PR-S09_완료의견과최종결과_v1.0_20261003.md) | 계약/UI | 자동·합성 통과 (§5 근거) |
| T12 | 교육태도에만 완료 의견 | 영역별 완료 의견→유효 선택→AI, 원값/출처 유지 | [S09](K-DOG_PR-S09_완료의견과최종결과_v1.0_20261003.md)·[S10](K-DOG_PR-S10_문장과장면선정_v1.0_20261003.md)·[S12](K-DOG_PR-S12_리포트실행과메뉴_v1.0_20261003.md) | 통합 | 자동·합성 통과 (§5 근거) |
| T13 | 작성 중 또는 D39만 작성 | 완료 우선 반영 금지·완성 조언 강제 출력 금지 | [S09](K-DOG_PR-S09_완료의견과최종결과_v1.0_20261003.md)·[S10](K-DOG_PR-S10_문장과장면선정_v1.0_20261003.md) | 계약/출력 | 자동·합성 통과 (§5 근거) |
| T14 | Q10=0,Q11=2 / Q12=0,Q13=1,Q14=2 | 두 평균1.0, 하나 결측 시 해당 묶음 null | [S02](K-DOG_PR-S02_설문과구글폼등록_v1.0_20261003.md) | 단위 | 자동·합성 통과 (§5 근거) |
| T15 | 구 개32=99·폐기33·미사용4 | S1 입력/산출 제외. 사용자 지시로 기존 앱 값 제거, 고객 원본 유지 | [S00](K-DOG_PR-S00_원본추출과S1계약_v1.0_20261003.md)·[S01](K-DOG_PR-S01_초기화와S1전환_v1.0_20261003.md)·[S06](K-DOG_PR-S06_독립채점과S1입력_v1.0_20261003.md)·[S08](K-DOG_PR-S08_AI채점과실행_v1.0_20261003.md) | 초기화/계약 | 자동·합성 통과 (§5 근거) |
| T16 | 원자료·조건 모두 빈칸 | 수치/유형 없음·자료 부족, 완성 조언 창작 금지 | [S07](K-DOG_PR-S07_계산과기본판정_v1.0_20261003.md)·[S09](K-DOG_PR-S09_완료의견과최종결과_v1.0_20261003.md)·[S10](K-DOG_PR-S10_문장과장면선정_v1.0_20261003.md)·[S11](K-DOG_PR-S11_리포트HTML과PDF_v1.0_20261003.md) | 통합/시각 | 자동·합성 통과 (§5 근거) |
| T17 | 개30=3·개34=0·보14=1 | 물건 회피 감소, 코접촉 시간 불필요 | [S07](K-DOG_PR-S07_계산과기본판정_v1.0_20261003.md)·[S10](K-DOG_PR-S10_문장과장면선정_v1.0_20261003.md) | 골든 | 자동·합성 통과 (§5 근거) |
| T18 | 개58=−2·개18=+2 | W=0과 방향 반전, 0→0과 구별 | [S07](K-DOG_PR-S07_계산과기본판정_v1.0_20261003.md)·[S10](K-DOG_PR-S10_문장과장면선정_v1.0_20261003.md)·[S11](K-DOG_PR-S11_리포트HTML과PDF_v1.0_20261003.md) | 골든/출력 | 자동·합성 통과 (§5 근거) |
| T19 | 몸긁기 일부 관찰 | null+사유+실제 사건, 전체 부재0과 구별 | [S04](K-DOG_PR-S04_촬영사건과관찰창_v1.0_20261003.md)·[S06](K-DOG_PR-S06_독립채점과S1입력_v1.0_20261003.md)·[S08](K-DOG_PR-S08_AI채점과실행_v1.0_20261003.md) | 계약 | 자동·합성 통과 (§5 근거) |
| T20 | 개8/10/12/30/34 및 기존 앱 점수 전체 | 사용자 지시로 전부 null에서 재채점, 같은 정의/ID도 기존 점수 복사 금지 | [S01](K-DOG_PR-S01_초기화와S1전환_v1.0_20261003.md)·[S06](K-DOG_PR-S06_독립채점과S1입력_v1.0_20261003.md)·[S14](K-DOG_PR-S14_검수자료와연구내보내기_v1.0_20261003.md) | 초기화/재채점 | 자동·합성 통과 (§5 근거) |
| T21 | 선택 꼬리 없음·다른 필수 근거 있음 | 꼬리 문장만 생략·유효 결과 출력 | [S04](K-DOG_PR-S04_촬영사건과관찰창_v1.0_20261003.md)·[S08](K-DOG_PR-S08_AI채점과실행_v1.0_20261003.md)·[S10](K-DOG_PR-S10_문장과장면선정_v1.0_20261003.md)·[S11](K-DOG_PR-S11_리포트HTML과PDF_v1.0_20261003.md) | 통합 | 자동·합성 통과 (§5 근거) |
| T22 | 동일 사건 두 카메라 | 중복 제거·유효 서로 다른 영역 최대3장면 | [S05](K-DOG_PR-S05_다중카메라전처리_v1.0_20261003.md)·[S08](K-DOG_PR-S08_AI채점과실행_v1.0_20261003.md)·[S10](K-DOG_PR-S10_문장과장면선정_v1.0_20261003.md) | 통합 | 자동·합성 통과 (§5 근거) |
| T23 | 몸 상태·몸털기·몸긁기 근거 | 결과4카드 유지·독립 몸 영역 없음 | [S10](K-DOG_PR-S10_문장과장면선정_v1.0_20261003.md)·[S11](K-DOG_PR-S11_리포트HTML과PDF_v1.0_20261003.md) | 시각 | 자동·합성 통과 (§5 근거) |
| T24 | 견본 요약 ‘찾고, 차분히 재회’ | 설명으로만 사용·제5애착 유형 금지 | [S09](K-DOG_PR-S09_완료의견과최종결과_v1.0_20261003.md)·[S10](K-DOG_PR-S10_문장과장면선정_v1.0_20261003.md)·[S11](K-DOG_PR-S11_리포트HTML과PDF_v1.0_20261003.md) | 계약/출력 | 자동·합성 통과 (§5 근거) |
| T25 | Q1~6 부분 결측·Q10/11 완전 | 두려움 정상 산출·기타 결측정책 미확정 유지 | [S02](K-DOG_PR-S02_설문과구글폼등록_v1.0_20261003.md)·[S13](K-DOG_PR-S13_집단비교와출력조건_v1.0_20261003.md) | 정책/출력 | 확정 묶음 통과 · 기타 결측정책 대기 유지 |
| T26 | 보12=3·개58=−2·개18=0 | W=+2, 무시 무효와 분리·원값/조건 보존 | [S07](K-DOG_PR-S07_계산과기본판정_v1.0_20261003.md) | 골든 | 자동·합성 통과 (§5 근거) |
| T27 | 양식 예시 메모 잔재 | 실제 근거/리포트에 유입 금지·실물 정정 확인 | [S06](K-DOG_PR-S06_독립채점과S1입력_v1.0_20261003.md)·[S10](K-DOG_PR-S10_문장과장면선정_v1.0_20261003.md)·[S14](K-DOG_PR-S14_검수자료와연구내보내기_v1.0_20261003.md) | 원본/계약 | 예시 차단 통과 · G04 교정 실물 대기 |
| T28 | 개9와 보10/11/23 선택 UI | 개9 −2→+2, 보10/11/23 +2→−2, 배점 의미 불변 | [S00](K-DOG_PR-S00_원본추출과S1계약_v1.0_20261003.md)·[S06](K-DOG_PR-S06_독립채점과S1입력_v1.0_20261003.md) | UI/골든 | 자동·합성 통과 (§5 근거) |
| T29 | 개21 전체30초 제안 미승인 | 정책 대기·원범위/사건 보존·확정값 혼용 금지 | [S04](K-DOG_PR-S04_촬영사건과관찰창_v1.0_20261003.md)·[S06](K-DOG_PR-S06_독립채점과S1입력_v1.0_20261003.md)·[S08](K-DOG_PR-S08_AI채점과실행_v1.0_20261003.md) | 정책 | D03 정책 대기 유지 시험 통과 |
| T30 | 루키 재확인값·AI 잠정값 | 개발 참고 유지·사람 확정 정답/독립 분모 제외 | [S14](K-DOG_PR-S14_검수자료와연구내보내기_v1.0_20261003.md)·[S16](K-DOG_PR-S16_원본압축본과360도실증_v1.0_20261003.md) | 출처/실자료 | 참고 분모 제외 통과 · G03 실자료 확인 대기 |
| T31 | 없는 사건/수치·미정 기준 확정 출력 | 오류 식별·재검토·검증 안 된 출력 정상 게시 금지 | [S08](K-DOG_PR-S08_AI채점과실행_v1.0_20261003.md)·[S10](K-DOG_PR-S10_문장과장면선정_v1.0_20261003.md)·[S12](K-DOG_PR-S12_리포트실행과메뉴_v1.0_20261003.md)·[S16](K-DOG_PR-S16_원본압축본과360도실증_v1.0_20261003.md) | 오류주입/실검수 | 오류 주입 통과 · 실제 AI 검수 미실행 |
| T32 | 자유 의견에서 최종 유형 반환 | 예시·근거/반대근거/보류 사유 제출, D04 상세는 확인 후 적용 | [S09](K-DOG_PR-S09_완료의견과최종결과_v1.0_20261003.md)·[S10](K-DOG_PR-S10_문장과장면선정_v1.0_20261003.md) | 정책/실제 반환 | 입력·보류 계약 통과 · D04 실제 반환 확인 대기 |

위 기대값은 요약이다. 실제 시험 작성 시 본문·부록의 원값·조건·관찰창을 함께 고정한다. T32는 미승인 상세 자동화가 합격했다는 시험이 아니라, 승인 전 정책 대기와 승인 후 확정 예시를 구분해 회신한다. T30의 비교파일 유효성 시험과 실제 독립 정확도 시험도 별개다.

## 2 운영 요청과 보호장치의 추가 검증

O번호는 이 구현 계획의 추가 검증 식별자이며 고객 T번호를 대체하지 않는다.

| ID | 확인할 흐름 | 기대 결과 | 담당 | 상태 |
| --- | --- | --- | --- | --- |
| O01 | Forms CSV/XLSX 신규·기존·현장 추가·같은 파일 재시도 | 대상 중복 없이 명시 ID/회차에 설문 반영, 변경 미리보기 | S02·S15 | 자동·합성 통과 (§5 근거) |
| O02 | 예비 정리표 전치·과거1~5척도 | 원문 판본 보존, 새0~4로 자동 변환하지 않음 | S02 | 자동·합성 통과 (§5 근거) |
| O03 | 같은 대상 3PC 동시 업로드·연결 충돌 | 완료 파일 보존·재전송 없이 연결 재시도·중복 없음 | S03·S15 | 합성 3클라이언트 통과 · 실제 3PC/LAN 미실행 |
| O04 | 등록보다 영상이 먼저 도착 | 미연결 수신물에 보존하고 명시 대상에 이후 연결 | S02·S03·S15 | 자동·합성 통과 (§5 근거) |
| O05 | 원본1/3/2→CAM1/2/3·변환본·offset | 번호/해시/시각 계보 유지, 같은 사건/대상 중복 방지 | S03~S05·S16 | 계보·offset 합성 통과 · 실제 동기화 실측 미실행 |
| O06 | INSV·360MP4·일반MP4 | 보관/변환/판독/품질 상태를 구별하여 실제 시험 | S03·S05·S16 | 보관·지원 경계 통과 · 360도 판독/품질 미실행 |
| O07 | 구판 순서/재회 길이와 S1 채점 | 실제 시각 보존·호환 범위만 평가·구판을 신판 정상으로 위장하지 않음 | S01·S04·S08 | 자동·합성 통과 (§5 근거) |
| O08 | 독립 시트·AI 노출·잠정값·철회 사례 | 권한/동의·출처·분모·정답 유효성 유지 | S06·S08·S14·S16 | 독립성·권한 합성 통과 · 실제 사람 정답 확인 대기 |
| O09 | 자체 집단과 미승인 외부 비교 | 동일판본 중복 제거/n, 모든 출력 경로에서 미승인 값 차단 | S13·S17 | 자체 집단·승인 조건부 종단·철회 합성 통과 · 실제 D06 대기 |
| O10 | 장면0~3·긴문장·결측·모바일/인쇄 | 4카드·기본6쪽·한글/차트·출처, 잘림/허구 없음 | S10~S12·S15 | 합성 UI/PDF 시각 검수 통과 · 현장 출력 미실행 |
| O11 | 수정/삭제 중 실행·옛 token·응답 유실 | 불변 입력·중복 호출 제어·삭제/권한 재검사·과금 미확인 표시 | S03·S08·S12·S15 | 자동·합성 통과 (§5 근거) |
| O12 | 새 ZIP·한글 경로·3PC·백업/복원 | S1 자산·동일 중앙 DB·원입력/새 결과 참조·삭제 이력 유지, 초기화 전 구판 점수 복원 제외 | S15 | 백업/복원·합성 리허설 통과 · ZIP 검증 중 · 실제 3PC/깨끗한 OS 미실행 |
| O13 | 원본/압축본/낮은FPS·1CAM/3CAM 반복 | 단계별/전체시간·조건·품질/결측·비용·변동을 분리 보고 | S16 | 준비 도구 시험 통과 · 실제 S16 측정 미실행 |
| O14 | 기존 결과 초기화·중단/반복·옛 worker 응답 | 전 점수 null·원입력 유지·S1 단일 운영·옛 결과 재등장 없음·재실행으로 새 S1 결과 삭제 없음 | S00·S01·S06~S08·S15 | 초기화·반복 보호 합성 및 실제 로컬 전환 통과 |

## 3 실행 결과 기록 형식

각 시험은 아래 항목을 갖춘다. 민감한 원본을 문서에 직접 붙이지 않고 보호된 자료 참조와 비식별 요약을 사용한다.

| 필드 | 기록 내용 |
| --- | --- |
| 식별 | T/O ID, 하위 사례 ID, 담당 PR/commit |
| 입력 | 합성/실제 구분, 대상 가명·회차·영상/시트 hash, 원문 절/셀, 관찰창 |
| 기대 | 숫자·상태·사유·출처·화면의 기대 결과와 판정 기준 |
| 실제 | 실제 반환값/파일 hash·화면/PDF·로그 위치 |
| 결과 | 통과/실패/미실행/정책 대기. 실행되지 않은 것을 통과로 두지 않음 |
| 차이 | 원인·수정 PR·잔여 영향·재시험 대상 |
| 판본 | 앱 commit, 모델, API, 프롬프트, 설정, 카탈로그/계산, 설문/집계, 촬영, 문장/템플릿 |
| 실행 | 실행일·환경·명령·평가자·검수자. 공급자 호출 여부/횟수·사용량 |

## 4 시험 종류와 완료 판단

- **단위/골든:** 고객 산식·경계·기회·결측을 검사한다. 구현의 반환값을 복사해 기대값을 만들지 않는다.
- **계약/합성 공급자:** 항목 집합·schema·근거·실패·복구를 검사한다. 실제 반려견 판독 정확도로 표현하지 않는다.
- **실제 공급자 기술 시험:** 허용된 입력으로 연결·계량을 확인한다. 사람 정답 비교가 없으면 품질 검증이 아니다.
- **실제 자료 대조:** 같은 판본/영상/창의 유효 사람 확정값과 AI 최초 출력만 비교한다. 누적 비교표의 단순 일치율을 독립 정확도로 바꾸지 않는다.
- **UI/PDF 시각 검수:** 제공 포맷, 모바일·긴문장·한글·그래프·사진·전체 페이지를 직접 확인한다.
- **운영 검수:** 실제 3PC·서버·네트워크·설치·복구를 확인한다. 브라우저3컨텍스트 합성 시험과 별개다.

S15에서 기본 구조 인수를 묶고, S16/S17 실자료·연구 확인은 별도 완료한다. 자료가 없어 실행하지 못한 행은 기대값/담당/부족 자료를 남긴다. 확인 회신으로 규칙이 바뀌면 새 판본의 기대값을 추가하고 과거 실행 기록은 유지한다.

## 5 2026-10-04 실제 시험과의 연결

아래는 이번 S1 구현에서 실행한 자동 시험의 대표 **파일·시험 함수**다. `test_` 함수가 존재한다는 이유만으로 통과로 간주하지 않고 각 S00~S17 계획의 실제 실행 기록과 연결했다. 같은 함수가 여러 경계를 검증할 수 있으므로 행 수를 시험 개수로 합산하지 않는다. 전체 backend 회귀의 최종 결과·현재 commit은 [구현 실행 기록](K-DOG_구현실행기록_v1.0_20261003.md)에 별도 기록한다. UI 실행 명령·합성 캡처와 PDF 전 페이지 검수는 각 단계 기록을 따른다.

실제 참가자 영상이나 유료 공급자를 호출하지 않았다. 실제 source DOCX/XLSX의 hash·추출 대조와 합성 영상의 FFmpeg·브라우저·PDF 실행은 수행했지만, 독립 실제 정확도·실제 LAN 3PC·실제 360도 품질·운영 설치를 대신하지 않는다. 실제 로컬 초기화·백업 복원은 아래 별도 기록으로 구분한다. 재개 입력과 정책/실물 확인 주체는 [실측 및 확인 후속 대장](K-DOG_실측및확인후속대장_v1.0_20261003.md)을 따른다. G02 문장은행 상태만으로 명세 검증된 정상 발급을 막지 않으며, D04 자동 유형 상세와 D06 외부 비교 승인을 합성 fixture로 승인 처리하지 않는다.

### T항목의 자동 시험 근거

| ID | 실제 파일·함수 | 검증 범위와 남은 경계 |
| --- | --- | --- |
| T01 | [test_exports_v4.py](../../backend/tests/test_exports_v4.py) `test_three_views_are_one_pair_and_different_batch_has_no_valid_denominator`; [test_uploads_v4.py](../../backend/tests/test_uploads_v4.py) `test_same_camera_distinct_files_and_local_duplicate_do_not_cross_cases` | 3시야는 한 비교 쌍, batch/input이 다르면 제외. 슬롯/카메라 수를 대상 수로 만들지 않는다. |
| T02 | [test_mapping_v4.py](../../backend/tests/test_mapping_v4.py) `test_input_addresses_and_physical_verification_are_distinct`; [test_input_import_v4.py](../../backend/tests/test_input_import_v4.py) `test_synthetic_d_j_mismatch_and_f_g_examples_detected_without_import` | 확정 코드·D/J 주소/대상·회차 핀 검증. 실제 빈 Excel의 수식·주소 인수는 G01/G04 대기이며 점수 import는 비활성이다. |
| T03 | [test_scoring_v4.py](../../backend/tests/test_scoring_v4.py) `test_vocal_exact_thresholds_actual_interval_and_no_audio`, `test_vocal_inconsistent_raw_and_partial_denominator_rejected` | 60초 중 0/20/40/40.1초→0/1/2/3, 오디오 없음/부분 분모 null. 실제 소리 판독 품질은 미측정이다. |
| T04 | [test_recording_v4.py](../../backend/tests/test_recording_v4.py) `test_no_contact_does_not_erase_later_body_or_avoidance_response`; [test_scoring_v4.py](../../backend/tests/test_scoring_v4.py) `test_w_is_independent_of_ignore_contact_and_keeps_direction` | 미접촉 개19/44 null과 몸 상태 W를 분리한다. |
| T05 | [test_acceptance_v4.py](../../backend/tests/test_acceptance_v4.py) `test_t05_zero_exploration_and_natural_body_are_distinct_and_no_old_v` | 개8/환경1/개23=0의 서로 다른 원문 뜻을 profile에 보존하며 구형 V는 없다. |
| T06 | [test_scoring_v4.py](../../backend/tests/test_scoring_v4.py) `test_walk_six_denominator_and_guardian_approach`, `test_walk_far_recheck_close_unknown_and_missing_hold`; [test_report_content_v4.py](../../backend/tests/test_report_content_v4.py) `test_walking_denominator_stays_six_and_percent_is_not_duration` | 50%/33.3%, 고정 분모6, 근접 예외와 미확인 보류. |
| T07 | [test_scoring_v4.py](../../backend/tests/test_scoring_v4.py) `test_all_25_separation_rows_match_appendix_c_descriptions` | 원문 처음10초/이후50초 설명 25조합 전수 검사. |
| T08 | [test_acceptance_v4.py](../../backend/tests/test_acceptance_v4.py) `test_t08_positive_separation_values_keep_two_specific_source_descriptions` | +2/+1의 초기 문지향 없음·후기 문에서 떨어진 조용한 모습이 관계 설명에 따로 남는다. |
| T09 | [test_scoring_v4.py](../../backend/tests/test_scoring_v4.py) `test_owner_unknown_opportunity_and_safety_action_excluded` | 보22 값만으로 기회를 추정하지 않고 보38 미확인 배점을 제외한다. |
| T10 | [test_scoring_v4.py](../../backend/tests/test_scoring_v4.py) `test_t10_five_source_examples_scene_averages`, `test_owner_exact_dominance_and_margin_edges_not_rounded` | 원문 5사례·유효 항목/장면·부족 null·경계값. |
| T11 | [test_judgements_v4.py](../../backend/tests/test_judgements_v4.py) `test_incomplete_draft_does_not_override_automatic`, `test_manual_missing_opposing_basis_foreign_code_and_unknown_type_reject`; [test_opinions_v4.py](../../backend/tests/test_opinions_v4.py) `test_requested_only_help_only_type_only_and_no_evaluator_never_complete` | 작성자/근거·반대근거가 빠진 선택과 미완 의견은 자동 원본을 덮지 않는다. |
| T12 | [test_final_results_v4.py](../../backend/tests/test_final_results_v4.py) `test_only_completed_education_overrides_that_domain_manual_then_basic`; [test_report_validation_v4.py](../../backend/tests/test_report_validation_v4.py) `test_from_final_uses_exact_original_and_does_not_refresh_opinion` | 완료 교육태도만 우선하고 다른 영역/원값·비율·고정 최종판본은 보존한다. |
| T13 | [test_final_results_v4.py](../../backend/tests/test_final_results_v4.py) `test_draft_and_help_only_never_override_or_emit_completed_help`; [test_report_content_v4.py](../../backend/tests/test_report_content_v4.py) `test_priority_help_uses_completed_human_text_once` | 작성 중/D39만으로 완료되지 않으며 완료 사람 조언만 출처와 함께 출력한다. |
| T14 | [test_survey_v4.py](../../backend/tests/test_survey_v4.py) `test_t14_two_fear_means_and_zero_are_source_values`, `test_every_fear_missing_position_holds_only_its_group` | 명시 두려움 묶음 평균1.0, 어느 위치의 결측도 해당 묶음만 null. |
| T15 | [test_catalog_v4.py](../../backend/tests/test_catalog_v4.py) `test_exact_counts_and_retired_identity_exclusion`; [test_reset_s1.py](../../backend/tests/test_reset_s1.py) `test_reset_removes_scores_preserves_inputs_accounts_settings_and_uncertain_usage`; [test_validation_data_v4.py](../../backend/tests/test_validation_data_v4.py) `test_raw_zero_negative_null_formula_and_cache_are_distinct_reference_only` | 폐기 코드/구앱 점수는 S1에 복사하지 않고 고객 참고 원본99는 참고로만 보존한다. 실제 로컬 초기화 결과는 아래 운영 전환 기록에 분리했다. |
| T16 | [test_scoring_v4.py](../../backend/tests/test_scoring_v4.py) `test_empty_input_no_zero_type_or_retired_calculation`; [test_report_content_v4.py](../../backend/tests/test_report_content_v4.py) `test_four_cards_missing_is_not_zero_and_no_invented_actions_or_scenes` | 빈칸을0·유형·완성 조언으로 만들지 않는다. 합성 결측 PDF 6쪽은 S11에서 검수했다. |
| T17 | [test_scoring_v4.py](../../backend/tests/test_scoring_v4.py) `test_object_same_identity_condition_and_no_nose_latency` | 3→0/보14=1에서 같은 물건이라는 명시 확인이 있을 때 회피 감소. 코접촉 지연은 요구하지 않는다. |
| T18 | [test_acceptance_v4.py](../../backend/tests/test_acceptance_v4.py) `test_t18_w_zero_keeps_direction_reversal_separate_from_zero_to_zero` | W=0이어도 −2→+2와0→0의 원값·관계 설명이 다르다. |
| T19 | [test_recording_v4.py](../../backend/tests/test_recording_v4.py) `test_whole_count_and_exploration_gates_retain_partial_observed_events`; [test_scoring_ai_v4.py](../../backend/tests/test_scoring_ai_v4.py) `test_count_zero_requires_whole_interval_and_d03_is_not_inferred` | 실제 부분 사건은 보존하고 전체 미발생0을 추정하지 않는다. |
| T20 | [test_intake_v4.py](../../backend/tests/test_intake_v4.py) `test_default_new_case_has_s1_contract_and_no_copied_scores`; [test_validation_data_v4.py](../../backend/tests/test_validation_data_v4.py) `test_registration_idempotency_never_changes_current_scores_or_source_bytes` | 기존 결과 이관 없음, 참고 등록도 새 채점 시트를 변경하지 않는다. |
| T21 | [test_acceptance_v4.py](../../backend/tests/test_acceptance_v4.py) `test_t21_missing_optional_tail_does_not_suppress_valid_social_result` | 꼬리54/55가 없어도 실제 유효 개51 사회성 설명은 유지한다. |
| T22 | [test_scoring_ai_v4.py](../../backend/tests/test_scoring_ai_v4.py) `test_three_views_of_one_event_never_become_count_three`; [test_report_scenes_v4.py](../../backend/tests/test_report_scenes_v4.py) `test_three_synchronized_views_one_explicit_event_one_scene`, `test_zero_one_two_and_three_scene_limit` | 명시 공통 사건만 합치고0~3장면을 고른다. 단순 시간 겹침은 공통 사건으로 추정하지 않는다. |
| T23 | [test_acceptance_v4.py](../../backend/tests/test_acceptance_v4.py) `test_t23_body_shake_and_scratch_evidence_keeps_exactly_four_result_cards` | 몸 상태·몸털기·몸긁기 실제 원관찰이 있어도 결과 카드는 정확히4개다. |
| T24 | [test_final_results_v4.py](../../backend/tests/test_final_results_v4.py) `test_free_text_summary_never_becomes_fifth_attachment_type`; [test_report_content_v4.py](../../backend/tests/test_report_content_v4.py) `test_typeless_completed_opinion_does_not_infer_new_type` | 자유 요약은 새 유형/선택을 만들지 않는다. |
| T25 | [test_survey_v4.py](../../backend/tests/test_survey_v4.py) `test_t25_nonfear_partial_policy_does_not_block_complete_fear`; [test_comparisons_v4.py](../../backend/tests/test_comparisons_v4.py) `test_per_domain_valid_n_zero_and_undecided_partial_means` | 확정 두려움 산출과 다른 영역의 정책 대기·유효 n을 분리한다. 미정 부분평균을 승인하지 않았다. |
| T26 | [test_scoring_v4.py](../../backend/tests/test_scoring_v4.py) `test_w_is_independent_of_ignore_contact_and_keeps_direction` | 보12=3인 무시 무효와 W=+2가 구별된다. |
| T27 | [test_input_import_v4.py](../../backend/tests/test_input_import_v4.py) `test_synthetic_d_j_mismatch_and_f_g_examples_detected_without_import`; [test_report_validation_v4.py](../../backend/tests/test_report_validation_v4.py) `test_placeholder_human_text_is_held_and_not_in_output_claims` | 예시 메모를 정상 근거로 발행하지 않는다. G04 실제 교정 파일 인수는 대기다. |
| T28 | [test_catalog_v4.py](../../backend/tests/test_catalog_v4.py) `test_value_and_display_order_are_separate`; [scoring-v4.spec.ts](../../frontend/tests/scoring-v4.spec.ts) | 원값과 선택 표시 순서를 분리하고 실제 S1 입력 UI로 확인했다. |
| T29 | [test_recording_v4.py](../../backend/tests/test_recording_v4.py) `test_policy_pending_is_not_missing_observation_or_extra_invalidity`; [test_scoring_ai_v4.py](../../backend/tests/test_scoring_ai_v4.py) `test_pending_group_uses_program_and_cannot_be_numeric` | 개21의 미승인30초 제안을 확정 범주로 만들지 않고 D03 대기를 유지한다. |
| T30 | [test_validation_data_v4.py](../../backend/tests/test_validation_data_v4.py) `test_unmatched_and_unidentified_evaluator_are_never_guessed_from_names`; [test_benchmark_s1.py](../../backend/tests/test_benchmark_s1.py) `test_wrong_ai_run_revised_ai_and_reference_only_values_cannot_supply_truth` | G03 참고/잠정/구판은 독립 정답 분모 제외. 실제 루키 등 고객 사례 재확인은 미실행이다. |
| T31 | [test_report_validation_v4.py](../../backend/tests/test_report_validation_v4.py) `test_regeneration_rejects_wrong_type_number_fake_noise_and_scene`; [test_report_runs_v4.py](../../backend/tests/test_report_runs_v4.py) `test_blocking_content_stays_review_required_without_rendering` | 허구 수치·유형·장면 오류 주입은 정상 발급을 차단한다. 자유서술 전반의 실제 정확도를 보장하는 시험은 아니다. |
| T32 | [test_judgements_v4.py](../../backend/tests/test_judgements_v4.py) `test_manual_missing_opposing_basis_foreign_code_and_unknown_type_reject`; [test_ai_api_v4.py](../../backend/tests/test_ai_api_v4.py) `test_settings_contract_permissions_conflict_and_no_provider_schema_validation` | 선택의 작성자/근거·반대근거와 정책 대기 계약을 검사한다. D04 실제 자동 유형 반환·예시 검수는 미실행이다. |

### O항목의 자동 시험 및 실측 경계

| ID | 실제 파일·함수 또는 브라우저 | 자동으로 확인한 것 / 남은 것 |
| --- | --- | --- |
| O01 | [test_forms_import_v4.py](../../backend/tests/test_forms_import_v4.py) `test_ids_are_fixed_in_preview_and_create_and_survey_commit_together`, `test_request_and_file_idempotency_preserve_ids_and_revision`; [importer-v4.spec.ts](../../frontend/tests/importer-v4.spec.ts) | 신규/기존·명시 회차·중복·미리보기·409·삭제/권한 재검사. |
| O02 | [test_forms_import_v4.py](../../backend/tests/test_forms_import_v4.py) `test_unsupported_scale_is_reference_only_and_never_converted`, `test_column_inspection_shares_layout_header_and_formula_checks`; [test_survey_v4.py](../../backend/tests/test_survey_v4.py) `test_old_survey_scale_is_not_reinterpreted_as_s1` | 전치/매핑과 구척도 참고 보존, 1~5→0~4 임의 변환 없음. |
| O03 | [test_uploads_v4.py](../../backend/tests/test_uploads_v4.py) `test_three_receives_and_revision_conflicts_recover_without_reupload`; [uploads-v4.spec.ts](../../frontend/tests/uploads-v4.spec.ts); [test_rehearsal.py](../../backend/tests/test_rehearsal.py) `test_two_pairs_end_to_end_in_a_temporary_folder` | 3논리 클라이언트와 revision 충돌 뒤 연결 재시도 통과. 실제 PC/LAN 전송시간·대용량 안정성은 미측정. |
| O04 | [test_uploads_v4.py](../../backend/tests/test_uploads_v4.py) `test_unlinked_inventory_permissions_and_manual_cleanup_are_explicit`, `test_receipt_snapshot_and_complete_bytes_survive_database_backup` | 등록 전 완료 bytes를 보존하고 이후 명시 연결한다. |
| O05 | [test_uploads_v4.py](../../backend/tests/test_uploads_v4.py) `test_insv_and_received_conversion_keep_provenance_and_parent_access`; [test_preprocess_v4.py](../../backend/tests/test_preprocess_v4.py) `test_three_cameras_offsets_quality_and_audio_are_not_summed`; [test_benchmark_s1.py](../../backend/tests/test_benchmark_s1.py) `test_alignment_uses_source_equals_reference_plus_positive_and_negative_offset` | 1/3/2 출처 매핑·원본/변환 계보·확인된 offset 보존. 실제 현장 동기화 정확도는 미측정. |
| O06 | [test_preprocess_v4.py](../../backend/tests/test_preprocess_v4.py) `test_insv_and_camera_decode_failure_leave_usable_camera_output`; [test_uploads_v4.py](../../backend/tests/test_uploads_v4.py) `test_insv_and_received_conversion_keep_provenance_and_parent_access` | INSV는 보관 전용, 합성 MP4 처리 경계 확인. 실제 INSV 변환·360MP4 판독/품질 완료를 주장하지 않는다. |
| O07 | [test_recording_v4.py](../../backend/tests/test_recording_v4.py) `test_legacy_stranger_before_reunion_is_preserved_and_not_standard`, `test_skipped_and_interrupted_separation_and_short_reunion` | 구순서·짧은 재회를 실제 시각 그대로 보존하며 정상 S1 창으로 위장하지 않는다. |
| O08 | [test_sheets_v4.py](../../backend/tests/test_sheets_v4.py) `test_grant_is_not_exposure_reveal_preserves_independent_original`; [test_exports_v4.py](../../backend/tests/test_exports_v4.py) `test_independent_historical_human_and_initial_ai_have_item_denominators`; [test_benchmark_s1.py](../../backend/tests/test_benchmark_s1.py) `test_human_after_ai_disclosure_is_excluded_and_reason_preserved` | 최초 사람/AI와 노출 후 review 분모 분리. 실제 유효 사람 정답 확보는 G03/S16 후속. |
| O09 | [test_comparisons_v4.py](../../backend/tests/test_comparisons_v4.py) `test_duplicate_case_sessions_never_increase_sample_count`, `test_pending_sources_never_expose_reference_numbers`; [test_external_comparisons_v4.py](../../backend/tests/test_external_comparisons_v4.py) `test_explicit_http_research_activation_target_snapshot_and_revocation`, `test_actual_content_html_pdf_and_withdrawal_keep_issued_bytes_immutable`; [test_external_exports_v4.py](../../backend/tests/test_external_exports_v4.py) `test_csv_and_xlsx_pin_approved_scope_numbers_and_pseudonymous_target`; [comparisons-v4.spec.ts](../../frontend/tests/comparisons-v4.spec.ts) | 자체 집단 n·출처 pin, 연구 확인과 기술 활성화의 분리, 정확한 대상의 API/HTML/PDF/CSV/XLSX 조건부 출력과 철회 차단. 실제 연구 승인/활성화는 D06 대기. |
| O10 | [test_report_render_v4.py](../../backend/tests/test_report_render_v4.py) `test_pdf_six_page_baseline_and_long_content_continues_without_clipping`; [report-print-v4.spec.ts](../../frontend/tests/report-print-v4.spec.ts); [report-v4.spec.ts](../../frontend/tests/report-v4.spec.ts) | 합성0~3장면, 기본6쪽·긴글 연장, 한글·실제 이미지 pin·360px와 인쇄 전 페이지 검수. 실제 참가자 문구/현장 프린터 미검수. |
| O11 | [test_run_v4.py](../../backend/tests/test_run_v4.py) `test_claim_expiry_stop_and_old_token_cannot_adopt`, `test_restart_recovers_complete_artifact_without_a_second_call`, `test_three_attempt_budget_and_billing_unknown_survive_explicit_retry`; [test_report_runs_v4.py](../../backend/tests/test_report_runs_v4.py) `test_lost_adoption_response_recovers_exact_files_without_rendering_twice` | token·권한·삭제·hash 재검사, 응답 유실 복구, 최대3회/호출예약과 미확인 과금. 실제 유료 비용은 미측정. |
| O12 | [test_exports_v4.py](../../backend/tests/test_exports_v4.py) `test_backup_restore_and_deleted_export_file_closure`; [test_validation_data_v4.py](../../backend/tests/test_validation_data_v4.py) `test_same_source_unbound_copy_and_old_backup_cannot_restore_deleted_cells`; [test_external_exports_v4.py](../../backend/tests/test_external_exports_v4.py) `test_typed_backup_and_delete_restore_close_external_dependents`; [test_rehearsal.py](../../backend/tests/test_rehearsal.py) `test_two_pairs_end_to_end_in_a_temporary_folder` | 새 결과/참고/외부 비교 의존 파일·삭제 이력의 백업 복원과 합성 전체 흐름. 배포 ZIP 검증은 S15 진행 중이며 실제 3PC/깨끗한 OS 설치는 후속이다. |
| O13 | [test_benchmark_s1.py](../../backend/tests/test_benchmark_s1.py) `test_wall_clock_is_not_sum_of_overlapping_stages`, `test_synthetic_measurement_does_not_pass_field_acceptance_or_missing_three_cam`, `test_retained_fps_claim_cannot_hide_fps_reduction` | 조건별 준비·집계 계약과 미측정 null을 검사했다. 원본/압축본/낮은FPS·1/3CAM 반복 실측은 하지 않았다. |
| O14 | [test_reset_s1.py](../../backend/tests/test_reset_s1.py) `test_interrupted_file_cleanup_retries_fixed_generation_and_preserves_new_s1_results`, `test_old_worker_cannot_publish_after_reset`; [test_deployment_v4.py](../../backend/tests/test_deployment_v4.py) `test_first_and_repeated_reset_preserve_new_s1_run_and_all_its_parents` | 초기화·중단·반복·새 S1 kind 보호 합성 통과. 2026-10-04 실제 로컬 전환과 재실행도 아래 별도 근거로 확인했다. |

### 실제 로컬 S1 전환 기록 — 2026-10-04

운영 담당 root가 기존 로컬 데이터 폴더를 직접 점검하고 보호된 로컬 백업 후 S1 초기화를 실행했다. 개인정보·원본 경로와 대상 이름은 이 대장에 싣지 않는다.

- 전환 전 DB schema4, 대상2·실행9·step111·계정2. 세션 정보를 제거한 원본 DB와 검증된 전환 전152파일을 소스 저장소 밖에 백업했다.
- 전환 후 대상2·계정2가 보존되고 구 실행/step/점수시트/기본결과는0이다. 원입력2개와 영상 참조6개의 hash가 전환 전과 일치했다. 같은 명령의 재실행은 complete였고 원격 정리 대기는0이다.
- 전환 후14파일 백업을 새 폴더에 실제 복원하여13개 참조를 검사했다. 초기화 이전 백업 복원은409로 차단되는 것을 확인했다.
- 이는 실제 로컬 데이터 전환·복원 근거다. 깨끗한 OS의 배포 ZIP 설치, 현장 LAN의 실제3PC, 참가자 영상 정확도/속도 실측은 여전히 별도 후속이다.

### 2026-10-04 최종 통합 중 관련 회귀

전체 backend 검사에서 발견한 삭제 이력의 오래된 2필드 기대값 4건과 합성 삭제 대상 ID 충돌에 따른 복원 오류 2건을 수정했다. 삭제 이력은 `(case_id, event_id, participant_id)`로 검사하며, 무관한 삭제 사례 fixture는 보존할 실제 사례와 다른 안정 ID를 사용한다. 제품의 안정 ID 기반 삭제 보호를 완화하지 않았다.

`uv run --locked python -X utf8 -m unittest tests.test_intake_v3 tests.test_reset_s1 tests.test_settings tests.test_deletion_restore_v4 -v`는 **36개, 61.450초 통과**했다. 여기의 구판 접수 fixture는 원입력·동의·백업 보호 회귀이며 구판 산식의 S1 골든값 전용이 아니다. 특히 `test_changed_participant_id_cannot_resurrect_same_case_from_older_backup`은 참가자 ID 변경 뒤 삭제된 동일 사례가 반복 복원으로 살아나지 않는지 확인한다. 이 결과는 해당 파일 회귀이며 최종 전체 통과 수치로 합산하지 않는다.
