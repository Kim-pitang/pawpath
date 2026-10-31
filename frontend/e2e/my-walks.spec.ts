import { expect, test, type APIRequestContext, type BrowserContext, type Page } from '@playwright/test';

const VENUE = { latitude: 37.4882, longitude: 127.0647 };
const SAMPLE_GPX = `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="SampleApp" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><name>가져온 강변길</name>
    <trkseg>
      <trkpt lat="37.4900" lon="127.0668"><ele>15</ele><time>2026-10-30T01:00:00Z</time></trkpt>
      <trkpt lat="37.4910" lon="127.0680"><ele>16</ele><time>2026-10-30T01:02:00Z</time></trkpt>
    </trkseg>
    <trkseg>
      <trkpt lat="37.4920" lon="127.0690"><time>2026-10-30T01:10:00Z</time></trkpt>
      <trkpt lat="37.4930" lon="127.0700"><time>2026-10-30T01:12:00Z</time></trkpt>
    </trkseg>
  </trk>
</gpx>`;

async function moveTo(context: BrowserContext, latitude: number, longitude = VENUE.longitude, accuracy = 8) {
  await context.setGeolocation({ latitude, longitude, accuracy });
}

/** 한 걸음을 25m 이내로 옮겨 순간 이동 필터에 걸리지 않게 걷는다. */
async function walk(page: Page, context: BrowserContext, fromLat: number, steps: number): Promise<number> {
  let latitude = fromLat;
  for (let index = 0; index < steps; index += 1) {
    latitude += 0.0002;
    await moveTo(context, latitude);
    await page.waitForTimeout(150);
  }
  return latitude;
}

async function startRecording(page: Page) {
  await page.goto('/record');
  await page.getByRole('button', { name: '산책 시작' }).click();
  await expect(page.getByTestId('record-distance')).toBeVisible();
}

async function saveWalk(request: APIRequestContext, overrides: Record<string, unknown> = {}) {
  const points = Array.from({ length: 6 }, (_, index) => ({
    latitude: 37.5 + index * 0.0003,
    longitude: 127.05,
    recorded_at: `2026-10-29T09:00:${String(index * 5).padStart(2, '0')}`,
    accuracy: 6,
    segment: 0,
  }));
  const response = await request.post('/api/my-walks', { data: { title: 'API로 만든 길', memo: '비밀 메모', points, ...overrides } });
  expect(response.ok()).toBeTruthy();
  return response.json();
}

test.describe('산책 기록', () => {
  test.use({ permissions: ['geolocation'], geolocation: { ...VENUE, accuracy: 8 } });

  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      if (!sessionStorage.getItem('keep-draft')) localStorage.removeItem('pawpath.recording.v1');
      sessionStorage.setItem('keep-draft', '1');
    });
  });

  test('시작, 이동, 일시정지, 재개, 종료, 저장까지 이어지고 상세 화면에 경로가 나온다', async ({ page, context }) => {
    await page.goto('/walk');
    await page.getByRole('link', { name: 'GPS로 산책 기록' }).click();
    await expect(page).toHaveURL(/\/record$/);
    await expect(page.getByText(/화면을 끄거나 다른 앱으로 이동하면/)).toBeVisible();
    await page.getByRole('button', { name: '산책 시작' }).click();

    let latitude = await walk(page, context, VENUE.latitude, 6);
    await expect(page.locator('path.walk-line')).toHaveCount(1);
    await expect(page.locator('.pp-me')).toBeVisible();
    await expect(page.getByText('출발', { exact: true })).toBeVisible();
    const walkedText = await page.getByTestId('record-distance').textContent();
    expect(Number(walkedText?.replace('m', ''))).toBeGreaterThan(100);
    await expect(page.getByTestId('record-time')).not.toHaveText('00:00:00', { timeout: 3000 });

    await page.getByRole('button', { name: '일시정지' }).click();
    await expect(page.getByText('일시정지', { exact: true }).first()).toBeVisible();
    const pausedTime = await page.getByTestId('record-time').textContent();
    // 일시정지 중에는 움직여도 거리와 시간이 늘지 않는다.
    await moveTo(context, latitude + 0.002);
    await page.waitForTimeout(1300);
    await expect(page.getByTestId('record-distance')).toHaveText(walkedText!);
    await expect(page.getByTestId('record-time')).toHaveText(pausedTime!);

    await page.getByRole('button', { name: '다시 시작' }).click();
    latitude = await walk(page, context, latitude + 0.002, 3);
    await page.getByRole('button', { name: '산책 종료' }).click();

    await expect(page.getByRole('heading', { name: '산책 저장' })).toBeVisible();
    await expect(page.getByTestId('save-summary')).toBeVisible();
    await page.getByLabel('산책길 이름').fill('새롬관 앞 첫 산책');
    await page.getByLabel('산책 메모').fill('양재천 바람이 좋았어요');
    const photo = await page.evaluate(() => {
      const canvas = document.createElement('canvas');
      canvas.width = 40;
      canvas.height = 30;
      canvas.getContext('2d')!.fillRect(0, 0, 20, 15);
      return canvas.toDataURL('image/jpeg');
    });
    await page.getByLabel('사진 고르기').setInputFiles({ name: 'walk.jpg', mimeType: 'image/jpeg', buffer: Buffer.from(photo.split(',')[1], 'base64') });
    await expect(page.getByTestId('pending-photo')).toHaveCount(1);
    await page.getByRole('button', { name: '저장하기' }).click();

    await expect(page).toHaveURL(/\/my-walks\/\d+$/);
    await expect(page.getByTestId('walk-title')).toHaveText('새롬관 앞 첫 산책');
    await expect(page.getByText('양재천 바람이 좋았어요')).toBeVisible();
    await expect(page.getByTestId('walk-photo')).toHaveCount(1);
    await expect(page.getByText('비공개', { exact: true })).toBeVisible();
    await expect(page.getByText('직접 기록')).toBeVisible();
    await expect(page.getByText('출발', { exact: true })).toBeVisible();
    await expect(page.getByText('도착', { exact: true })).toBeVisible();

    await page.goto('/my-walks');
    const card = page.getByTestId('saved-walk-card').filter({ hasText: '새롬관 앞 첫 산책' });
    await expect(card).toBeVisible();
    await expect(card.getByTestId('route-thumbnail')).toBeVisible();
    // 저장에 성공하면 임시 기록이 남지 않는다.
    await page.goto('/record');
    await expect(page.getByRole('button', { name: '산책 시작' })).toBeVisible();
  });

  test('위치 권한을 거부하면 이유를 알리고 시작할 수 없다', async ({ page }) => {
    await page.addInitScript(() => {
      navigator.geolocation.watchPosition = (_success, error) => {
        setTimeout(() => error?.({ code: 1, PERMISSION_DENIED: 1, POSITION_UNAVAILABLE: 2, TIMEOUT: 3, message: 'denied' } as GeolocationPositionError), 50);
        return 1;
      };
    });
    await page.goto('/record');
    await expect(page.getByRole('alert')).toContainText('위치 권한');
    await expect(page.getByRole('button', { name: '산책 시작' })).toBeDisabled();
  });

  test('브라우저가 위치 시각을 다른 단위로 줘도 거리를 쌓고 오늘 날짜로 저장한다', async ({ page }) => {
    // WebKit은 position.timestamp를 밀리초가 아니라 마이크로초로 준다.
    await page.addInitScript(() => {
      let timer = 0;
      navigator.geolocation.watchPosition = (success) => {
        let step = 0;
        const emit = () =>
          success({
            coords: { latitude: 37.4882 + step * 0.0002, longitude: 127.0647, accuracy: 8, altitude: null, altitudeAccuracy: null, heading: null, speed: null },
            timestamp: Date.now() * 1000,
          } as unknown as GeolocationPosition);
        emit();
        timer = window.setInterval(() => {
          step += 1;
          emit();
        }, 300);
        return 1;
      };
      navigator.geolocation.clearWatch = () => window.clearInterval(timer);
    });
    await startRecording(page);
    await expect.poll(async () => Number((await page.getByTestId('record-distance').textContent())?.replace('m', '')), { timeout: 8000 }).toBeGreaterThan(60);
    await page.getByRole('button', { name: '산책 종료' }).click();
    await page.getByRole('button', { name: '저장하기' }).click();
    await expect(page).toHaveURL(/\/my-walks\/\d+$/);
    await expect(page.getByText(/^오늘 (오전|오후)/)).toBeVisible();
  });

  test('신호가 약한 좌표는 거리에 넣지 않고 화면에 알린다', async ({ page, context }) => {
    await startRecording(page);
    await walk(page, context, VENUE.latitude, 2);
    const before = await page.getByTestId('record-distance').textContent();
    await moveTo(context, VENUE.latitude + 0.0006, VENUE.longitude, 300);
    await expect(page.getByText('신호 약함')).toBeVisible();
    await page.waitForTimeout(400);
    await expect(page.getByTestId('record-distance')).toHaveText(before!);
  });

  test('순간 이동한 좌표는 거리에 넣지 않는다', async ({ page, context }) => {
    await startRecording(page);
    await walk(page, context, VENUE.latitude, 2);
    const before = await page.getByTestId('record-distance').textContent();
    await moveTo(context, 35.1);
    await page.waitForTimeout(400);
    await expect(page.getByTestId('record-distance')).toHaveText(before!);
  });

  test('산책 도중 새로고침해도 기록을 불러와 이어 갈 수 있다', async ({ page, context }) => {
    await startRecording(page);
    const latitude = await walk(page, context, VENUE.latitude, 4);
    const before = await page.getByTestId('record-distance').textContent();
    await page.reload();
    await expect(page.getByText('저장하지 않은 기록을 불러왔어요')).toBeVisible();
    await expect(page.getByTestId('record-distance')).toHaveText(before!);
    await expect(page.getByRole('button', { name: '다시 시작' })).toBeVisible();
    await page.getByRole('button', { name: '다시 시작' }).click();
    await walk(page, context, latitude, 2);
    await page.getByRole('button', { name: '산책 종료' }).click();
    await expect(page.getByRole('heading', { name: '산책 저장' })).toBeVisible();
    // 저장 화면에서 새로고침해도 사라지지 않는다.
    await page.reload();
    await expect(page.getByRole('heading', { name: '산책 저장' })).toBeVisible();
    await page.getByRole('button', { name: '기록 버리기' }).click({ noWaitAfter: true }).catch(() => undefined);
  });

  test('저장 중 네트워크가 끊기면 기록을 지키고 다시 저장해도 한 번만 저장된다', async ({ page, context, request }) => {
    await startRecording(page);
    await walk(page, context, VENUE.latitude, 3);
    await page.getByRole('button', { name: '산책 종료' }).click();
    const title = `네트워크 시험 ${Date.now()}`;
    await page.getByLabel('산책길 이름').fill(title);

    await page.route('**/api/my-walks', (route) => route.abort());
    await page.getByRole('button', { name: '저장하기' }).click();
    await expect(page.getByRole('alert')).toContainText('다시 저장할 수 있어요');
    await page.reload();
    await expect(page.getByRole('heading', { name: '산책 저장' })).toBeVisible();

    await page.unroute('**/api/my-walks');
    await page.getByLabel('산책길 이름').fill(title);
    // 응답만 잃어버린 경우를 흉내 낸다. 서버에는 저장되었지만 화면은 실패로 안다.
    await page.route('**/api/my-walks', async (route) => {
      await route.fetch();
      await route.abort();
    });
    await page.getByRole('button', { name: '저장하기' }).click();
    await expect(page.getByRole('alert')).toContainText('다시 저장할 수 있어요');
    await page.unroute('**/api/my-walks');
    await page.getByRole('button', { name: '저장하기' }).click();
    await expect(page).toHaveURL(/\/my-walks\/\d+$/);

    const walks = await (await request.get('/api/my-walks')).json();
    expect(walks.filter((item: { title: string }) => item.title === title)).toHaveLength(1);
  });

  test('이동 없이 종료하면 저장 대신 이유를 보여 준다', async ({ page }) => {
    await startRecording(page);
    await page.getByRole('button', { name: '산책 종료' }).click();
    await expect(page.getByRole('alert')).toContainText('이동이 기록되지 않아');
    await expect(page.getByRole('button', { name: '저장하기' })).toHaveCount(0);
  });
});

test.describe('GPX 가져오기와 내보내기', () => {
  const upload = (page: Page, content: string, name = 'walk.gpx') =>
    page.getByLabel('GPX 파일').setInputFiles({ name, mimeType: 'application/gpx+xml', buffer: Buffer.from(content) });

  test('파일을 검증해 미리 보고 저장한 뒤, 내려받아 다시 가져와도 경로가 같다', async ({ page }) => {
    await page.goto('/my-walks');
    await page.getByRole('link', { name: 'GPX 가져오기' }).click();
    await upload(page, SAMPLE_GPX);

    const result = page.getByTestId('gpx-result');
    await expect(result).toContainText('1.1');
    await expect(result).toContainText('1개 / 2개');
    await expect(result).toContainText('4개');
    await expect(page.locator('path.walk-line')).toHaveCount(1);
    await expect(page.getByLabel('산책길 이름')).toHaveValue('가져온 강변길');

    await page.getByLabel('산책길 이름').fill('강변길 왕복');
    await page.getByRole('button', { name: '산책길로 저장' }).click();
    await expect(page).toHaveURL(/\/my-walks\/\d+$/);
    await expect(page.getByText('GPX 가져옴')).toBeVisible();
    const stats = await page.getByTestId('walk-stats').textContent();

    const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', { name: 'GPX 다운로드' }).click()]);
    expect(download.suggestedFilename()).toMatch(/^pawpath_.*_20261030\.gpx$/);
    const stream = await download.createReadStream();
    const chunks: Buffer[] = [];
    for await (const chunk of stream) chunks.push(chunk as Buffer);
    const exported = Buffer.concat(chunks).toString('utf8');
    expect(exported).toContain('<gpx version="1.1"');
    expect(exported).toContain('<time>2026-10-30T01:00:00Z</time>');
    expect(exported).toContain('<ele>15.0</ele>');
    expect(exported.match(/<trkseg>/g)).toHaveLength(2);

    await page.goto('/my-walks/import');
    await upload(page, exported, 'exported.gpx');
    await expect(page.getByTestId('gpx-result')).toContainText('1개 / 2개');
    await expect(page.getByTestId('gpx-result')).toContainText('4개');
    // 같은 경로이므로 중복이라고 알리고, 거리와 시간도 처음과 같다.
    await expect(page.getByTestId('gpx-duplicate')).toContainText('강변길 왕복');
    const distance = stats?.match(/거리([\d.]+k?m)/)?.[1];
    await expect(page.getByTestId('gpx-result')).toContainText(distance!);
  });

  test('시간 정보가 없는 파일은 그렇게 안내하고 저장할 수 있다', async ({ page }) => {
    await page.goto('/my-walks/import');
    await upload(page, '<gpx version="1.1"><trk><trkseg><trkpt lat="37.49" lon="127.06"/><trkpt lat="37.5" lon="127.06"/></trkseg></trk></gpx>');
    await expect(page.getByText(/시각 정보가 없어/)).toBeVisible();
    await expect(page.getByTestId('gpx-result')).toContainText('시간 정보 없음');
    await page.getByLabel('산책길 이름').fill('시간 없는 길');
    await page.getByRole('button', { name: '산책길로 저장' }).click();
    await expect(page.getByTestId('walk-stats')).toContainText('시간 정보 없음');
  });

  test('잘못된 파일은 이유를 알리고 저장 화면을 열지 않는다', async ({ page }) => {
    await page.goto('/my-walks/import');
    const alert = page.getByRole('alert');
    await upload(page, 'not gpx');
    await expect(alert).toContainText('형식');
    await upload(page, '');
    await expect(alert).toContainText('빈 파일');
    await upload(page, '<gpx version="1.1"></gpx>');
    await expect(alert).toContainText('좌표가 없어요');
    await upload(page, '<!DOCTYPE gpx [<!ENTITY x SYSTEM "file:///etc/passwd">]><gpx version="1.1"></gpx>');
    await expect(alert).toContainText('DOCTYPE');
    await upload(page, SAMPLE_GPX, 'photo.jpg');
    await expect(alert).toContainText('.gpx 파일만');
    await expect(page.getByRole('button', { name: '산책길로 저장' })).toHaveCount(0);
  });

  test('파일을 끌어다 놓아도 가져온다', async ({ page }) => {
    await page.goto('/my-walks/import');
    const transfer = await page.evaluateHandle((content) => {
      const data = new DataTransfer();
      data.items.add(new File([content], 'dropped.gpx', { type: 'application/gpx+xml' }));
      return data;
    }, SAMPLE_GPX);
    await page.getByTestId('gpx-dropzone').dispatchEvent('drop', { dataTransfer: transfer });
    await expect(page.getByTestId('gpx-result')).toContainText('4개');
  });
});

test.describe('나의 산책길과 공유', () => {
  test('목록을 정렬하고 공개 범위로 거를 수 있다', async ({ page, request }) => {
    const stamp = Date.now();
    await saveWalk(request, { title: `필터 공개 ${stamp}`, visibility: 'public' });
    await page.goto('/my-walks');
    await expect(page.getByTestId('saved-walk-card').filter({ hasText: `필터 공개 ${stamp}` })).toBeVisible();
    await page.getByLabel('공개 범위별 보기').selectOption('private');
    await expect(page.getByTestId('saved-walk-card').filter({ hasText: `필터 공개 ${stamp}` })).toHaveCount(0);
    await page.getByLabel('공개 범위별 보기').selectOption('public');
    await expect(page.getByTestId('saved-walk-card').filter({ hasText: `필터 공개 ${stamp}` })).toBeVisible();
    await page.getByRole('button', { name: '거리순' }).click();
    await expect(page.getByRole('button', { name: '거리순' })).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByTestId('saved-walk-card').filter({ hasText: `필터 공개 ${stamp}` })).toBeVisible();
  });

  test('수정하고 삭제할 수 있다', async ({ page, request }) => {
    const walk = await saveWalk(request, { title: `수정 전 ${Date.now()}` });
    await page.goto(`/my-walks/${walk.id}`);
    await page.getByRole('button', { name: '수정' }).click();
    await page.getByLabel('산책길 이름').fill('수정한 이름');
    await page.getByRole('button', { name: '저장하기' }).click();
    await expect(page.getByTestId('walk-title')).toHaveText('수정한 이름');

    page.once('dialog', (dialog) => dialog.accept());
    await page.getByRole('button', { name: '삭제' }).click();
    await expect(page).toHaveURL(/\/my-walks$/);
    expect((await request.get(`/api/my-walks/${walk.id}`)).status()).toBe(404);
  });

  test('공유 링크를 만들면 받는 사람은 개인정보 없이 보고, 해제하면 열리지 않는다', async ({ page, browser, request }) => {
    const pets = await (await request.get('/api/pets')).json();
    const walk = await saveWalk(request, { title: `공유 시험 ${Date.now()}`, pet_id: pets[0].id });
    await page.goto(`/my-walks/${walk.id}`);
    await expect(page.getByText(/집 주소 같은 민감한 위치/)).toBeVisible();
    await page.getByRole('button', { name: '공유 링크 만들기' }).click();
    const link = await page.getByLabel('공유 링크').inputValue();
    expect(link).toMatch(/\/shared\/[\w-]{32,}$/);
    await expect(page.getByText('링크 공유', { exact: true })).toBeVisible();

    const viewerContext = await browser.newContext();
    const viewer = await viewerContext.newPage();
    await viewer.goto(link);
    await expect(viewer.getByTestId('shared-title')).toHaveText(walk.title);
    await expect(viewer.locator('path.walk-line')).toHaveCount(1);
    await expect(viewer.getByText('출발', { exact: true })).toBeVisible();
    await expect(viewer.getByText('도착', { exact: true })).toBeVisible();
    await expect(viewer.getByTestId('shared-stats')).toContainText('총 거리');
    // 메모와 반려동물은 허용하지 않으면 보이지 않는다.
    await expect(viewer.getByText('비밀 메모')).toHaveCount(0);
    await expect(viewer.getByText(pets[0].name)).toHaveCount(0);
    await expect(viewer.getByRole('navigation', { name: '주요 메뉴' })).toHaveCount(0);

    await page.getByRole('button', { name: '공유 링크 해제' }).click();
    await expect(page.getByRole('button', { name: '공유 링크 만들기' })).toBeVisible();
    await viewer.reload();
    await expect(viewer.getByText(/공유가 해제되었거나/)).toBeVisible();
    await expect(viewer.getByTestId('shared-title')).toHaveCount(0);
    await viewerContext.close();
  });

  test('비공개 산책길은 없는 링크와 똑같이 열리지 않는다', async ({ page }) => {
    await page.goto('/shared/not-a-real-token');
    await expect(page.getByText(/공유가 해제되었거나/)).toBeVisible();
  });

  test('메모 공개를 허용하면 공유 화면에 메모가 나온다', async ({ page, request }) => {
    const walk = await saveWalk(request, { title: `메모 공유 ${Date.now()}`, memo: '그늘이 좋아요' });
    await page.goto(`/my-walks/${walk.id}`);
    await page.getByLabel('공유 화면에 메모도 보여 주기').check();
    await page.getByRole('button', { name: '7일' }).click();
    await page.getByRole('button', { name: '공유 링크 만들기' }).click();
    await expect(page.getByText(/까지 열려요/)).toBeVisible();
    await page.goto(await page.getByLabel('공유 링크').inputValue());
    await expect(page.getByTestId('shared-memo')).toHaveText('그늘이 좋아요');
  });

  test('공개 산책길은 목록에서 볼 수 있고 시각과 메모는 나오지 않는다', async ({ page, request }) => {
    const title = `공개 목록 ${Date.now()}`;
    await saveWalk(request, { title, visibility: 'public' });
    await page.goto('/my-walks');
    await page.getByRole('link', { name: '공개된 산책길 둘러보기' }).click();
    await page.getByRole('link', { name: new RegExp(title) }).click();
    await expect(page.getByTestId('shared-title')).toHaveText(title);
    await expect(page.getByText('비밀 메모')).toHaveCount(0);
  });

  test('마이페이지에서 나의 산책길로 갈 수 있다', async ({ page, request }) => {
    const pets = await (await request.get('/api/pets')).json();
    expect(pets.length).toBeGreaterThan(0);
    await page.goto('/my');
    await page.getByRole('link', { name: '나의 산책길' }).click();
    await expect(page).toHaveURL(/\/my-walks$/);
  });
});
