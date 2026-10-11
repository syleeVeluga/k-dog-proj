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
  for (const name of ['원본4.mp4', '원본10.mp4', '원본.mp4', '20261011.mp4', '11.mp4', 'cam1.mp4', 'three-browser-cam1.mp4', 'IMG_1.mp4', '촬영원본1.mp4', '']) expect(guessFromFilename(name), name).toBeNull();
});
