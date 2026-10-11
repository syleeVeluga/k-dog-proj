import type { Page } from '@playwright/test';

// 767px 이하에서는 메뉴가 서랍이라 먼저 「메뉴」 버튼으로 연다.
export async function openMenu(page: Page, label: string) {
  const navigation = page.getByRole('navigation', { name: '주 메뉴' });
  const toggle = page.getByRole('button', { name: '메뉴', exact: true });
  await navigation.or(toggle).first().waitFor();
  if (!(await navigation.isVisible())) await toggle.click();
  await navigation.getByRole('button', { name: label, exact: true }).click();
}
