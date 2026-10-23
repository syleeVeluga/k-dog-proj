import type { Page } from '@playwright/test';

// 767px 이하에서는 메뉴가 서랍이라 먼저 「메뉴」 버튼으로 연다.
export async function openMenu(page: Page, label: string) {
  // 촬영은 독립 메뉴에서 제거됐다. 기존 기능 회귀는 탭 또는 보존한 직접 경로로 연다.
  if (label === '영상 파일 업로드' || label === '촬영 기록 (8구간)' || label === '전처리') {
    const task = label === '영상 파일 업로드' ? '영상 등록' : label === '전처리' ? '전처리' : '촬영 기록';
    const tabs = page.getByRole('navigation', { name: '참가자 작업' });
    if (await tabs.isVisible()) await tabs.getByRole('button', { name: task, exact: true }).click();
    else await page.evaluate(route => { window.location.hash = route; }, label === '영상 파일 업로드' ? '#/recording/inbox' : label === '전처리' ? '#/preprocess' : '#/recording/record');
    return;
  }
  const navigation = page.getByRole('navigation', { name: '주 메뉴' });
  const toggle = page.getByRole('button', { name: '메뉴', exact: true });
  await navigation.or(toggle).first().waitFor();
  if (!(await navigation.isVisible())) await toggle.click();
  await navigation.getByRole('button', { name: label, exact: true }).click();
}

export async function openPreprocessing(page: Page, id: string) {
  await openMenu(page, '참가자 접수');
  await page.reload();
  await page.getByLabel('검색', { exact: true }).fill(id);
  await page.getByLabel('행사 필터').selectOption('');
  await page.getByLabel('자료 상태 별 조회').selectOption('all');
  await page.getByRole('button', { name: `${id} 영상 등록`, exact: true }).click();
  await page.getByRole('navigation', { name: '참가자 작업' }).getByRole('button', { name: '전처리', exact: true }).click();
}
