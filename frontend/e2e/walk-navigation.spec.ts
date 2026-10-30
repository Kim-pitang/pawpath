import { expect, test, type APIRequestContext, type BrowserContext, type Page } from '@playwright/test';
import { buildRoute, pointAt, type LatLng, type RouteModel } from '../src/lib/navigation';

interface CourseData {
  id: number;
  name: string;
  route: LatLng[];
}

async function firstCourse(request: APIRequestContext): Promise<CourseData & { model: RouteModel }> {
  const courses: CourseData[] = await (await request.get('/api/courses')).json();
  return { ...courses[0], model: buildRoute(courses[0].route) };
}

async function moveTo(context: BrowserContext, point: LatLng) {
  await context.setGeolocation({ latitude: point[0], longitude: point[1], accuracy: 10 });
}

async function openNavigation(page: Page, courseId: number) {
  await page.goto(`/navigate?course=${courseId}`);
  await expect(page.getByTestId('navigation-map')).toBeVisible();
}

test.describe('GPS 길 안내', () => {
  test.use({ permissions: ['geolocation'], geolocation: { latitude: 37.4979, longitude: 127.0276, accuracy: 10 } });

  test('추천에서 이 코스로 산책을 누르면 지도 안내가 열린다', async ({ page, context, request }) => {
    const { model } = await firstCourse(request);
    await moveTo(context, pointAt(model, 0));
    await page.goto('/recommend');
    const card = page.getByTestId('course-card-1');
    const name = (await card.getByRole('heading').textContent())!;
    await card.getByRole('link', { name: '이 코스로 산책' }).click();
    await expect(page).toHaveURL(/\/navigate\?course=\d+&recommendation=\d+/);
    await expect(page.getByTestId('navigate-course-name')).toHaveText(name);
    await expect(page.getByTestId('navigation-map')).toBeVisible();
    await expect(page.locator('.pp-me')).toBeVisible();
    await expect(page.locator('path.nav-remaining')).toHaveCount(1);
  });

  test('코스에서 너무 멀면 도보 안내 대신 외부 길찾기와 시연 모드를 안내한다', async ({ page, request }) => {
    const { id } = await firstCourse(request);
    await openNavigation(page, id);
    await expect(page.getByTestId('nav-instruction')).toContainText('떨어져 있어요');
    // 멀리 있어도 지도는 내 위치가 아니라 가야 할 코스를 보여 준다.
    await expect(page.locator('path.nav-remaining')).toBeInViewport();
    const startLabel = await page.locator('.pp-marker-start').boundingBox();
    expect(startLabel!.width).toBeGreaterThan(24);
    const link = page.getByRole('link', { name: '카카오맵에서 출발점 길찾기' });
    await expect(link).toHaveAttribute('href', /^https:\/\/map\.kakao\.com\/link\/to\//);
    await expect(page.getByRole('button', { name: '시연용 위치로 걷기' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'GPS 없이 기록하기' })).toBeVisible();
    await expect(page.getByRole('button', { name: '산책 끝내기' })).toHaveCount(0);
  });

  test('가까우면 출발점까지 안내하고, 코스에 들어오면 산책을 시작한다', async ({ page, context, request }) => {
    const { id, model } = await firstCourse(request);
    const start = pointAt(model, 0);
    await moveTo(context, [start[0] + 0.003, start[1]]);
    await openNavigation(page, id);
    await expect(page.getByTestId('approach-summary')).toContainText('코스 출발점까지');
    await expect(page.getByText('직선으로 표시했어요')).toBeVisible();
    await expect(page.locator('path.nav-approach')).toHaveCount(1);
    await expect(page.getByRole('button', { name: '산책 끝내기' })).toHaveCount(0);

    await moveTo(context, start);
    await expect(page.getByTestId('walk-progress')).toBeVisible();
    await expect(page.getByRole('button', { name: '산책 끝내기' })).toBeVisible();
  });

  test('걸으면 진행률이 오르고, 이탈을 알리고, 완주 후 피드백으로 이어진다', async ({ page, context, request }) => {
    const { id, model } = await firstCourse(request);
    await moveTo(context, pointAt(model, 0));
    await openNavigation(page, id);
    const progress = page.getByTestId('walk-progress');
    await expect(progress).toHaveAttribute('aria-valuenow', '0');

    // 안내 문구가 실제 회전 지점에 맞게 바뀌는지 확인한다.
    const turn = model.turns.find((item) => item.at > 150)!;
    for (let meters = 40; meters <= turn.at - 60; meters += 40) {
      await moveTo(context, pointAt(model, meters));
    }
    await moveTo(context, pointAt(model, turn.at - 60));
    await expect(page.getByTestId('nav-instruction')).toContainText(/앞에서 (왼쪽으로|오른쪽으로|돌아서)/);

    // 절반까지 걷기
    const half = model.total / 2;
    for (let meters = turn.at - 60; meters <= half; meters += 60) {
      await moveTo(context, pointAt(model, meters));
    }
    await moveTo(context, pointAt(model, half));
    // 이 코스의 절반 지점은 43% 지점과 같은 길이라, 다음 걸음 전까지는 앞쪽 진행도로 보는 것이 맞다.
    await expect(async () => {
      expect(Number(await progress.getAttribute('aria-valuenow'))).toBeGreaterThanOrEqual(40);
    }).toPass();
    const reached = (await progress.getAttribute('aria-valuenow'))!;

    // 코스 이탈
    const here = pointAt(model, half);
    await moveTo(context, [here[0] + 0.002, here[1] + 0.002]);
    await expect(page.getByTestId('nav-instruction')).toContainText('벗어났어요');
    await expect(page.locator('path.nav-rejoin')).toHaveCount(1);
    await expect(progress).toHaveAttribute('aria-valuenow', reached);

    // 복귀 후 완주
    await moveTo(context, here);
    await expect(page.getByTestId('nav-instruction')).not.toContainText('벗어났어요');
    for (let meters = half; meters < model.total; meters += 60) {
      await moveTo(context, pointAt(model, meters));
    }
    await moveTo(context, pointAt(model, model.total));
    await expect(page.getByText('코스를 완주했어요!')).toBeVisible();

    await page.getByRole('button', { name: '피드백 남기기' }).click();
    await expect(page).toHaveURL(/\/walk$/);
    await expect(page.getByRole('heading', { name: /어땠나요\?/ })).toBeVisible();
    await page.getByRole('button', { name: '산책 만족도 5점' }).click();
    await page.getByRole('button', { name: /만족도 4점$/ }).nth(1).click();
    await page.getByRole('button', { name: '딱 좋았어요' }).click();
    await page.getByRole('button', { name: '날씨 만족도 3점' }).click();
    await page.getByRole('button', { name: '또 갈래요' }).click();
    await page.getByRole('button', { name: '피드백 남기기' }).click();
    await expect(page.getByTestId('affinity-change')).toBeVisible();

    // 새로고침해도 끝난 산책의 피드백 폼이 다시 나오지 않는다.
    await page.reload();
    await expect(page.getByRole('heading', { name: /어땠나요\?/ })).toHaveCount(0);
  });

  test('걷는 도중 그만두면 기록을 남기지 않는다', async ({ page, context, request }) => {
    const { id, model } = await firstCourse(request);
    const before: unknown[] = await (await request.get('/api/walks')).json();
    await moveTo(context, pointAt(model, 0));
    await page.goto('/map');
    await openNavigation(page, id);
    await expect(page.getByTestId('walk-progress')).toBeVisible();
    page.once('dialog', (dialog) => dialog.accept());
    await page.getByRole('button', { name: '나가기' }).click();
    await expect(page).toHaveURL(/\/map/);
    const after: unknown[] = await (await request.get('/api/walks')).json();
    expect(after.length).toBe(before.length);
  });
});

test.describe('GPS를 쓸 수 없을 때', () => {
  test('시연용 위치로 코스를 걸을 수 있고 화면에 시연용으로 표시된다', async ({ page, request }) => {
    const { id } = await firstCourse(request);
    await openNavigation(page, id);
    await page.getByRole('button', { name: '시연용 위치로 걷기' }).click();
    await expect(page.getByText('시연용 위치', { exact: true })).toBeVisible();
    await expect(page.getByText('실제 GPS가 아니라 코스를 따라 움직이는 시연용 위치예요.')).toBeVisible();
    const progress = page.getByTestId('walk-progress');
    await expect(progress).toBeVisible();
    await expect(async () => {
      expect(Number(await progress.getAttribute('aria-valuenow'))).toBeGreaterThan(5);
    }).toPass({ timeout: 15000 });

    await page.getByRole('button', { name: '산책 끝내기' }).click();
    await expect(page.getByRole('heading', { name: /어땠나요\?/ })).toBeVisible();
  });

  test('HTTPS가 아닌 주소에서는 이유를 안내하고 대안을 제공한다', async ({ page, request }) => {
    const { id } = await firstCourse(request);
    await page.addInitScript(() => Object.defineProperty(window, 'isSecureContext', { value: false }));
    await openNavigation(page, id);
    await expect(page.getByRole('alert')).toContainText('HTTPS');
    await expect(page.getByRole('button', { name: '시연용 위치로 걷기' })).toBeVisible();
    await page.getByRole('link', { name: 'GPS 없이 기록하기' }).click();
    await expect(page).toHaveURL(/\/walk\?course=\d+/);
    await expect(page.getByRole('button', { name: '산책 완료' })).toBeVisible();
  });

  test('코스 없이 들어오면 추천으로 안내한다', async ({ page }) => {
    await page.goto('/navigate');
    await expect(page.getByRole('link', { name: '오늘의 추천 보기' })).toBeVisible();
  });
});
