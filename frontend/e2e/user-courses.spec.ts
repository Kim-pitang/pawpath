import { expect, test, type Page } from '@playwright/test';

const START: [number, number] = [37.5545, 126.9065];

/** 출발점에서 far까지 갔다가 돌아오는 GPX. 지점은 약 10m 간격이다. */
function gpx(name: string, far: [number, number]): string {
  const steps = Math.round(Math.hypot((far[0] - START[0]) * 110540, (far[1] - START[1]) * 88000) / 10);
  const there = Array.from({ length: steps }, (_, i) => [START[0] + ((far[0] - START[0]) * i) / steps, START[1] + ((far[1] - START[1]) * i) / steps]);
  const points = [...there, ...[...there].reverse(), START];
  const trkpts = points
    .map(([lat, lon], i) => `<trkpt lat="${lat.toFixed(7)}" lon="${lon.toFixed(7)}"><time>2026-10-30T07:${String(Math.floor(i / 60) % 60).padStart(2, '0')}:${String(i % 60).padStart(2, '0')}Z</time></trkpt>`)
    .join('');
  return `<?xml version="1.0" encoding="UTF-8"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><name>${name}</name><trkseg>${trkpts}</trkseg></trk></gpx>`;
}

async function importWalk(page: Page, name: string, far: [number, number]) {
  await page.goto('/my-walks/import');
  await page.getByLabel('GPX 파일').setInputFiles({ name: 'walk.gpx', mimeType: 'application/gpx+xml', buffer: Buffer.from(gpx(name, far)) });
  await expect(page.getByTestId('gpx-result')).toBeVisible();
  await page.getByLabel('산책길 이름').fill(name);
  await page.getByRole('button', { name: '산책길로 저장' }).click();
  await expect(page).toHaveURL(/\/my-walks\/\d+$/);
}

test('가져온 산책길은 저장하자마자 추천 후보가 되고, 빼면 사라진다', async ({ page }) => {
  const name = `망원정마당 왕복 ${Date.now()}`;
  await importWalk(page, name, [37.5512, 126.9034]);
  const panel = page.getByTestId('course-candidate');
  // 따로 누르지 않아도 저장과 함께 후보가 된다.
  await expect(panel.getByText('저장할 때 추천 후보에 넣었어요')).toBeVisible();
  await expect(panel.getByRole('button', { name: '추천 후보에 넣기' })).toHaveCount(0);
  await expect(panel.getByText('혼잡도와 경사는 측정할 수 없어')).toBeVisible();
  await expect(panel.getByText('주변 환경을 측정하지 않아')).toBeVisible();

  await panel.getByRole('link', { name: '지도에서 보기' }).click();
  await expect(page.getByTestId('selected-course-name')).toHaveText(name);
  const listItem = page.getByRole('list', { name: '코스 목록' }).getByRole('button', { name: new RegExp(name) });
  await expect(listItem).toContainText('내 산책길');
  await expect(page.getByText('혼잡도 확인 불가')).toBeVisible();
  await expect(page.getByText('경사 확인 불가')).toBeVisible();

  await page.getByRole('link', { name: '이 코스로 산책' }).click();
  await expect(page.getByTestId('navigate-course-name')).toHaveText(name);
  await expect(page.getByTestId('navigation-map')).toBeVisible();

  await page.goBack();
  await page.goBack();
  await expect(panel).toBeVisible();
  await panel.getByRole('button', { name: '추천 후보에서 빼기' }).click();
  await expect(panel.getByRole('button', { name: '다시 추천 후보로' })).toBeVisible();
  await page.goto('/map');
  await expect(page.getByRole('list', { name: '코스 목록' }).getByRole('button', { name: new RegExp(name) })).toHaveCount(0);
});

test('그늘을 모르는 긴 내 산책길은 폭염 때 이유와 함께 추천에서 빠진다', async ({ page }) => {
  const name = `긴 강변길 ${Date.now()}`;
  await importWalk(page, name, [37.541, 126.9065]);
  await expect(page.getByText('저장할 때 추천 후보에 넣었어요')).toBeVisible();

  await page.goto('/recommend');
  await page.getByRole('button', { name: '폭염', exact: true }).click();
  const excluded = page.getByTestId('excluded-courses');
  await excluded.locator('summary').click();
  const item = excluded.getByRole('listitem').filter({ hasText: name });
  await expect(item).toBeVisible();
  await expect(item).toContainText('그늘을 확인할 수 없어요');
});

test('다른 계정에는 내 산책길 코스가 보이지 않는다', async ({ page, browser }) => {
  const name = `혼자 보는 길 ${Date.now()}`;
  await importWalk(page, name, [37.5512, 126.9034]);
  await expect(page.getByText('저장할 때 추천 후보에 넣었어요')).toBeVisible();
  const courseId = new URL(await page.getByRole('link', { name: '지도에서 보기' }).evaluate((a: HTMLAnchorElement) => a.href)).searchParams.get('course');

  const other = await (await browser.newContext()).newPage();
  expect((await other.request.post('/api/auth/signup', { data: { login_id: `other${Date.now()}`, password: 'walk-with-dubu-1', name: '다른 보호자' } })).status()).toBe(201);
  await other.goto('/map');
  await expect(other.getByRole('list', { name: '코스 목록' })).toBeVisible();
  await expect(other.getByRole('list', { name: '코스 목록' }).getByRole('button', { name: new RegExp(name) })).toHaveCount(0);
  expect((await other.request.get(`/api/courses/${courseId}`)).status()).toBe(404);
  await other.context().close();
});
