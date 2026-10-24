# K-DOG PR-PA08 전처리 병렬화와 검증 재사용

버전: v1.0 · 2026-10-24 · 기준: PA07 병합 `bdd5789` · 브랜치: `veluga/preprocess-reuse-parallel` · 상태: 구현·관련 검증·독립 cold review 조치 완료, 전체 회귀·배포·실측 대기

상위: [전체 계획](K-DOG_AI병렬화계획_v1.0_20261024.md), [실행 대장](K-DOG_AI병렬화_검증실행대장_v1.0_20261024.md), [cold review](K-DOG_AI병렬화_ColdReview_v1.0_20261024.md)

## 범위와 불변 조건

사용자 요청에 따라 전처리의 중복 디코딩/인코딩·검증을 줄이고 최대 두 구간을 병렬 처리한다. 구현 → 검증 → 두 subagent 독립 cold review → 수용 수정·재검증 → 문서 업데이트 → 병합 순으로 진행한다. 같은 별도 실측 DB·자료·CAM1/2/4·N4로 전체 분석과 리포트를 한 번 확인하며, CAM3 원본·이전 결과를 보존한다. 누적 $4.79184225의 기존 원장과 $50 도달 전 최대 비용 선예약 차단을 유지한다. 관찰/채점/결측/오디오 규칙, 논리 관찰창, 모델·prompt·FPS/해상도·사고 수준과 운영 기본값 1은 바꾸지 않는다.

## 구현

- 같은 구간의 원본 FPS형과 AI형을 한 FFmpeg 입력 디코더에서 만들며 AI형을 이미 손실 인코딩한 원본형에서 다시 만드는 작업을 줄인다. 필요한 두 출력은 유지한다. 구간 간 임의 stream-copy로 비-keyframe을 버리거나, FPS를 낮춰 빈 프레임을 복제하지 않는다. 실제 이미지가 이전 두 단계 손실 인코딩 결과와 byte 단위로 같다는 보장은 하지 않는다.
- AI의 기준 선택은 실제 원본형 mux 시계의 초별 첫 실제 프레임이다. 공유 디코딩 결과의 프레임 수/PTS를 원본형의 실제 선택 인덱스와 대조하며, 불일치 시 기존 원본형 기반의 독립 AI 생성 경로로 검증한다. 공유 출력 실패 시 부분 파일을 성공으로 채택하지 않고 원본형 독립 생성부터 재검증한다.
- 원본형과 AI형은 B-frame 없이 실제 프레임을 해석한 뒤 마지막 표시 끝만 무손실 재포장한다. 최종 packet PTS/수를 재포장 전 디코딩한 프레임과 대조하고 실제 최종 파일 시각을 사용한다. 기존 원본 대응 2ms·whole-observation·evidence 경계 검사를 유지한다. 시각을 임의 metadata로 덮어쓰거나 관찰량을 늘리지 않는다.
- 새 `s1-cut-5-shared-decode`는 구간 최대 2개, codec thread 2개를 고정한다. 입력·출력마다 FFmpeg 스레드를 제한한다. 새 구간은 한 슬롯이 끝난 뒤에만 배정하고 결과는 원래 순서로 고정한다. 입력 revision/행위자/점유를 재검증하며 치명 오류에서는 추가 배정을 멈추고 모든 자식을 수습한 뒤 실패 기록·OS 잠금 해제로 진행한다.
- 전처리 시도 내부에서 프레임 검사와 파일 fingerprint를 결속한다. Windows에서는 metadata 시각 복원이 가능하므로 매 검사에 실제 SHA-256을 포함하고 내용 hash 생략을 주장하지 않는다. 이미 계산·확인한 digest만 파일 포인터의 hash 필드에 재사용한다. POSIX는 기존 metadata change 시각도 확인한다. 새 요청·재사용·기존 batch 열람의 독립 hash 검증을 유지하며 전역/영구 신뢰 cache를 만들지 않는다. 원본과 파생 파일 변경·revision/claim 교체·비활성 actor를 성공으로 채택하지 않는다.

## 검증·실제 실행 기록

초기 관련 22회귀에서 두 실패를 확인했다. 분수 초 remux의 0.977ms encoder tick 차이를 새 packet 검사가 기존 2ms 계약보다 엄격하게 거절한 건은 최종 실제 PTS와 기존 대응 검사를 사용하는 것으로 수정했다. 공유 AI 선택은 같은 인코딩 전 clock의 정확한 프레임 인덱스를 대조하여 인접 프레임 혼동을 막는다. 다른 실패는 병렬 완료 순서를 직렬 순서로 가정한 시험으로, 한 카메라 실패·다른 카메라 성공과 원본 보존의 의미를 유지하도록 수정했다. 관련 두 회귀는 5.620초에 통과했다. 새 계량 시험의 upload receipt/storage ref 오용도 수정 후 통과했다. 최종 전처리 29회귀가 63.119초에 통과했다. 앞선 관련 98개는 138.720초에 통과했으며 최종 전체/배포/실측은 수행 후 갱신한다.

독립 subagent 두 명이 관찰/시계/오디오와 병렬/파일 무결성을 나눠 검토했다. P1 1건: clock 검사 후 hash 전 파일 교체가 새 identity로 채택되는 경합을 수용해 clock 생성 전후의 identity를 묶고 remux 입력·최종 packet 검사·metadata/hash까지 같은 파일인지 검증한다. +20ms 실제 PTS 교체가 HTTP409/완료 0으로 거절됐고 관련 독립 3개는 5.732초·5.610초에 통과했다. P2 1건: 성공 done snapshot 직후 peer 실패를 놓치고 refill하던 경합을 수용해 자식의 치명 오류가 즉시 stop을 선언하도록 했다. 같은 probe의 배정/시작이 3개에서 2개로 줄었고 독립 새 회귀는 2.712초에 통과했다. 최종 미해결 P1/P2·제품 blocker는 없다.

추가 P1 1건은 root의 Windows 합성 변조 점검에서 발견했다. `st_ctime`이 생성 시각이므로 같은 크기 변조 후 mtime을 복원하면 기존 stat fingerprint가 같았다. 중간 수정의 WinAPI ChangeTime도 일반 handle의 전체 FILE_BASIC_INFO 복원으로 되돌릴 수 있음을 reviewer가 재현했다. 최종 제품은 이 metadata 신뢰 분기를 제거하고 Windows에서 실제 SHA-256을 clock부터 발행까지 매번 결속한다. 전체 timestamp 복원 후 stat는 같고 내용만 다른 파일을 거절하는 회귀를 포함한 최종 4개가 root 5.297초·독립 5.120초/5.001초에 통과했다. 제품 발견 총 2P1/1P2를 해소했다. 앞선 두 후보의 미완료 전체 회귀·배포물·검증 기록은 보존하며 이 후보들로 실제 전처리나 유료 분석을 실행하지 않았다.

관찰 담당자는 합성 VFR(무음/지연/앞선 오디오)·저FPS·분수 초 6종을 PA07 기준과 대조했다. 실제 source PTS·offset·오디오 범위·whole/evidence 의미가 일치했고 원래 부족한 관찰도 부족으로 유지했다. 지연 오디오에서는 공유 선택 불일치 후 독립 AI 경로가 동일한 실제 선택을 보존했다. 합성 original/AI 12파일은 Chromium 로드·끝 10ms 앞 탐색 오류 0이었다. reviewer는 실제 키·참가자·실측 DB·리포트를 열지 않았다.

관련 브라우저 검증은 분석/키 전환 18개(2.2분)와 전처리/접수 상태 18개(1.4분)로 총 36개 통과했다. 배포 빌드와 현재 Windows의 내장 런타임 설치·변조 거절·업무/재시작·발급 봉인/복원·계정 경계·재설치 보존 검증도 외부 AI 0회로 통과했다. 새 PC/OS 검증은 아니다.

외부 실행 helper도 두 reviewer가 검토했다. 제품 발견과 별도로 helper P1 1건(기존 예산 원장 유실 시 신규 원장을 만들어 누적 지출을 제외), P2 2건(카메라별/대표 음성 변경을 총량 검사만으로 놓침, 완료 batch 재조회 시간을 새 전처리 시간으로 발행)을 수용했다. 기존 74회·최소 $4.79184225 원장 필수, view별 음성/관찰·대표 음성·결손 범위 대조, 기존 request 시작/완료/실패 거절과 fsync 최초시도 marker로 수정했다. 합성 독립 재검토에서 모두 해소됐고 실제 자료는 열지 않았다. 정확히 $50에 닿는 다음 예약 차단·정리 허용, null 계량 전액예약·0과 불명 구별, 원장 유실/불충분 이력 거절은 실제 HTTP 0회로 확인했다.

실제 실행은 원본 11개·raw 영상 4개·이전 SYNC/OPT 전달본을 hash로 보존한다. 전처리 시간과 분석→PDF 시간을 분리하고 FFmpeg/ffprobe 작업별 경과·호출 수·실제 겹침을 기록한다. 실제 호출 전 모든 항목군의 근거 범위·whole-observation gate를 이전 고정 자료와 대조한다. 한 번의 기능 기록은 일반 SLA/P50/P95/독립 사람 정확도·기존 전문가/현장 인수 완료가 아니다.

## 버전·자료 경계

2026-10-24 확인: 최신 Python [3.15.1](https://www.python.org/downloads/release/python-3151/)·3.14 문서의 3.14.9에 대해 프로젝트 `>=3.14,<3.15`와 기존 배포 pin 3.14.8을 유지한다. 표준 [ThreadPoolExecutor](https://docs.python.org/3.14/library/concurrent.futures.html)의 최대 worker·대기/종료 계약을 사용한다. 최신 [FFmpeg 9.0.2](https://ffmpeg.org/download.html)는 기존 배포와 같으며 [복수 출력·스레드 옵션](https://www.ffmpeg.org/ffmpeg.html)을 확인했다. 최신 [Pydantic 2.14.1](https://pypi.org/project/pydantic/) 대비 기존 2.13.5 pin을 유지한다. 관련 없는 의존성/lockfile/DB schema 변경은 없다. G01/G04 계산 양식·CAM3 동기화·전문가/현장 인수 대기는 별도로 유지한다.

잠금 Python 의존성 25개의 공식 PyPI registry를 재조회했고 최신/선택 버전이 같은 날짜 [PA05 배포 의존성 표](K-DOG_AI병렬화_검증실행대장_v1.0_20261024.md#pa05-배포-의존성-확인--2026-10-24)와 같았다. frontend는 같은 날짜 PA04의 공식 registry/호환성 기록과 선택 pin을 유지했다. [Gemini 3.8 Flash 공식 요율](https://ai.google.dev/gemini-api/docs/whats-new-gemini-3.8)도 입력 $0.75/M·출력/사고 $3.75/M을 확인했으며 실제 청구 확인과 구별한다.

Windows 시각 의미는 [Python os.stat](https://docs.python.org/3.14/library/os.html#os.stat_result.st_ctime), timestamp 전체 복원 반례는 [Microsoft FILE_BASIC_INFO](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_basic_info)와 [SetFileInformationByHandle](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-setfileinformationbyhandle)를 확인했다. WinAPI/ctypes는 반례 시험에만 사용하며 제품 실행 경로에는 새 native API 의존성이 없다.
