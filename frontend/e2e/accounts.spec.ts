import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

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
  await page.getByRole('button', { name: '회원가입' }).click();
  await page.getByLabel('아이디').fill(loginId);
  await page.getByLabel('비밀번호').fill(PASSWORD);
  await page.getByLabel('이름').fill(name);
  await page.getByRole('button', { name: '가입하고 시작하기' }).click();
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

  test('로그인이 만료되면 알리고 다시 로그인하도록 안내한다', async ({ page, context, request }) => {
    await signUpInBrowser(page, newId());
    await expect(page).toHaveURL(/\/$/);
    expect((await page.request.post('/api/pets', { data: PET })).status()).toBe(201);
    await page.reload();
    await expect(page.locator('header').getByRole('link', { name: '콩' })).toBeVisible();

    // 서버에서 세션을 끝내 만료된 상황을 만든다. 브라우저에는 이제 쓸 수 없는 쿠키가 남아 있다.
    const token = (await context.cookies()).find((cookie) => cookie.name === 'pawpath_session')!.value;
    await request.post('/api/auth/logout', { headers: { Cookie: `pawpath_session=${token}` } });
    await page.getByRole('navigation', { name: '주요 메뉴' }).getByRole('link', { name: '마이' }).click();
    const banner = page.getByTestId('auth-notice');
    await expect(banner).toContainText('로그인이 만료되었어요');
    // 시연 보호자로 돌아간 뒤에는 이전 오류가 남지 않는다.
    await expect(page.getByRole('alert')).toHaveCount(1);
    await expect(page.locator('header').getByRole('link', { name: '콩' })).toHaveCount(0);
    await banner.getByRole('link', { name: '로그인' }).click();
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole('alert')).toContainText('로그인이 만료되었어요');
  });

  test('로그인이 필수인 서버면 로그인 화면으로 보낸다', async ({ page }) => {
    await page.route('**/api/auth/me', (route) => route.fulfill({ json: { authenticated: false, auth_required: true, user: null } }));
    await page.goto('/recommend');
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByText('이 서버는 로그인해야 쓸 수 있어요')).toBeVisible();
    await expect(page.getByRole('link', { name: '로그인하지 않고 시연 보호자로 둘러보기' })).toHaveCount(0);
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

