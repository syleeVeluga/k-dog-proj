// 파일명이 「원본1」「원본2」「원본3」(또는 숫자만 1·2·3)이면 화면 안내와 같은 카메라로 미리 채운다.
// 원본1 → CAM1 · 원본3 → CAM2 · 원본2 → CAM3. 녹화 도구의 N_CAMk_설명/CAMk_설명도 제안한다(서버 검사는 그대로).
export const CAMERA_BY_ORIGINAL: Record<string, string> = { '1': 'CAM1', '3': 'CAM2', '2': 'CAM3' };

export function guessFromFilename(filename: string): { original: string | null; camera: string } | null {
  const stem = filename.normalize('NFKC').replace(/\.[^./\\]+$/, '').trim();
  const camera = /^\d+_CAM([1-9]\d*)_/i.exec(stem) ?? /^CAM([1-9]\d*)(?:_|$)/i.exec(stem);
  if (camera) return /원본\s*[123]/.test(stem) ? null : { original: null, camera: `CAM${camera[1]}` };
  const match = /^원본\s*([123])(?!\d)(.*)$/.exec(stem) ?? /^([123])()$/.exec(stem);
  // 「원본1-재촬영」처럼 구분 기호 뒤에 글자만 붙은 이름만 인정한다. 다른 숫자나 cam 표기가 섞이면(원본1_cam3, 원본1+원본2) 추정하지 않는다.
  if (!match || /\d|cam/i.test(match[2]) || (match[2] && !/^[\s\-_(\[]/.test(match[2]))) return null;
  return { original: match[1], camera: CAMERA_BY_ORIGINAL[match[1]] };
}
