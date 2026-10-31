import { expect, test, type Page } from '@playwright/test';

const VENUE = { latitude: 37.5559, longitude: 126.9105 };

/** 출발점에서 한 변 약 200m의 사각형을 도는 경로. 지점은 약 10m 간격이다. */
function loop(offsetLng = 0): [number, number][] {
  const d = 0.0018;
  const corners: [number, number][] = [
    [VENUE.latitude, VENUE.longitude],
    [VENUE.latitude + d, VENUE.longitude + offsetLng],
    [VENUE.latitude + d, VENUE.longitude + d + offsetLng],
    [VENUE.latitude, VENUE.longitude + d + offsetLng],
    [VENUE.latitude, VENUE.longitude],
  ];
  const points: [number, number][] = [];
  for (let i = 0; i < 4; i += 1) {
    for (let step = 0; step < 20; step += 1) {
      points.push([corners[i][0] + ((corners[i + 1][0] - corners[i][0]) * step) / 20, corners[i][1] + ((corners[i + 1][1] - corners[i][1]) * step) / 20]);
    }
  }
  return [...points, corners[0]];
}

const candidate = (offset: number, minutes: number, repeated: number) => ({
  route: loop(offset),
  distance_m: minutes * 60,
  duration_min: minutes,
  repeated_pct: repeated,
  start_snap_m: 1,
  fit: null,
});

const fitOf = (score: number, extra: Record<string, unknown> = {}) => ({
  score,
  level: 'good',
  summary: '두부에게 맞는 조용한 코스예요.',
  details: [],
  cautions: [],
  highlights: ['공원을 지나는 길이 약 40%', '큰 도로변 비율 약 0%'],
  start_label: '오후 4시',
  unknown: [],
  excluded: [],
  ...extra,
});

async function mockGenerate(page: Page, respond: (body: { latitude: number; longitude: number; duration_min: number }) => { status: number; json: unknown }) {
  const seen: { latitude: number; longitude: number; duration_min: number }[] = [];
  await page.route('**/api/routes/generate', async (route) => {
    const body = route.request().postDataJSON();
    seen.push(body);
    const { status, json } = respond(body);
    await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(json) });
  });
  return seen;
}

test.describe('산책길 만들기', () => {
  test.use({ permissions: ['geolocation'], geolocation: { ...VENUE, accuracy: 8 } });

  test('반려동물에 맞춰 평가한 점수, 측정한 특징, 이유를 보여 주고 선택한 후보의 설명이 바뀐다', async ({ page }) => {
    const seen = await mockGenerate(page, () => ({
      status: 200,
      json: {
        target_min: 30,
        notice: null,
        scored_for: '두부',
        fit_notice: null,
        candidates: [
          { ...candidate(0, 30, 4), fit: fitOf(84.2) },
          { ...candidate(0.0004, 28, 12), fit: fitOf(61.5, { level: 'caution', summary: '차가 다니는 길이 많아요.', cautions: ['큰 도로변 비율이 높아요'], highlights: ['큰 도로변 비율 약 55%'] }) },
        ],
      },
    }));
    await page.goto('/generate');
    await page.getByRole('button', { name: '현재 위치 사용' }).click();
    await page.getByTestId('generate-button').click();

    const candidates = page.getByTestId('generate-candidate');
    await expect(candidates).toHaveCount(2);
    expect(typeof seen[0]).toBe('object');
    await expect(candidates.nth(0)).toContainText('맞춤 84점');
    await expect(candidates.nth(0)).toContainText('공원을 지나는 길이 약 40%');
    await expect(page.getByText('두부에게 맞는 순서로 보여 드려요')).toBeVisible();
    await expect(page.getByTestId('generate-fit')).toContainText('두부에게 맞는 조용한 코스예요.');
    await candidates.nth(1).click();
    await expect(page.getByTestId('generate-fit')).toContainText('차가 다니는 길이 많아요.');
    await expect(page.getByTestId('generate-fit')).toContainText('큰 도로변 비율이 높아요');
  });

  test('현재 위치로 경로를 만들고 후보를 고른 뒤 내 산책길로 저장하면 추천 후보에 넣을 수 있다', async ({ page }) => {
    const seen = await mockGenerate(page, () => ({
      status: 200,
      json: { target_min: 30, notice: null, scored_for: null, fit_notice: null, candidates: [candidate(0, 30, 4), candidate(0.0004, 28, 12)] },
    }));
    await page.goto('/generate');
    await expect(page.getByTestId('generate-button')).toBeDisabled();
    await page.getByRole('button', { name: '현재 위치 사용' }).click();
    await expect(page.getByTestId('generate-button')).toBeEnabled();
    await page.getByTestId('generate-button').click();

    const candidates = page.getByTestId('generate-candidate');
    await expect(candidates).toHaveCount(2);
    expect(seen).toHaveLength(1);
    expect(seen[0].duration_min % 5).toBe(0);
    expect(Math.abs(seen[0].latitude - VENUE.latitude)).toBeLessThan(0.001);
    await candidates.nth(1).click();
    await expect(candidates.nth(1)).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByText('경사와 반려견 출입 여부는 확인하지 않았고')).toBeVisible();

    await page.getByLabel('산책길 이름').fill(`만든 길 ${Date.now()}`);
    await page.getByTestId('generate-save').click();
    await expect(page).toHaveURL(/\/my-walks\/\d+$/);
    await expect(page.getByText('자동 생성')).toBeVisible();
    await page.getByTestId('course-candidate').getByRole('button', { name: '추천 후보에 넣기' }).click();
    await expect(page.getByText('이 산책길을 추천 후보에 넣었어요')).toBeVisible();
    // e2e는 DB 하나를 같이 쓴다. 코스를 켜 둔 채 끝내면 뒤 테스트의 코스 수가 달라진다.
    await page.getByTestId('course-candidate').getByRole('button', { name: '추천 후보에서 빼기' }).click();
    await expect(page.getByText('이 산책길을 추천 후보에 넣었어요')).toHaveCount(0);
  });

  test('기준에 맞는 경로가 없으면 안내만 보이고 저장 화면은 나오지 않는다', async ({ page }) => {
    await mockGenerate(page, () => ({ status: 200, json: { target_min: 20, candidates: [], notice: '이 위치와 시간에는 기준에 맞는 순환 경로를 찾지 못했어요. 시간을 늘리거나 출발 위치를 바꿔 보세요.' } }));
    await page.goto('/generate');
    await page.getByRole('button', { name: '현재 위치 사용' }).click();
    await page.getByTestId('generate-button').click();
    await expect(page.getByText('기준에 맞는 순환 경로를 찾지 못했어요')).toBeVisible();
    await expect(page.getByTestId('generate-save')).toHaveCount(0);
  });

  test('너무 자주 요청하면 서버 안내 문구를 그대로 보여 주고 다시 시도할 수 있다', async ({ page }) => {
    let calls = 0;
    await mockGenerate(page, () => {
      calls += 1;
      return calls === 1
        ? { status: 429, json: { detail: '방금 경로를 만들었어요. 잠시 뒤에 다시 시도해 주세요.' } }
        : { status: 200, json: { target_min: 30, notice: null, candidates: [candidate(0, 30, 4)] } };
    });
    await page.goto('/generate');
    await page.getByRole('button', { name: '현재 위치 사용' }).click();
    await page.getByTestId('generate-button').click();
    await expect(page.getByText('방금 경로를 만들었어요')).toBeVisible();
    await page.getByTestId('generate-button').click();
    await expect(page.getByTestId('generate-candidate')).toHaveCount(1);
  });

  test('요청 중에는 버튼이 막혀 같은 요청이 두 번 나가지 않는다', async ({ page }) => {
    let calls = 0;
    await page.route('**/api/routes/generate', async (route) => {
      calls += 1;
      await new Promise((resolve) => setTimeout(resolve, 600));
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ target_min: 30, notice: null, candidates: [candidate(0, 30, 4)] }) });
    });
    await page.goto('/generate');
    await page.getByRole('button', { name: '현재 위치 사용' }).click();
    await page.getByTestId('generate-button').dblclick();
    await expect(page.getByTestId('generate-button')).toBeDisabled();
    await expect(page.getByRole('status')).toContainText('경로를 만들어 비교');
    await expect(page.getByTestId('generate-candidate')).toHaveCount(1);
    expect(calls).toBe(1);
  });

  test('지도를 눌러 출발점을 고르면 위치 권한 없이도 만들 수 있다', async ({ page }) => {
    const seen = await mockGenerate(page, () => ({ status: 200, json: { target_min: 30, notice: null, candidates: [candidate(0, 30, 4)] } }));
    await page.goto('/generate');
    await page.getByTestId('walk-route-map').click({ position: { x: 120, y: 100 } });
    await expect(page.getByText('지도에서 고른 위치예요.')).toBeVisible();
    await page.getByTestId('generate-button').click();
    await expect(page.getByTestId('generate-candidate')).toHaveCount(1);
    expect(seen).toHaveLength(1);
  });

  test('경로를 기다리는 사이 출발점을 바꾸면 늦게 온 이전 경로는 보이지 않는다', async ({ page }) => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => (release = resolve));
    await page.route('**/api/routes/generate', async (route) => {
      await gate;
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ target_min: 30, notice: null, candidates: [candidate(0, 30, 4)] }) });
    });
    await page.goto('/generate');
    await page.getByRole('button', { name: '현재 위치 사용' }).click();
    await page.getByTestId('generate-button').click();
    await expect(page.getByRole('status')).toBeVisible();
    await page.getByTestId('walk-route-map').click({ position: { x: 60, y: 60 } });
    await expect(page.getByText('지도에서 고른 위치예요.')).toBeVisible();
    release();
    await page.waitForTimeout(500);
    await expect(page.getByTestId('generate-candidate')).toHaveCount(0);
    await expect(page.getByTestId('generate-button')).toBeEnabled();
  });

  test('후보를 바꿔 저장하면 고른 후보의 경로가 저장된다', async ({ page }) => {
    await mockGenerate(page, () => ({ status: 200, json: { target_min: 30, notice: null, candidates: [candidate(0, 30, 4), candidate(0.0004, 26, 12)] } }));
    let saved: { points: { longitude: number }[] } | null = null;
    await page.route('**/api/my-walks', async (route) => {
      if (route.request().method() === 'POST') saved = route.request().postDataJSON();
      await route.continue();
    });
    await page.goto('/generate');
    await page.getByRole('button', { name: '현재 위치 사용' }).click();
    await page.getByTestId('generate-button').click();
    await page.getByTestId('generate-candidate').nth(1).click();
    await page.getByTestId('generate-save').click();
    await expect(page).toHaveURL(/\/my-walks\/\d+$/);
    expect(saved).not.toBeNull();
    // 두 후보는 두 번째 꼭짓점(20번째 지점)의 경도만 다르다. 두 번째 후보의 값이 저장돼야 한다.
    expect(saved!.points[20].longitude).toBeCloseTo(VENUE.longitude + 0.0004, 6);
  });
});
