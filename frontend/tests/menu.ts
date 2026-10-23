import type { Page } from '@playwright/test';

// 767px 이하에서는 메뉴가 서랍이라 먼저 「메뉴」 버튼으로 연다.
export async function openMenu(page: Page, label: string) {
  // 촬영은 독립 메뉴에서 제거됐다. 기존 기능 회귀는 탭 또는 보존한 직접 경로로 연다.
  if (label === '영상 파일 업로드' || label === '촬영 기록 (8구간)') {
    const task = label === '영상 파일 업로드' ? '영상 등록' : '촬영 기록';
    const tabs = page.getByRole('navigation', { name: '참가자 작업' });
    if (await tabs.isVisible()) await tabs.getByRole('button', { name: task, exact: true }).click();
    else await page.evaluate(route => { window.location.hash = route; }, label === '영상 파일 업로드' ? '#/recording/inbox' : '#/recording/record');
    return;
  }
  const navigation = page.getByRole('navigation', { name: '주 메뉴' });
  const toggle = page.getByRole('button', { name: '메뉴', exact: true });
  await navigation.or(toggle).first().waitFor();
  if (!(await navigation.isVisible())) await toggle.click();
  await navigation.getByRole('button', { name: label, exact: true }).click();
}
