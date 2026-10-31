import { expect, test, type APIRequestContext, type BrowserContext, type Page } from '@playwright/test';

const PASSWORD = 'walk-with-dubu-1';
const POINTS = Array.from({ length: 4 }, (_, index) => ({ latitude: 37.5 + index * 0.0003, longitude: 127.0, segment: 0 }));
const PET = {
  name: '콩',
  breed: '시바견',
  age_years: 3,
  weight_kg: 9,
  size: 'medium',
  activity_level: 'high',
  personality: 'active',
  path_preference: 'new',
  heat_sensitivity: 'medium',
  novelty_reaction: 'calm',
};
const GPX = `<?xml version="1.0" encoding="UTF-8"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><name>사진 길</name><trkseg>
<trkpt lat="37.49" lon="127.06"><time>2026-10-30T01:00:00Z</time></trkpt><trkpt lat="37.491" lon="127.061"><time>2026-10-30T01:02:00Z</time></trkpt></trkseg></trk></gpx>`;

const newId = () => `user${Date.now()}${Math.floor(Math.random() * 1000)}`;

async function signUpInBrowser(page: Page, loginId: string, name = '새 보호자') {
  await page.goto('/login');
  // 계정 정보를 읽으면 Google 버튼이 생겨 화면이 밀리므로, 그 뒤에 눌러야 빗나가지 않는다.
  await page.getByRole('link', { name: '로그인하지 않고 시연 보호자로 둘러보기' }).waitFor();
  await page.getByRole('button', { name: '회원가입' }).click();
  await page.getByLabel('아이디').fill(loginId);
  await page.getByLabel('비밀번호').fill(PASSWORD);
  await page.getByLabel('이름', { exact: true }).fill(name);
  await page.getByRole('button', { name: '가입하고 시작하기' }).click();
  // 가입하면 대표 프로필의 이름과 아바타를 정한다. 계정 이름이 미리 채워져 있다.
  await expect(page.getByRole('heading', { name: '내 프로필을 정해 주세요' })).toBeVisible();
  await expect(page.getByLabel('프로필 이름')).toHaveValue(name);
  await page.getByRole('button', { name: '시작하기', exact: true }).click();
}

/** 브라우저 캔버스로 만든 진짜 JPEG. */
async function makeJpeg(page: Page): Promise<Buffer> {
  const dataUrl = await page.evaluate(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 64;
    canvas.height = 48;
    const context = canvas.getContext('2d')!;
    context.fillStyle = '#2e8b62';
    context.fillRect(0, 0, 64, 48);
    context.fillStyle = '#d9661a';
    context.fillRect(10, 10, 20, 20);
    return canvas.toDataURL('image/jpeg', 0.9);
  });
  return Buffer.from(dataUrl.split(',')[1], 'base64');
}

/** 휴대폰 사진처럼 EXIF 위치 정보와 끝에 붙은 보조 이미지를 넣는다. */
function withLocation(jpeg: Buffer): Buffer {
  const payload = Buffer.from('Exif\0\0MM\0*GPSLatitude=37.4882;GPSLongitude=127.0647', 'latin1');
  const length = Buffer.alloc(2);
  length.writeUInt16BE(payload.length + 2);
  const trailer = Buffer.from('\xff\xd8GPS-TRAILER-THUMBNAIL\xff\xd9', 'latin1');
  return Buffer.concat([jpeg.subarray(0, 2), Buffer.from([0xff, 0xe1]), length, payload, jpeg.subarray(2), trailer]);
}

async function guestWalk(request: APIRequestContext, title = '시연 보호자의 길') {
  const response = await request.post('/api/my-walks', { data: { title, points: POINTS } });
  expect(response.ok()).toBeTruthy();
  return response.json();
}

test.describe('계정', () => {
  test('가입하면 빈 계정으로 시작하고, 시연 보호자의 데이터와 섞이지 않는다', async ({ page, request }) => {
    const demo = await guestWalk(request);
    await page.goto('/');
    await page.locator('header').getByRole('link', { name: '로그인' }).click();
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole('link', { name: '로그인하지 않고 시연 보호자로 둘러보기' })).toBeVisible();
    await signUpInBrowser(page, newId());

    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByText('아직 등록된 반려동물이 없어요')).toBeVisible();
    await expect(page.locator('header').getByRole('link', { name: '로그인' })).toHaveCount(0);
    expect(await (await page.request.get('/api/pets')).json()).toEqual([]);
    expect((await page.request.get(`/api/my-walks/${demo.id}`)).status()).toBe(404);

    await page.goto('/my-walks');
    await expect(page.getByText('시연 보호자 계정에 저장돼요')).toHaveCount(0);
    await expect(page.getByTestId('saved-walk-card')).toHaveCount(0);

    await page.goto('/my');
    await expect(page.getByTestId('account-name')).toContainText('새 보호자');
    await page.getByRole('button', { name: '로그아웃' }).click();
    await expect(page).toHaveURL(/\/$/);
    // 로그아웃하면 다시 시연 보호자로 돌아간다.
    await expect(page.locator('header').getByRole('link', { name: '두부' })).toBeVisible();
    await expect(page.locator('header').getByRole('link', { name: '로그인' })).toBeVisible();
  });

  test('비밀번호가 틀리면 알리고, 맞으면 원래 가려던 화면으로 간다', async ({ page }) => {
    const loginId = newId();
    expect((await page.request.post('/api/auth/signup', { data: { login_id: loginId, password: PASSWORD, name: '재방문' } })).status()).toBe(201);
    await page.request.post('/api/auth/logout');

    await page.goto('/my-walks');
    await page.locator('header').getByRole('link', { name: '로그인' }).click();
    await page.getByLabel('아이디').fill(loginId.toUpperCase());
    await page.getByLabel('비밀번호').fill('wrong-password');
    await page.getByRole('button', { name: '로그인하기' }).click();
    await expect(page.getByRole('alert')).toContainText('아이디나 비밀번호가 맞지 않아요');

    await page.getByLabel('비밀번호').fill(PASSWORD);
    await page.getByRole('button', { name: '로그인하기' }).click();
    await expect(page).toHaveURL(/\/my-walks$/);
    await expect(page.getByRole('heading', { name: '나의 산책길' })).toBeVisible();
  });

  test('가입 입력이 규칙에 맞지 않으면 보내기 전에 알린다', async ({ page }) => {
    await page.goto('/login');
    await page.getByRole('button', { name: '회원가입' }).click();
    await page.getByLabel('아이디').fill('한글아이디');
    await page.getByLabel('비밀번호').fill(PASSWORD);
    await page.getByLabel('이름').fill('규칙');
    await page.getByRole('button', { name: '가입하고 시작하기' }).click();
    await expect(page.getByRole('alert')).toContainText('영문 소문자');
    await page.getByLabel('아이디').fill(newId());
    await page.getByLabel('비밀번호').fill('short');
    await page.getByRole('button', { name: '가입하고 시작하기' }).click();
    await expect(page.getByRole('alert')).toContainText('8자 이상');
  });

  test('로그인이 필수인 서버면 로그인 화면으로 보낸다', async ({ page }) => {
    await page.route('**/api/auth/me', (route) => route.fulfill({ json: { authenticated: false, auth_required: true, user: null } }));
    await page.goto('/recommend');
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByText('이 서버는 로그인해야 쓸 수 있어요')).toBeVisible();
    await expect(page.getByRole('link', { name: '로그인하지 않고 시연 보호자로 둘러보기' })).toHaveCount(0);
  });
});

/** 서버에서 세션을 끝내 만료된 상황을 만든다. 브라우저에는 이제 쓸 수 없는 쿠키가 남아 있다. */
async function endSession(context: BrowserContext, request: APIRequestContext) {
  const token = (await context.cookies()).find((cookie) => cookie.name === 'pawpath_session')!.value;
  await request.post('/api/auth/logout', { headers: { Cookie: `pawpath_session=${token}` } });
}

async function signUpWithPet(page: Page, loginId: string) {
  await signUpInBrowser(page, loginId);
  await expect(page).toHaveURL(/\/$/);
  expect((await page.request.post('/api/pets', { data: PET })).status()).toBe(201);
  await page.reload();
  await expect(page.locator('header').getByRole('link', { name: '콩' })).toBeVisible();
}

const expiredDialog = (page: Page) => page.getByRole('dialog', { name: '로그인이 만료되었어요' });
const reLogin = async (page: Page, password = PASSWORD) => {
  await expiredDialog(page).getByLabel('비밀번호').fill(password);
  await expiredDialog(page).getByRole('button', { name: '다시 로그인' }).click();
};
const remembered = (page: Page) => page.evaluate(() => localStorage.getItem('pawpath.account'));

test.describe('세션 만료와 다시 로그인', () => {
  test('만료되면 보던 화면 위에서 다시 로그인하고, 멈춘 요청이 이어서 끝난다', async ({ page, context, request }) => {
    const loginId = newId();
    await signUpWithPet(page, loginId);
    await endSession(context, request);

    await page.getByRole('navigation', { name: '주요 메뉴' }).getByRole('link', { name: '마이' }).click();
    await expect(expiredDialog(page)).toBeVisible();
    await expect(page.getByTestId('expired-login-id')).toHaveText(loginId);
    // 시연 보호자의 데이터로 넘어가지 않는다.
    await expect(page.locator('header').getByRole('link', { name: '두부' })).toHaveCount(0);

    await reLogin(page, 'wrong-password');
    await expect(expiredDialog(page).getByRole('alert')).toContainText('아이디나 비밀번호가 맞지 않아요');
    await expect(expiredDialog(page)).toBeVisible();

    await reLogin(page);
    await expect(expiredDialog(page)).toHaveCount(0);
    await expect(page).toHaveURL(/\/my$/);
    // 만료로 멈췄던 요청이 다시 가서 화면이 오류 없이 채워진다.
    await expect(page.getByRole('heading', { name: '콩의 산책 리포트' })).toBeVisible();
    await expect(page.getByRole('alert')).toHaveCount(0);
  });

  test('쓰던 내용이 남아 있고, 다시 로그인하면 저장한 값이 내 계정에 들어간다', async ({ page, context, request }) => {
    await signUpWithPet(page, newId());
    await page.goto('/my-walks/import');
    await page.getByLabel('GPX 파일').setInputFiles({ name: 'walk.gpx', mimeType: 'application/gpx+xml', buffer: Buffer.from(GPX) });
    await expect(page.getByTestId('gpx-result')).toBeVisible();
    const title = `만료 뒤 저장 ${Date.now()}`;
    await page.getByLabel('산책길 이름').fill(title);

    await endSession(context, request);
    await page.getByRole('button', { name: '산책길로 저장' }).click();
    await expect(expiredDialog(page)).toBeVisible();
    await reLogin(page);

    await expect(page).toHaveURL(/\/my-walks\/\d+$/);
    await expect(page.getByRole('heading', { name: title })).toBeVisible();
    const mine: { title: string }[] = await (await page.request.get('/api/my-walks')).json();
    expect(mine.map((walk) => walk.title)).toContain(title);
    // 누구나 보는 시연 보호자 계정에 들어가지 않았다.
    const demo: { title: string }[] = await (await request.get('/api/my-walks', { headers: { Cookie: '' } })).json();
    expect(demo.map((walk) => walk.title)).not.toContain(title);
  });

  test.describe('산책 기록', () => {
    const START = { latitude: 37.4882, longitude: 127.0647, accuracy: 8 };
    test.use({ permissions: ['geolocation'], geolocation: START });

    test('저장 직전에 만료되어도 기록이 남고, 다시 로그인하면 내 계정에 한 번만 저장된다', async ({ page, context, request }) => {
      await signUpWithPet(page, newId());
      await page.goto('/record');
      await page.getByRole('button', { name: '산책 시작' }).click();
      await expect(page.getByTestId('record-distance')).toBeVisible();
      for (let step = 1; step <= 8; step += 1) {
        await context.setGeolocation({ ...START, latitude: START.latitude + step * 0.0002 });
        await page.waitForTimeout(150);
      }
      await page.getByRole('button', { name: '산책 종료' }).click();
      const title = `기록 만료 ${Date.now()}`;
      await page.getByLabel('산책길 이름').fill(title);

      await endSession(context, request);
      await page.getByRole('button', { name: '저장하기' }).click();
      await expect(expiredDialog(page)).toBeVisible();
      // 로그인을 기다리는 동안 기록은 기기에 남아 있다.
      expect(await page.evaluate(() => localStorage.getItem('pawpath.recording.v1'))).not.toBeNull();
      await reLogin(page);

      await expect(page).toHaveURL(/\/my-walks\/\d+$/);
      await expect(page.getByRole('heading', { name: title })).toBeVisible();
      expect(await page.evaluate(() => localStorage.getItem('pawpath.recording.v1'))).toBeNull();
      const mine: { title: string }[] = await (await page.request.get('/api/my-walks')).json();
      expect(mine.filter((walk) => walk.title === title)).toHaveLength(1);
      const demo: { title: string }[] = await (await request.get('/api/my-walks')).json();
      expect(demo.map((walk) => walk.title)).not.toContain(title);
    });
  });

  test('오래 있다 돌아와 쿠키가 없어도 만료를 알리고, 시연 보호자로 둘러볼 수 있다', async ({ page, context }) => {
    const loginId = newId();
    await signUpWithPet(page, loginId);
    await context.clearCookies();
    await page.reload();
    await expect(expiredDialog(page)).toBeVisible();
    await expect(page.getByTestId('expired-login-id')).toHaveText(loginId);

    await expiredDialog(page).getByRole('button', { name: '시연 보호자로 둘러보기' }).click();
    await expect(expiredDialog(page)).toHaveCount(0);
    await expect(page).toHaveURL(/\/$/);
    await expect(page.locator('header').getByRole('link', { name: '두부' })).toBeVisible();
    // 고른 뒤에는 다시 묻지 않는다.
    await page.reload();
    await expect(page.locator('header').getByRole('link', { name: '두부' })).toBeVisible();
    await expect(expiredDialog(page)).toHaveCount(0);
  });

  test('탭으로 돌아오면 누르기 전에 만료를 알린다', async ({ page, context }) => {
    await signUpWithPet(page, newId());
    await context.clearCookies();
    await expect(expiredDialog(page)).toHaveCount(0);
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
    await expect(expiredDialog(page)).toBeVisible();
  });

  test('다른 계정으로 로그인하면 앞사람의 저장하지 않은 기록을 지운다', async ({ page, context }) => {
    await signUpWithPet(page, newId());
    await page.evaluate(() => localStorage.setItem('pawpath.recording.v1', JSON.stringify({ id: 'left-behind', points: [], status: 'paused' })));
    await context.clearCookies();
    await page.reload();

    page.once('dialog', (dialog) => dialog.accept());
    await expiredDialog(page).getByRole('button', { name: '다른 계정으로 로그인' }).click();
    await expect(page).toHaveURL(/\/login$/);
    expect(await page.evaluate(() => localStorage.getItem('pawpath.recording.v1'))).toBeNull();
    expect(await remembered(page)).toBeNull();
  });

  test('취소하면 기록을 지우지 않고 그대로 기다린다', async ({ page, context }) => {
    await signUpWithPet(page, newId());
    await page.evaluate(() => localStorage.setItem('pawpath.recording.v1', JSON.stringify({ id: 'kept', points: [], status: 'paused' })));
    await context.clearCookies();
    await page.reload();
    page.once('dialog', (dialog) => dialog.dismiss());
    await expiredDialog(page).getByRole('button', { name: '시연 보호자로 둘러보기' }).click();
    await expect(expiredDialog(page)).toBeVisible();
    expect(await page.evaluate(() => localStorage.getItem('pawpath.recording.v1'))).toContain('kept');
  });

  test('직접 로그아웃하면 만료로 보지 않는다', async ({ page }) => {
    await signUpWithPet(page, newId());
    await page.goto('/my');
    await page.getByRole('button', { name: '로그아웃' }).click();
    await expect(page.locator('header').getByRole('link', { name: '로그인' })).toBeVisible();
    await page.reload();
    await expect(page.locator('header').getByRole('link', { name: '두부' })).toBeVisible();
    await expect(expiredDialog(page)).toHaveCount(0);
  });

  test('공유 링크를 볼 때는 다시 로그인을 요구하지 않는다', async ({ page, context, request }) => {
    const walk = await guestWalk(request, `공유 길 ${Date.now()}`);
    const token = (await (await request.post(`/api/my-walks/${walk.id}/share`, { data: {} })).json()).share_token;
    await signUpWithPet(page, newId());
    await context.clearCookies();
    await page.goto(`/shared/${token}`);
    await expect(page.getByTestId('shared-title')).toBeVisible();
    await expect(expiredDialog(page)).toHaveCount(0);
  });

  test('로그인이 필수인 서버에서는 시연 보호자로 넘어가는 길을 주지 않는다', async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('pawpath.account', JSON.stringify({ id: 99, login_id: 'someone', provider: 'password' })));
    await page.route('**/api/auth/me', (route) => route.fulfill({ json: { authenticated: false, auth_required: true, google_enabled: false, user: null } }));
    await page.goto('/my');
    await expect(expiredDialog(page)).toBeVisible();
    await expect(expiredDialog(page).getByRole('button', { name: '시연 보호자로 둘러보기' })).toHaveCount(0);
    await expiredDialog(page).getByRole('button', { name: '다른 계정으로 로그인' }).click();
    await expect(page).toHaveURL(/\/login$/);
  });

  test('Google 계정은 Google로 다시 로그인하고, 실패 이유를 대화상자에 알린다', async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('pawpath.account', JSON.stringify({ id: 99, login_id: null, provider: 'google' })));
    await page.route('**/api/auth/me', (route) => route.fulfill({ json: { authenticated: false, auth_required: false, google_enabled: true, user: null } }));
    await page.goto('/my-walks?sort=recent');
    await expect(expiredDialog(page).getByRole('link', { name: 'Google로 다시 로그인' })).toHaveAttribute('href', '/api/auth/google/start?next=%2Fmy-walks%3Fsort%3Drecent');
    await expect(expiredDialog(page).getByLabel('비밀번호')).toHaveCount(0);
    await page.goto('/login?error=google_cancelled');
    await expect(expiredDialog(page).getByRole('alert')).toContainText('Google 로그인을 취소했어요');
  });
});

test.describe('계정 탈퇴', () => {
  const account = async (page: Page) => (await (await page.request.get('/api/auth/me')).json()).authenticated;

  test('지울 데이터를 보여 주고, 탈퇴하면 서버와 기기, 공유 링크에서 모두 사라진다', async ({ page, browser, context }) => {
    const loginId = newId();
    await signUpWithPet(page, loginId);
    const walk = await (await page.request.post('/api/my-walks', { data: { title: '비밀 산책길', points: POINTS } })).json();
    expect((await page.request.post(`/api/my-walks/${walk.id}/photos`, { data: await makeJpeg(page), headers: { 'Content-Type': 'image/jpeg' } })).status()).toBe(201);
    const token = (await (await page.request.post(`/api/my-walks/${walk.id}/share`, { data: {} })).json()).share_token;
    await page.evaluate(() => localStorage.setItem('pawpath.recording.v1', JSON.stringify({ id: 'unsaved', points: [], status: 'paused' })));

    await page.goto('/my');
    await page.getByRole('link', { name: '계정 관리' }).click();
    await expect(page).toHaveURL(/\/account$/);
    await expect(page.getByTestId('session-policy')).toContainText('7일 동안 쓰지 않으면');
    const summary = page.getByTestId('deletion-summary');
    await expect(summary).toContainText('반려동물');
    await expect(summary).toContainText('1장');
    await expect(summary).toContainText('공유 중인 산책길');
    await expect(page.getByRole('link', { name: '산책길을 먼저 GPX로 내려받기' })).toBeVisible();

    // 방금 로그인했으므로 본인 확인을 다시 묻지 않지만, 확인 단어를 넣어야 눌린다.
    const remove = page.getByRole('button', { name: '계정과 데이터 모두 지우기' });
    await expect(remove).toBeDisabled();
    await page.getByLabel('계속하려면').fill('탈퇴 안 함');
    await expect(remove).toBeDisabled();
    await page.getByLabel('계속하려면').fill('탈퇴');
    await remove.click();

    await expect(page).toHaveURL(/\/goodbye$/);
    await expect(page.getByRole('heading', { name: '탈퇴가 끝났어요' })).toBeVisible();
    expect(await account(page)).toBe(false);
    expect((await context.cookies()).some((cookie) => cookie.name === 'pawpath_session')).toBe(false);
    expect(await remembered(page)).toBeNull();
    expect(await page.evaluate(() => localStorage.getItem('pawpath.recording.v1'))).toBeNull();

    // 만료 대화상자 없이 시연 보호자로 돌아간다.
    await page.getByRole('link', { name: '처음으로' }).click();
    await expect(page.locator('header').getByRole('link', { name: '두부' })).toBeVisible();
    await expect(expiredDialog(page)).toHaveCount(0);

    const visitor = await browser.newContext();
    expect((await visitor.request.get(`/api/shared/${token}`)).status()).toBe(404);
    expect((await visitor.request.post('/api/auth/login', { data: { login_id: loginId, password: PASSWORD } })).status()).toBe(401);
    await visitor.close();
  });

  test('이 브라우저에 남은 사진 캐시도 함께 지운다', async ({ page, browserName }) => {
    test.skip(browserName !== 'chromium', 'WebKit은 only-if-cached를 지원하지 않아 캐시를 직접 확인할 수 없다');
    await signUpInBrowser(page, newId());
    await expect(page).toHaveURL(/\/$/);
    const walk = await (await page.request.post('/api/my-walks', { data: { title: '캐시 확인', points: POINTS } })).json();
    const photo = await (await page.request.post(`/api/my-walks/${walk.id}/photos`, { data: await makeJpeg(page), headers: { 'Content-Type': 'image/jpeg' } })).json();
    const url = `/api/my-walks/${walk.id}/photos/${photo.id}`;
    const cached = () =>
      page.evaluate(
        (target) =>
          fetch(target, { cache: 'only-if-cached', mode: 'same-origin' })
            .then((response) => response.ok)
            .catch(() => false),
        url,
      );
    await page.goto(`/my-walks/${walk.id}`);
    await expect.poll(() => page.getByTestId('walk-photo').first().evaluate((image: HTMLImageElement) => image.naturalWidth)).toBe(64);
    expect(await cached()).toBe(true);

    await page.goto('/account');
    await page.getByLabel('계속하려면').fill('탈퇴');
    await page.getByRole('button', { name: '계정과 데이터 모두 지우기' }).click();
    await expect(page).toHaveURL(/\/goodbye$/);
    await expect.poll(cached).toBe(false);
  });

  test('시간이 지났으면 비밀번호를 다시 확인한 뒤에야 탈퇴할 수 있다', async ({ page }) => {
    await signUpInBrowser(page, newId());
    await expect(page).toHaveURL(/\/$/);
    // 로그인한 지 오래된 세션처럼 보이게 한다. 비밀번호 확인과 탈퇴는 실제 서버로 간다.
    await page.route('**/api/auth/account', async (route) => {
      if (route.request().method() !== 'GET') return route.fallback();
      const response = await route.fetch();
      return route.fulfill({ response, json: { ...(await response.json()), reauth_required: true } });
    });
    await page.goto('/account');
    await expect(page.getByRole('button', { name: '계정과 데이터 모두 지우기' })).toHaveCount(0);

    const password = page.getByLabel('탈퇴하려면 비밀번호를 다시 입력해 주세요');
    await password.fill('wrong-password');
    await page.getByRole('button', { name: '본인 확인' }).click();
    await expect(page.getByRole('alert')).toContainText('비밀번호가 맞지 않아요');
    expect(await account(page)).toBe(true);

    await password.fill(PASSWORD);
    await page.getByRole('button', { name: '본인 확인' }).click();
    await page.getByLabel('계속하려면').fill('탈퇴');
    await page.getByRole('button', { name: '계정과 데이터 모두 지우기' }).click();
    await expect(page).toHaveURL(/\/goodbye$/);
    expect(await account(page)).toBe(false);
  });

  test('화면을 오래 열어 두어 본인 확인이 끝났으면 다시 묻는다', async ({ page }) => {
    await signUpInBrowser(page, newId());
    await expect(page).toHaveURL(/\/$/);
    await page.route('**/api/auth/account', (route) =>
      route.request().method() === 'DELETE' ? route.fulfill({ status: 403, json: { detail: '탈퇴하려면 본인을 다시 확인해 주세요.' } }) : route.fallback(),
    );
    await page.goto('/account');
    await page.getByLabel('계속하려면').fill('탈퇴');
    await page.getByRole('button', { name: '계정과 데이터 모두 지우기' }).click();
    await expect(page.getByRole('alert')).toContainText('본인을 다시 확인');
    await expect(page.getByLabel('탈퇴하려면 비밀번호를 다시 입력해 주세요')).toBeVisible();
    expect(await account(page)).toBe(true);
  });

  test('서버가 탈퇴를 처리하지 못하면 이유를 알리고 그대로 둔다', async ({ page }) => {
    await signUpInBrowser(page, newId());
    await expect(page).toHaveURL(/\/$/);
    await page.route('**/api/auth/account', (route) =>
      route.request().method() === 'DELETE' ? route.fulfill({ status: 503, json: { detail: '탈퇴를 처리하지 못했어요. 지운 데이터는 없으니 잠시 뒤 다시 시도해 주세요.' } }) : route.fallback(),
    );
    await page.goto('/account');
    await page.getByLabel('계속하려면').fill('탈퇴');
    await page.getByRole('button', { name: '계정과 데이터 모두 지우기' }).click();
    await expect(page.getByRole('alert')).toContainText('지운 데이터는 없으니');
    await expect(page).toHaveURL(/\/account$/);
    await expect(page.getByRole('button', { name: '계정과 데이터 모두 지우기' })).toBeEnabled();
  });

  test('Google 계정은 Google로 본인을 확인하고, 다른 계정을 고르면 알린다', async ({ page }) => {
    const user = { id: 99, name: '구글 보호자', login_id: null, email: 'dubu@example.com', provider: 'google' };
    const data = { pets: 0, walks: 0, feedback: 0, recommendations: 0, saved_walks: 0, photos: 0, personal_courses: 0, shared_walks: 0, community_trails: 0, trail_reviews: 0 };
    await page.route('**/api/auth/me', (route) => route.fulfill({ json: { authenticated: true, auth_required: false, google_enabled: true, user } }));
    await page.route('**/api/auth/account', (route) =>
      route.fulfill({ json: { provider: 'google', reauth_required: true, session_expires_at: '2026-11-30T10:00:00', session_idle_days: 7, data, backup_retention_days: 14 } }),
    );
    await page.goto('/account?error=google_mismatch');
    await expect(page.getByRole('alert')).toContainText('다른 Google 계정');
    await expect(page.getByRole('link', { name: 'Google로 본인 확인' })).toHaveAttribute('href', '/api/auth/google/start?reauth=true');
    await expect(page.getByText('Google 계정은 그대로예요')).toBeVisible();
    await expect(page.getByText('14일 안에 사라지고')).toBeVisible();
    await expect(page.getByText('지금은 계정 정보 말고 지울 데이터가 없어요')).toBeVisible();
  });

  test('로그인하지 않으면 계정 화면 대신 로그인으로 보낸다', async ({ page }) => {
    await page.goto('/account');
    await expect(page).toHaveURL(/\/login$/);
  });
});

test.describe('산책길 사진', () => {
  test('사진을 붙이면 위치 정보를 지워 저장하고, 공유 화면에는 보이지 않는다', async ({ page, browser, request }) => {
    const walk = await guestWalk(request, `사진 시험 ${Date.now()}`);
    await page.goto(`/my-walks/${walk.id}`);
    const jpeg = withLocation(await makeJpeg(page));

    await page.getByLabel('사진 추가').setInputFiles({ name: 'dog.jpg', mimeType: 'image/jpeg', buffer: jpeg });
    const photos = page.getByTestId('walk-photo');
    await expect(photos).toHaveCount(1);
    await expect.poll(() => photos.first().evaluate((image: HTMLImageElement) => image.naturalWidth)).toBe(64);
    await expect(page.getByText('공유 화면에는 나오지 않아요')).toBeVisible();

    const detail = await (await request.get(`/api/my-walks/${walk.id}`)).json();
    const stored = await (await request.get(`/api/my-walks/${walk.id}/photos/${detail.photos[0].id}`)).body();
    expect(stored.includes('GPSLatitude')).toBe(false);
    expect(stored.includes('GPS-TRAILER')).toBe(false);

    // 화면을 거치지 않고 원본을 바로 올려도 서버가 위치 정보를 지우고, 사진은 그대로 열린다.
    const raw = await request.post(`/api/my-walks/${walk.id}/photos`, { data: jpeg, headers: { 'Content-Type': 'image/jpeg' } });
    expect(raw.status()).toBe(201);
    const rawPhoto = await raw.json();
    const cleaned = await (await request.get(`/api/my-walks/${walk.id}/photos/${rawPhoto.id}`)).body();
    expect(cleaned.includes('GPSLatitude')).toBe(false);
    expect(cleaned.includes('GPS-TRAILER')).toBe(false);
    const width = await page.evaluate(async (url) => {
      const image = new Image();
      image.src = url;
      await image.decode();
      return image.naturalWidth;
    }, `/api/my-walks/${walk.id}/photos/${rawPhoto.id}`);
    expect(width).toBe(64);

    const token = (await (await request.post(`/api/my-walks/${walk.id}/share`, { data: { share_memo: true } })).json()).share_token;
    const viewer = await (await browser.newContext()).newPage();
    await viewer.goto(`/shared/${token}`);
    await expect(viewer.getByTestId('shared-title')).toBeVisible();
    await expect(viewer.locator('img[src*="/photos/"]')).toHaveCount(0);
    await viewer.context().close();

    await page.reload();
    await expect(photos).toHaveCount(2);
    page.once('dialog', (dialog) => dialog.accept());
    await page.getByRole('button', { name: '사진 1 삭제' }).click();
    await expect(photos).toHaveCount(1);
  });

  test('GPX를 가져올 때 고른 사진이 함께 저장되고, 5장을 넘기면 알린다', async ({ page }) => {
    await page.goto('/my-walks/import');
    await page.getByLabel('GPX 파일').setInputFiles({ name: 'photo-walk.gpx', mimeType: 'application/gpx+xml', buffer: Buffer.from(GPX) });
    await expect(page.getByTestId('gpx-result')).toBeVisible();
    await expect(page.getByText('시연 보호자 계정에 저장돼요')).toBeVisible();

    const jpeg = await makeJpeg(page);
    const files = Array.from({ length: 6 }, (_, index) => ({ name: `photo-${index}.jpg`, mimeType: 'image/jpeg', buffer: jpeg }));
    await page.getByLabel('사진 고르기').setInputFiles(files);
    await expect(page.getByTestId('pending-photo')).toHaveCount(5);
    await expect(page.getByTestId('photo-picker').getByRole('alert')).toContainText('5장까지');
    await page.getByRole('button', { name: '사진 5 빼기' }).click();
    await expect(page.getByTestId('pending-photo')).toHaveCount(4);

    await page.getByLabel('산책길 이름').fill(`사진 가져오기 ${Date.now()}`);
    await page.getByRole('button', { name: '산책길로 저장' }).click();
    await expect(page).toHaveURL(/\/my-walks\/\d+$/);
    await expect(page.getByTestId('walk-photo')).toHaveCount(4);
  });

  test('열 수 없는 파일은 이유를 알리고 고르지 않는다', async ({ page }) => {
    await page.goto('/my-walks/import');
    await page.getByLabel('GPX 파일').setInputFiles({ name: 'photo-walk.gpx', mimeType: 'application/gpx+xml', buffer: Buffer.from(GPX) });
    await page.getByLabel('사진 고르기').setInputFiles({ name: 'note.jpg', mimeType: 'image/jpeg', buffer: Buffer.from('not an image') });
    await expect(page.getByTestId('photo-picker').getByRole('alert')).toContainText('열 수 없는 사진');
    await expect(page.getByTestId('pending-photo')).toHaveCount(0);
  });

  test('다른 계정의 사진은 주소를 알아도 열리지 않는다', async ({ page, request }) => {
    const walk = await guestWalk(request);
    const photo = await (await request.post(`/api/my-walks/${walk.id}/photos`, { data: await makeJpeg(page), headers: { 'Content-Type': 'image/jpeg' } })).json();
    await signUpInBrowser(page, newId());
    await expect(page).toHaveURL(/\/$/);
    expect((await page.request.get(`/api/my-walks/${walk.id}/photos/${photo.id}`)).status()).toBe(404);
  });
});

test.describe('Google 로그인', () => {
  const GOOGLE_USER = { id: 99, name: '구글 보호자', login_id: null, email: 'dubu@example.com', provider: 'google' };

  test('Google로 계속하기는 PKCE와 state를 붙여 Google 로그인 화면으로 보낸다', async ({ page }) => {
    await page.goto('/my-walks');
    await page.locator('header').getByRole('link', { name: '로그인' }).click();
    const button = page.getByRole('link', { name: 'Google로 계속하기' });
    await expect(button).toHaveAttribute('href', '/api/auth/google/start?next=%2Fmy-walks');

    // 실제 Google에 접속하지 않도록 브라우저를 보내지 않고 서버의 리디렉션 응답만 확인한다.
    const response = await page.request.get((await button.getAttribute('href'))!, { maxRedirects: 0 });
    expect(response.status()).toBe(302);
    expect(response.headers()['set-cookie']).toContain('pawpath_google_state=');
    const location = new URL(response.headers()['location']);
    expect(`${location.origin}${location.pathname}`).toBe('https://accounts.google.com/o/oauth2/v2/auth');
    const params = location.searchParams;
    expect(params.get('client_id')).toBe('e2e-client.apps.googleusercontent.com');
    expect(params.get('redirect_uri')).toBe('http://127.0.0.1:5183/api/auth/google/callback');
    expect(params.get('response_type')).toBe('code');
    expect(params.get('scope')).toBe('openid email profile');
    expect(params.get('code_challenge_method')).toBe('S256');
    expect(params.get('state')!.length).toBeGreaterThanOrEqual(40);
    expect(params.get('nonce')!.length).toBeGreaterThanOrEqual(40);

    // Google 화면에서 취소하고 돌아오면 이유를 알린다.
    await page.goto(`/api/auth/google/callback?error=access_denied&state=${params.get('state')}`);
    await expect(page).toHaveURL(/\/login\?error=google_cancelled$/);
    await expect(page.getByRole('alert')).toContainText('Google 로그인을 취소했어요');
  });

  test('다른 브라우저에서 시작한 로그인으로 돌아오면 막고 이유를 알린다', async ({ page }) => {
    await page.goto('/api/auth/google/callback?state=made-by-someone-else&code=stolen-code');
    await expect(page).toHaveURL(/\/login\?error=google_state$/);
    await expect(page.getByRole('alert')).toContainText('시작한 주소와 돌아온 주소가 달라요');
    expect((await (await page.request.get('/api/auth/me')).json()).authenticated).toBe(false);
  });

  test('실패 이유마다 다른 안내를 보여 준다', async ({ page }) => {
    for (const [code, text] of [
      ['google_failed', '실패했어요'],
      ['google_unavailable', '설정되어 있지 않아요'],
    ]) {
      await page.goto(`/login?error=${code}`);
      await expect(page.getByRole('alert')).toContainText(text);
    }
  });

  test('Google로 로그인한 보호자는 마이페이지에 Google 계정으로 표시된다', async ({ page }) => {
    await page.route('**/api/auth/me', (route) => route.fulfill({ json: { authenticated: true, auth_required: false, google_enabled: true, user: GOOGLE_USER } }));
    await page.goto('/my');
    await expect(page.getByText('Google 계정으로 로그인')).toBeVisible();
    await expect(page.getByTestId('account-name')).toContainText('dubu@example.com');
  });

  test('Google 설정이 없는 서버에서는 버튼을 숨긴다', async ({ page }) => {
    await page.route('**/api/auth/me', (route) => route.fulfill({ json: { authenticated: false, auth_required: false, google_enabled: false, user: null } }));
    await page.goto('/login');
    await expect(page.getByRole('heading', { name: '로그인' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Google로 계속하기' })).toHaveCount(0);
  });
});

