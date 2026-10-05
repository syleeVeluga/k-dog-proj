# K-DOG 배포용 FFmpeg 빌드

배포 패키지(D01)에 넣는 `ffmpeg.exe`·`ffprobe.exe`를 직접 빌드하고, 같은 폴더에 대응 소스·라이선스·`build.json`을 만든다. 구성은 FFmpeg 기본 기능 + libx264 + zlib이고 결과 라이선스는 GPL 2 이상이다. 근거와 결정은 [PR-D00 계획](../../docs/설치배포개선_20261005/K-DOG_PR-D00_FFmpeg최소빌드_v1.0_20261005.md)을 따른다.

FFmpeg를 올릴 때만 다시 빌드한다. 평소 릴리즈는 `releases/.cache/ffmpeg-<버전>-kdog/`의 결과를 `build.json` 해시로 확인한 뒤 사용한다. 결과는 바이너리이므로 커밋하지 않는다 (`releases/`는 git 무시 대상).

## 빌드 PC 준비 (개발자 PC만)

1. [MSYS2](https://www.msys2.org/)를 설치하고 전체 업그레이드한다: `pacman -Syu` (셸을 닫으라고 하면 닫고 한 번 더).
2. UCRT64 셸에서 도구를 설치한다.

   ```sh
   pacman -S --needed make diffutils mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-binutils \
     mingw-w64-ucrt-x86_64-pkgconf mingw-w64-ucrt-x86_64-nasm
   ```

MSYS2에 설치된 x264·zlib 패키지는 쓰지 않는다. 스크립트는 `PKG_CONFIG_LIBDIR`로 고정 소스로 만든 정적 라이브러리만 보이게 하고, 그 라이브러리와 헤더가 실제로 설치되었는지 확인한 뒤 FFmpeg를 빌드한다 (없으면 MSYS2 기본 경로로 대체되지 않도록 중단).

## 실행

MSYS2 **UCRT64** 셸에서 저장소 루트 기준으로 실행한다. FFmpeg `configure`가 공백 경로를 지원하지 않으므로 저장소 경로에 공백이 없어야 한다.

```sh
scripts/ffmpeg/build-ffmpeg.sh
```

- 소스는 고정 URL에서 `releases/.cache/ffmpeg-src/`로 받고 스크립트 상수의 SHA-256으로 확인한다. 해시가 다르면 중단한다.
  - code.videolan.org는 스크립트 다운로드에 x264 압축 파일 대신 봇 확인 페이지를 줄 수 있고, GitLab이 생성하는 압축 파일은 시간이 지나면 바이트가 달라질 수 있다. 이때는 받은 파일을 지우고 브라우저로 받거나 이전 빌드의 `source/`에서 복사한다. 장기 기준 원본은 빌드 결과의 `source/`다.
- 결과: `releases/.cache/ffmpeg-<버전>-kdog/`
  - `bin/ffmpeg.exe`, `bin/ffprobe.exe` — 정적 링크, 시스템 DLL에만 의존 (스크립트가 `objdump -p`로 확인)
  - `source/` — 세 소스 원본 압축 파일, `build-ffmpeg.sh` 사본, 실제 실행한 명령(`configure-commands.txt`)
  - `licenses/` — FFmpeg `COPYING.GPLv2`·`COPYING.LGPLv2.1`·`LICENSE.md`, x264·zlib 라이선스, 정적으로 들어간 mingw-w64 CRT·winpthreads·libgcc(GCC Runtime Library Exception) 라이선스
  - `build.json` — 버전, 소스 SHA-256, 컴파일러·MSYS2 도구 버전, 명령, 빌드 일시, `bin`·`source`·`licenses` 모든 파일의 SHA-256

환경변수:

| 변수 | 용도 |
| --- | --- |
| `KDOG_FFMPEG_SOURCES` | 소스 폴더 지정. 이전 빌드의 `source/`를 지정하면 인터넷 없이 같은 소스로 다시 빌드한다 |
| `KDOG_FFMPEG_OUT` | 결과 폴더 지정 (재빌드 확인용으로 기본 결과를 덮어쓰지 않을 때) |
| `KDOG_FFMPEG_JOBS` | 병렬 컴파일 수 (기본 4). 컴파일러 하나가 커밋 메모리를 약 1GB까지 쓰므로 `cc1.exe: out of memory`가 나면 줄인다 |

## 빌드 후 확인

```sh
OUT=releases/.cache/ffmpeg-9.0.2-kdog/bin
$OUT/ffmpeg.exe -hide_banner -buildconf    # 외부 라이브러리는 libx264·zlib뿐, --enable-w32threads 포함
$OUT/ffmpeg.exe -hide_banner -L | head -n 3 # GPL 2 이상
```

제품·시험 기능 확인 목록(인코더 `libx264`·`aac`·`png`, 디코더 `h264`·`hevc`·`aac`, demuxer `mov`·`matroska`·`avi`, muxer `mp4`·`image2`, 필터 `select`·`fps`·`scale`, `lavfi`와 `testsrc`·`testsrc2`·`sine`, 프로토콜 `file`·`pipe`)과 backend 시험은 빌드 결과의 `bin`을 PATH 맨 앞에 두고 실행한다. 결과는 PR-D00 실행 기록에 남긴다.

## 버전 갱신

1. FFmpeg 최신 안정판(서명 확인), x264 `stable` 브랜치 최신 커밋, zlib 최신 릴리즈를 확인한다.
2. 스크립트 상단 상수(버전·커밋·URL·SHA-256)를 바꾼다. 해시는 받은 파일로 직접 계산하고, 게시된 해시나 서명이 있으면 대조한다.
3. 빌드 후 위 확인과 backend 시험을 다시 실행하고, D01 패키지 시험으로 넘긴다.
