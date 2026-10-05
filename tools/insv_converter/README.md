# INSV 판독·MP4 변환 실험

버전: v1.0 · 2026-10-04 · 관련: S03/S05/S16, O06, E01

UI 없는 독립 CLI다. Python 표준 라이브러리와 PATH의 FFmpeg/ffprobe만 사용한다. 원본을 변경하지 않고 실행마다 새 결과 폴더를 만든다. 영상·JSON 기록은 저장소 밖에 저장해야 한다. K-DOG DB·채점 경로에 자동 연결하지 않는다.

## 실행

저장소 루트 `D:\dev\k_dog_proj`에서 실행한다. 기존 Python/FFmpeg 설치를 사용하므로 추가 패키지 설치는 없다.

```powershell
# 기본은 처음 10초의 모든 영상·오디오 스트림을 실제 디코딩한다.
python -X utf8 tools/insv_converter/convert.py inspect "D:/K-DOG/media/source.insv" --output-dir "D:/K-DOG/media-tests"

# 전체 원본 판독: 큰 파일은 오래 걸린다.
python -X utf8 tools/insv_converter/convert.py inspect "D:/K-DOG/media/source.insv" --output-dir "D:/K-DOG/media-tests" --full-decode

# 재포장: 압축 데이터를 복사해 MP4에 담는다. 용량 절감 목적이 아니다.
python -X utf8 tools/insv_converter/convert.py remux "D:/K-DOG/media/source.insv" --output-dir "D:/K-DOG/media-tests"

# 재인코딩: 먼저 60초 샘플, 원본 해상도·프레임 시각 유지, H.264 CRF23/AAC192k.
python -X utf8 tools/insv_converter/convert.py compress "D:/K-DOG/media/source.insv" --output-dir "D:/K-DOG/media-tests" --seconds 60

# Studio에서 만든 일반 화면 MP4를 축소·압축. 원본보다 확대하지 않는다.
python -X utf8 tools/insv_converter/convert.py compress "D:/K-DOG/media/flat.mp4" --output-dir "D:/K-DOG/media-tests" --layout flat --max-width 1920 --crf 23
```

`--seconds`를 빼면 변환은 전체 길이다. 모든 영상·오디오 스트림을 매핑하고 데이터/자이로 등 전용 트랙은 MP4 변환에서 제외한다. 영상 배치는 `--layout`으로 아는 경우만 기록한다. 기본 `unknown`이며 해상도로 360도 여부를 추정하지 않는다. FPS 감소·음성 제거·장면 잘라 붙이기를 하지 않는다. 재인코딩은 손실 변환이며 용량 감소를 보장하지 않는다. CRF가 높으면 더 강하게 압축하지만 세부 행동이 손실될 수 있다. HDR/10bit 입력은 이 실험의8bit 출력과 색·밝기 차이를 확인해야 한다.

결과의 `output.mp4`와 `report.json`에 원본/출력 SHA-256, 크기 비율, 도구 버전, 명령·설정, 스트림·길이·FPS·오디오 정보를 남긴다. 변환 출력은 전체 디코딩 후 성공으로 기록한다. 실패는 종료 코드1과 오류 기록을 남기며 부분 파일을 정상 결과로 표시하지 않는다. JSON에는 로컬 경로가 있으므로 공개 저장소에 올리지 않는다. 원본 해시를 전후 확인한다.

## 판정 경계와 스티칭

- `sample_passed`: 처음 N초 판독. 전체 파일은 미확인.
- `full_passed`: 전체 영상·오디오 판독. 브라우저 재생·동기 정확도·행동 판독은 별도 확인.
- INSV 판독 성공도 제품의 직접 분석 지원을 뜻하지 않는다. 앱의 `storage_only` 정책은 유지한다.
- 렌즈 하나의 원형 영상이나 두 렌즈 화면은 remux/compress로 정상360도 영상이 되지 않는다. 다중 파일 렌즈 세트 결합·스티칭은 수행하지 않는다.
- 개·보호자·관련 자극, 빠른 움직임, 귀/꼬리·표정, 발성, 길이·음성 동기를 비교한다. 처음60초만으로 전체 품질을 승인하지 않는다.

Insta360 공식 Media SDK는 UI 없는 스티칭 프로그램 `MediaSDKTest.exe`를 제공한다. 현재 SDK를 설치·번들·호출하지 않았다. 버전/제공 조건과 카메라 지원을 확인해 배포본을 확보한 뒤 `-help`와 공식 문서를 대조한다. SDK·모델/DLL·영상은 저장소 밖에 둔다.

```powershell
# 공식 SDK 예시, 미검증. 기존 출력 파일 경로를 재사용하지 않는다.
& "D:/Insta360SDK/bin/MediaSDKTest.exe" -inputs "D:/K-DOG/media/source.insv" -output "D:/K-DOG/media-tests/stitched-new.mp4" -stitch_type optflow -output_size 3840x1920 -enable_flowstate
```

SDK/Studio 결과 MP4를 본 CLI로 검사·압축할 수 있다. 원본 INSV 세트와 SDK/Studio 버전·설정·hash는 별도로 보존한다. 본 JSON은 앱 등록 요청이 아니며 앱 연결 시 실제 부모 upload ID/hash와 변환 계보를 명시한다.

## 버전 확인과 검증

2026-10-04 공식 자료 확인: [Python 최신 안정판3.14.8](https://www.python.org/downloads/), [FFmpeg 최신 안정판9.0.2 / 8.1 계열8.1.3](https://www.ffmpeg.org/download.html). 기존 프로젝트 환경 Python3.14.2, FFmpeg/ffprobe8.1.1을 선택해 공용 도구 업그레이드를 피하고 필요한 명령을 실제 시험한다. 새 의존성 설치·manifest 변경은 없다. 실행마다 외부 도구 버전을 기록한다. [FFmpeg API](https://www.ffmpeg.org/ffmpeg.html), [ffprobe API](https://ffmpeg.org/ffprobe.html), [scale 필터](https://www.ffmpeg.org/ffmpeg-filters.html#scale), [공식 Media SDK CLI](https://insta360develop.github.io/Insta360-Developer_Docs/en/x/desktop/media/).

```powershell
python -X utf8 -m unittest discover -s tools/insv_converter -p "test_*.py" -v
git diff --check
graft build
graft check
```

합성 MP4를 `.insv` 이름으로 생성하여 판독/재포장/압축과 실패 경계를 검증한다. 실제 카메라 INSV 지원 근거가 아니다. [E01 실측 후속](../../docs/개발반영_20261003/K-DOG_실측및확인후속대장_v1.0_20261003.md)은 계속 대기다.

2026-10-04 검증: 위 unittest9개 통과(5.502초). 재포장 전후 압축 패킷 hash 일치, 원본 hash 불변, 압축 후 FPS/길이/오디오·축소 크기, 무음 다중 영상 트랙 유지, 한글·공백 CLI 경로, 손상 입력 실패와 결과 충돌 방지를 확인했다. 문서 로컬 링크·공백 검사와 graft 동기 검사도 통과했다. 제품 코드 변경이 없어 backend/frontend 전체 회귀는 재실행하지 않았다.
