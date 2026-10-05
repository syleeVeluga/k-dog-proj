# PR-D00 FFmpeg 최소 빌드

버전: v1.0 · 2026-10-05 · 상태: 구현 완료 (2026-10-05) · 선행: 없음 · 기준: main `6376311`

상위: [설치·배포 개선 계획](K-DOG_설치배포개선계획_v1.0_20261005.md). 공통 절차는 [S1 계획 §7](../개발반영_20261003/K-DOG_개발반영계획_v1.0_20261003.md)을 적용한다.

브랜치 제안: `veluga/d00-ffmpeg-minimal-build` · 권장 PR 제목: `build: 배포용 FFmpeg 최소 빌드와 소스 동봉`

## 문제와 결과

S1 전처리 계약은 `libx264`·CRF 20을 고정한다 ([preprocess_v4.py:22](../../backend/app/preprocess_v4.py#L22), [preprocess_v4.py:264](../../backend/app/preprocess_v4.py#L264)). `libx264`를 포함하면 FFmpeg 전체가 GPL이 되므로, FFmpeg를 함께 배포하려면 **배포한 바이너리의 대응 소스(Corresponding Source) 전체**를 제공해야 한다 ([FFmpeg 법률 안내](https://ffmpeg.org/legal.html)).

처음 후보였던 gyan.dev essentials 빌드에는 외부 라이브러리가 약 33개 들어 있다. 그런데 FFmpeg 커밋 링크만 제공되고 라이브러리 소스 묶음은 없다 ([gyan.dev builds](https://www.gyan.dev/ffmpeg/builds/)). 이 빌드를 재배포하면 우리가 33개 라이브러리의 정확한 소스를 모두 모아 제공해야 하므로 사용하지 않는다 (상위 계획 Q01, 결정 K07).

이 PR은 K-DOG에 필요한 것만 넣은 FFmpeg를 **직접 빌드하는 스크립트**를 추가한다. 빌드 결과에는 대응 소스 묶음이 함께 생기며, D01이 이를 바이너리와 같이 패키지에 동봉한다. 동봉 방식은 3년 제공 약속이나 다운로드 서버 유지가 필요 없는 가장 단순한 준수 방법이다.

## 빌드 범위

| 구성 | 포함 이유 | 라이선스 |
| --- | --- | --- |
| FFmpeg 9.0.2 기본 기능 (내장 디코더·demuxer·muxer·필터·AAC 인코더) | 카메라 MP4/MOV/MKV/WebM/AVI 입력([media.py:16](../../backend/app/media.py#L16)), H.264/HEVC/AAC 디코딩, MP4 출력, `select` 필터, 시험용 `lavfi` | LGPL 2.1+ (GPL 활성화로 전체 GPL 2+) |
| x264 (`stable` 브랜치 고정 커밋) | 전처리 클립 인코딩 `libx264` | GPL 2+ |
| zlib (고정 버전) | 리포트 장면 PNG 출력([report_runs_v4.py:416](../../backend/app/report_runs_v4.py#L416)) | zlib |

설정 원칙:

- `--enable-gpl --enable-libx264 --enable-zlib --disable-autodetect --enable-w32threads`를 사용한다. 자동 감지를 끄면 빌드 PC에 있던 다른 라이브러리가 섞여 들어가지 않는다. 다만 스레드 지원도 자동 감지 대상이므로 `--enable-w32threads`로 명시한다. 그렇지 않으면 단일 스레드로 빌드되어 큰 360도/HEVC 영상 처리가 매우 느려질 수 있다.
- 정적 빌드로 `ffmpeg.exe`·`ffprobe.exe` 두 파일만 만든다. x264는 `--enable-static`으로, zlib은 고정 소스를 별도 prefix에 빌드한다. FFmpeg는 `--pkg-config-flags=--static --extra-ldflags=-static`으로 링크하여 MSYS2의 `libwinpthread-1.dll`·`libgcc_s_seh-1.dll`·`zlib1.dll`에 의존하지 않게 한다. `ffplay`와 문서는 빼고, `--enable-nonfree`와 `--enable-version3`는 쓰지 않는다.
- 결과 라이선스는 **GPL 2 이상**이다.
- K-DOG는 `ffmpeg.exe`를 별도 프로그램으로 명령줄 실행만 하고 링크하지 않는다. 이런 관계는 일반적으로 별개 프로그램의 단순 집합(GPLv2 §2)으로 해석되어 K-DOG 코드에는 GPL 의무가 생기지 않는다. 최종 판단은 상위 Q01의 확인 결과를 따른다. 동봉하는 `ffmpeg.exe`는 수정하거나 암호화하지 않는다.

## 파일별 변경

| 파일 | 변경 | 구현 내용 |
| --- | --- | --- |
| `scripts/ffmpeg/build-ffmpeg.sh` | 신설 | MSYS2 UCRT64 셸에서 실행. 고정 URL·SHA-256으로 FFmpeg·x264·zlib 소스를 받고, 해시를 확인한 뒤 정적 빌드한다. 결과는 `releases/.cache/ffmpeg-<버전>-kdog/`에 둔다 |
| `scripts/ffmpeg/README.md` | 신설 | 빌드 PC 준비(MSYS2 설치, 필요한 패키지), 실행 명령, 버전 갱신 방법 |
| (빌드 결과, 커밋하지 않음) | 생성 | `bin/ffmpeg.exe`·`bin/ffprobe.exe`, `source/`(세 소스 원본 압축 파일 + `build-ffmpeg.sh` 사본 + 실제 configure 명령), `licenses/`(GPLv2·LGPLv2.1 전문, x264·zlib 라이선스, 정적으로 들어간 mingw-w64 런타임·winpthreads 고지), `build.json`(버전, 소스·바이너리 SHA-256, configure 명령, 빌드 일시) |
| `backend/tests/test_packaging.py` | 수정 | 빌드 결과 폴더가 있을 때 `build.json`과 실제 파일 해시가 일치하는지, `licenses/`·`source/`가 있는지 확인 (없으면 명시적 skip) |

빌드 결과는 바이너리이므로 저장소에 커밋하지 않는다. `releases/`가 git 무시 대상인지 다시 확인한다. 같은 스크립트와 같은 고정 소스로 언제든 다시 만들 수 있어야 한다.

## 구현 순서

1. 버전을 다시 확인한다: FFmpeg 최신 안정판, x264 `stable` 최신 커밋, zlib 최신, MSYS2 설치본. 각각의 SHA-256을 스크립트 상수로 고정한다.
2. 빌드 스크립트를 작성하고 개발 PC에서 실제로 빌드한다.
3. `ffmpeg -buildconf`의 configure 옵션에 외부 라이브러리가 `libx264`·`zlib`뿐인지 확인한다.
4. 제품과 시험이 쓰는 기능이 모두 있는지 확인한다: `-encoders`(`libx264`, `aac`, `png`), `-decoders`(`h264`, `hevc`, `aac`), `-demuxers`(`mov`, `matroska`, `avi`), `-muxers`(`mp4`, `image2`), `-filters`(`select`, `fps`, `scale`), 입력 장치 `lavfi`와 시험 소스(`testsrc`, `testsrc2`, `sine`), `-protocols`(`file`, `pipe`). `ffmpeg.exe`·`ffprobe.exe`가 시스템 DLL에만 의존하는지 `objdump -p`의 `DLL Name`으로 확인한다.
5. 빌드한 FFmpeg를 PATH 앞에 둔 상태에서 전처리·리포트 장면·리허설 시험을 실행한다.

## 검증과 완료 조건

- 빌드한 FFmpeg를 PATH 맨 앞에 둔 상태에서 backend 전체 시험(특히 `test_preprocess`, `test_preprocess_v4`, `test_preprocess_api_v4`, `test_report_runs_v4`, `test_rehearsal`)이 통과한다. 개발 환경 FFmpeg 8.1.1과 결과가 다르면 원인과 영향을 기록한다.
- `-buildconf`에 `--enable-w32threads`가 있고, 실행 파일이 시스템 DLL 외에 의존하지 않는다.
- `build.json`의 소스 해시가 고정값과 같고, `source/`의 파일만으로 같은 configure 명령을 다시 실행할 수 있다. 같은 빌드 PC에서 한 번 더 빌드해 확인한다.
- `ffmpeg -L`이 GPL 2 이상으로 표시되고, `-buildconf`에 다른 외부 라이브러리가 없다.
- backend 전체 시험과 `git diff --check`가 통과한다.

## 위험과 대응

| 위험 | 대응 |
| --- | --- |
| 실제 카메라 파일(INSV 등)이 기본 디코더로 열리지 않음 | 지원 범위는 지금과 같다 (현재 입력 허용 형식은 mov·matroska·webm·avi). 실제 파일 호환성은 후속 대장 E01에서 확인한다. 필요한 기능이 있으면 그 라이브러리만 추가하고 소스 묶음에도 넣는다 |
| 빌드 환경 차이로 결과가 달라짐 | MSYS2 패키지 목록과 컴파일러 버전을 `build.json`에 기록한다. 바이너리가 비트 단위로 같을 필요는 없고, 소스와 configure 명령이 같으면 된다 |
| 빌드 실패나 시간 부담 | FFmpeg를 올릴 때만 다시 빌드한다. 평소 릴리즈는 캐시된 결과를 해시로 확인한 뒤 사용한다 |

## 구현 및 검증 기록

- [x] 구현·변경 파일 및 commit/PR 기록
- [x] FFmpeg·x264·zlib·MSYS2 최신·선택 버전·확인일·근거 기록
- [x] `-buildconf`·기능 목록·시험 결과와 바이너리 SHA-256 기록
- [x] 리뷰 발견사항과 수용/보류/거절·수정·재검증 기록
- [x] D01 인계 사항(빌드 결과 경로·`build.json` 형식) 기록

### 구현 (2026-10-05)

브랜치 `veluga/d00-ffmpeg-minimal-build`, [PR #47](https://github.com/syleeVeluga/k-dog-proj/pull/47). 변경 파일: `scripts/ffmpeg/build-ffmpeg.sh`(신설), `scripts/ffmpeg/README.md`(신설), `backend/tests/test_packaging.py`(`test_ffmpeg_build_manifest_matches_files`). 계획과 달라진 점:

- 병렬 컴파일 수를 `KDOG_FFMPEG_JOBS`(기본 4)로 둔다. 개발 PC에서 `nproc`(16) 병렬로 `cc1.exe: out of memory`가 났다 (커밋 여유 메모리 약 4.6GB).
- 시스템 DLL 확인은 이름 목록 대신 "System32에 실제로 있는 DLL 또는 UCRT API-set(`api-ms-win-crt-*`)"으로 판단한다. FFmpeg 기본 입력 장치(vfwcap·gdigrab)가 `AVICAP32`·`GDI32` 등을 가져오기 때문이다.
- 재빌드 확인을 위해 `KDOG_FFMPEG_SOURCES`(소스 폴더)와 `KDOG_FFMPEG_OUT`(결과 폴더)를 둔다. Git Bash에서 MSYS2 bash를 부르면 환경변수가 넘어가지 않으므로 UCRT64 셸이나 PowerShell에서 실행한다.

### 버전 확인 (2026-10-05)

| 대상 | 최신 확인 | 선택 | 근거 |
| --- | --- | --- | --- |
| FFmpeg | 9.0.2 (2026-09-18) | 9.0.2 | [ffmpeg.org download](https://ffmpeg.org/download.html). `ffmpeg-9.0.2.tar.xz.asc` PGP 서명 확인: "Good signature", 키 `FCF9 86EA 15E6 E293 A564 4F10 B432 2F04 D676 58D8`. SHA-256 `8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e` |
| x264 | `stable` 최신 `b35605ace3ddf7c1a5d67a2eb553f034aef41d55` (2025-06-08) | 같음 | [code.videolan.org API](https://code.videolan.org/api/v4/projects/videolan%2Fx264/repository/branches/stable). GitLab 압축 파일 SHA-256 `6eeb82934e69fd51e043bd8c5b0d152839638d1ce7aa4eea65a3fedcf83ff224` |
| zlib | 1.3.2 (2026-02-17) | 1.3.2 | [madler/zlib v1.3.2](https://github.com/madler/zlib/releases/tag/v1.3.2). SHA-256 `d7a0654783a4da529d1bb793b7ad9c3318020af77667bcae35f95d0e42a792f3`는 GitHub 게시 digest와 일치 |
| MSYS2 도구 | 2026-10-05 `pacman -Syu` 후 최신 | gcc 16.2.0-4, binutils 2.47-3, mingw-w64 crt/winpthreads 14.0.0.r426, nasm 3.02-1, pkgconf 3.0.7-1, make 4.4.1-3 | 개발 PC `D:\msys64` (원래 설치본 2023-10-26, gcc 13.2.0). 정확한 목록은 `build.json`의 `toolchain` |

code.videolan.org는 스크립트 다운로드에 x264 압축 파일 대신 봇 확인 HTML(7KB)을 준 적이 있다. 고정 SHA-256 검사가 이를 거절했고, 스크립트는 받은 파일을 지우고 브라우저로 받거나 이전 빌드의 `source/`에서 복사하라고 안내한다.

### 빌드 결과와 기능 확인

결과 `releases/.cache/ffmpeg-9.0.2-kdog/` (git 무시 대상):

- `bin/ffmpeg.exe` SHA-256 `141b21b712f782eec5b19a17a55bc34f4d8ef5c8168270aa04ab520158d8a2c6` (33,194,496 B)
- `bin/ffprobe.exe` SHA-256 `4c9cb35bbaecade8915131b790045960dca782e55906da75f104917999517f6b` (32,993,280 B)
- `-buildconf`: `--enable-gpl --enable-libx264 --enable-zlib --disable-autodetect --enable-w32threads --disable-ffplay --disable-doc --pkg-config-flags=--static`와 경로 옵션뿐이다. 다른 외부 라이브러리는 없다.
- `-L`: "GNU General Public License ... either version 2 of the License, or (at your option) any later version".
- 의존 DLL: `KERNEL32`, `USER32`, `GDI32`, `SHELL32`, `ole32`, `OLEAUT32`, `SHLWAPI`, `AVICAP32`, `WS2_32`, `bcrypt`와 UCRT `api-ms-win-crt-*`뿐이다. `libwinpthread-1.dll`·`libgcc_s_seh-1.dll`·`zlib1.dll` 의존은 없다.
- 기능: 인코더 `libx264`·`aac`·`png`, 디코더 `h264`·`hevc`·`aac`, demuxer `mov,mp4,…`·`matroska,webm`·`avi`, muxer `mp4`·`image2`, 필터 `select`·`fps`·`scale`·`testsrc`·`testsrc2`·`sine`, 입력 장치 `lavfi`, 프로토콜 `file`·`pipe` 모두 있다.
- 실행 파일에 빌드 PC의 절대 경로(`/d/dev/k_dog_proj/releases/.cache/...`)가 configure 문자열로 들어간다. 동작에는 영향이 없다.

재빌드 확인: 결과의 `source/build-ffmpeg.sh`(커밋된 스크립트와 동일)를 `KDOG_FFMPEG_SOURCES=<결과>/source`로 실행했다. 인터넷 없이 `source/`의 파일만으로 빌드되었다. 소스 해시와 명령은 결과 폴더 경로만 다르고 같다. 바이너리는 내장 경로 문자열 때문에 바이트가 다르다 (계획대로 비트 동일성은 요구하지 않음).

### 시험

- 빌드한 FFmpeg를 PATH 맨 앞에 둔 backend 전체 시험: **583개 OK, skip 2** (역사 원본 부재로 정상 skip). 이 실행은 리뷰 반영 전 빌드(같은 소스·옵션)로 했다.
- 최종 빌드로 `test_preprocess`·`test_preprocess_v4`·`test_preprocess_api_v4`·`test_report_runs_v4`·`test_rehearsal`·`test_packaging` 51개 OK (skip 없음). D01 패키지에 들어간 최종 바이너리(위 SHA-256)로 `test_preprocess_v4`·`test_preprocess_api_v4`·`test_report_runs_v4`·`test_rehearsal` 37개 OK.
- 개발 환경 FFmpeg 8.1.1(gyan.dev full)과 시험 결과 차이는 없다. 출력 바이트 비교는 하지 않았다.
- frontend build, 전체 e2e **45개 통과**, `git diff --check` 통과.

### cold review와 조치

독립 cold review 결과 P1 없음, P2 3건, P3 6건.

| 등급 | 발견 | 조치 |
| --- | --- | --- |
| P2 | zlib makefile이 복사 실패를 무시하면 FFmpeg가 MSYS2 기본 zlib로 조용히 링크될 수 있음 | 수용: 의존 라이브러리·헤더·`.pc` 설치 확인 후 실패 시 중단, README 표현 수정 |
| P2 | 기록된 FFmpeg configure 명령의 따옴표가 빠져 그대로 다시 실행할 수 없음 | 수용: `printf %q`로 기록 |
| P2 | 상대 경로 `KDOG_FFMPEG_OUT`이면 빌드 실패·MSYS2 zlib 대체 | 수용: 소스·결과 경로를 절대 경로로 변환 |
| P3 | 실행 파일에 빌드 PC 경로가 들어감 | 보류: 동작 영향 없음, 위에 기록 |
| P3 | `source/`에 빌드 도구 설치 정보 없음, mingw-w64 런타임 소스 미동봉 | 부분 수용: `configure-commands.txt`에 `pacman` 명령 추가. 런타임(CRT·winpthreads·libgcc)은 허용형·GCC Runtime Library Exception이며 GPLv2 §3의 시스템 구성요소 예외로 보는 것이 일반적이어서 라이선스·버전만 동봉한다. 벨루가의 Q01 확인에서 요구하면 MSYS2 소스 패키지를 추가한다 |
| P3 | FFmpeg `LICENSE.md`의 IJG 표기 | 수용(D01): 한국어 오픈소스 고지에 포함 |
| P3 | 해시 불일치 시 이전 빌드 `source/`의 파일 이름을 바꿔 그 빌드를 훼손 | 수용: 이름을 바꾸지 않고 안내만 출력 |
| P3 | 캐시 결과가 리뷰 반영 전 스크립트로 만든 것 | 수용: 최종 스크립트로 다시 빌드 (위 결과) |
| P3 | 시험이 결과 자체 일관성만 확인 | 수용: 스크립트 고정 SHA-256과 `build.json` 대조, configure 옵션·런타임 라이선스 폴더 확인 추가 |

### D01 인계

- 결과 경로: `releases/.cache/ffmpeg-9.0.2-kdog/` (`bin/`, `source/`, `licenses/`, `build.json`).
- `build.json` 형식 `kdog-ffmpeg-build-1`: `ffmpeg`·`x264`·`zlib` 버전, `license`, `built_at`, `compiler`, `toolchain`, `configure`(zlib·x264·ffmpeg 명령), `sources`(압축 파일 SHA-256), `files`(`bin`·`source`·`licenses` 아래 모든 파일의 상대 경로 → SHA-256). D01은 `files`와 실제 파일이 정확히 같을 때만 패키지에 넣는다.
- 한국어 오픈소스 고지에 IJG 표기를 넣는다.
- Q01 확인 담당자(벨루가)의 동봉물 점검 결과는 D01 기록에 남긴다.
