import { expect, type Page } from '@playwright/test';

/**
 * 테스트 전용 로그인(서버의 E2E_LOGIN). Playwright는 실제 Google 화면을 지날 수 없으므로,
 * Google로 처음 로그인한 것과 같은 계정을 만들고 이 브라우저에 세션 쿠키를 넣는다. 같은 key는 같은 계정이다.
 */
export async function signIn(page: Page, key: string, name = '새 보호자') {
  const response = await page.request.post('/api/e2e/login', { data: { key, name } });
  expect(response.ok()).toBeTruthy();
  return response.json();
}
