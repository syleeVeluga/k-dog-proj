import { test, expect } from '@playwright/test';
import { guessFromFilename } from '../src/uploadGuess';

test('파일명 규칙은 화면 안내(원본1→CAM1, 원본3→CAM2, 원본2→CAM3)만 따른다', () => {
  expect(guessFromFilename('원본1.mp4')).toEqual({ original: '1', camera: 'CAM1' });
  expect(guessFromFilename('원본3.MOV')).toEqual({ original: '3', camera: 'CAM2' });
  expect(guessFromFilename('원본2.mp4')).toEqual({ original: '2', camera: 'CAM3' });
  expect(guessFromFilename('원본 2.mp4')).toEqual({ original: '2', camera: 'CAM3' });
  expect(guessFromFilename('원본２.mp4')).toEqual({ original: '2', camera: 'CAM3' });
  expect(guessFromFilename('원본1-재촬영.mp4')).toEqual({ original: '1', camera: 'CAM1' });
  expect(guessFromFilename('1.mp4')).toEqual({ original: '1', camera: 'CAM1' });
  for (const name of ['원본1+원본2.mp4', '원본1_cam3.mp4', '원본3_CAM1.mp4', '원본1 2.mp4', '원본1.5배속.mp4', '원본1배속.mp4', '원본4.mp4', '원본10.mp4', '원본.mp4', '20261011.mp4', '11.mp4', 'three-browser-cam1.mp4', 'IMG_1.mp4', '촬영원본1.mp4', '']) expect(guessFromFilename(name), name).toBeNull();
});

test('녹화 도구의 회차_CAMk_설명과 CAMk 파일명을 카메라로만 제안한다', () => {
  for (const [filename, camera] of [['6_CAM1_복도-정면.mkv', 'CAM1'], ['6_CAM4_참여자-오른쪽.mkv', 'CAM4'], ['cam2_x.mp4', 'CAM2'], ['cam1.mp4', 'CAM1'], ['６_ＣＡＭ４_오른쪽.mkv', 'CAM4'], ['6_CAM10_x.mkv', 'CAM10']]) {
    expect(guessFromFilename(filename)).toEqual({ original: null, camera });
  }
  for (const filename of ['원본1_CAM3.mp4', '6_CAM3_원본1.mkv', '6_CAM0_x.mkv', '6_CAM1.mkv']) expect(guessFromFilename(filename)).toBeNull();
});
