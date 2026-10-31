import { readFileSync } from 'node:fs';
import { expect, test, type Browser, type Page } from '@playwright/test';
import { buildRoute, pointAt, type LatLng } from '../src/lib/navigation';
import { signIn } from './login';

const SECRET_TITLE = '우리집 앞 비밀 이름';
const SECRET_MEMO = '현관에서 출발한 비밀 메모';
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

const unique = () => `${Date.now()}${Math.floor(Math.random() * 1000)}`;

async function signInAs(page: Page, name = '앨리스') {
  await signIn(page, `user${unique()}`, name);
}

/** 북쪽으로 곧게 걷는 경로. 지점 간격은 약 55m다. */
function line(count = 40, lat = 37.55, lng = 126.91) {
  return Array.from({ length: count }, (_, index) => ({
    latitude: lat + index * 0.0005,
    longitude: lng,
    recorded_at: new Date(Date.UTC(2026, 9, 29, 0, 0, index * 40)).toISOString(),
    accuracy: 5,
    segment: 0,
  }));
}

async function makeWalk(page: Page, overrides: Record<string, unknown> = {}) {
  const response = await page.request.post('/api/my-walks', { data: { title: SECRET_TITLE, memo: SECRET_MEMO, points: line(), ...overrides } });
  expect(response.status()).toBe(201);
  return response.json();
}

async function shareTrail(page: Page, overrides: Record<string, unknown> = {}, walkOverrides: Record<string, unknown> = {}) {
  const walk = await makeWalk(page, walkOverrides);
  const response = await page.request.post('/api/community/trails', { data: { saved_walk_id: walk.id, title: `공유한 길 ${unique()}`, description: '그늘이 좋아요', ...overrides } });
  expect(response.status()).toBe(201);
  return response.json();
}

async function asNewMember(browser: Browser, name = '밥'): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await signInAs(page, name);
  return page;
}

async function asGuest(browser: Browser): Promise<Page> {
  return (await browser.newContext()).newPage();
}

async function makeJpeg(page: Page): Promise<Buffer> {
  const dataUrl = await page.evaluate(() => {
    const canvas = document.createElement('canvas');
    canvas.width = 64;
    canvas.height = 48;
    const context = canvas.getContext('2d')!;
    context.fillStyle = '#2e8b62';
    context.fillRect(0, 0, 64, 48);
    return canvas.toDataURL('image/jpeg', 0.9);
  });
  return Buffer.from(dataUrl.split(',')[1], 'base64');
}

/** 모바일 에뮬레이션은 내용이 넘치면 window.innerWidth까지 늘어나므로, 지정한 화면 폭과 비교한다. */
async function expectNoSideScroll(page: Page, width: number, where: string) {
  const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(scrollWidth, `${where} 가로 넘침`).toBeLessThanOrEqual(width);
}

test.describe('산책길 공유', () => {
  test('내 산책길 상세에서 공유하면 가린 경로로 커뮤니티와 상세에 나온다', async ({ page, browser }) => {
    await signInAs(page);
    const walk = await makeWalk(page);
    const title = `양재천 그늘길 ${unique()}`;

    await page.goto(`/my-walks/${walk.id}`);
    await page.getByTestId('community-panel').getByRole('link', { name: '커뮤니티에 공유하기' }).click();
    await expect(page).toHaveURL(new RegExp(`/community/share\\?walk=${walk.id}$`));
    await expect(page.getByTestId('trail-preview-summary')).toContainText('가렸어요');
    await expect(page.locator('path.walk-line')).toHaveCount(1);
    await expect(page.getByText('작성자 이름은 “앨리스”으로 표시돼요.')).toBeVisible();

    const before = await page.getByTestId('trail-preview-summary').textContent();
    await page.getByRole('button', { name: '500m' }).click();
    await expect(page.getByTestId('trail-preview-summary')).not.toHaveText(before!);
    await page.getByRole('button', { name: '200m' }).click();

    await page.getByLabel('산책길 제목').fill(title);
    await page.getByLabel('산책길 설명').fill('강아지가 좋아하는 그늘길이에요');
    await page.getByRole('button', { name: '공원', exact: true }).click();
    await page.getByRole('button', { name: '소형견', exact: true }).click();
    await page.getByRole('button', { name: '공유하기' }).click();

    await expect(page).toHaveURL(/\/community\/trails\/\d+$/);
    await expect(page.getByTestId('trail-title')).toHaveText(title);
    await expect(page.getByTestId('trail-author')).toHaveText('앨리스');
    await expect(page.getByTestId('trail-description')).toHaveText('강아지가 좋아하는 그늘길이에요');
    await expect(page.getByTestId('trail-tags')).toContainText('공원');
    await expect(page.getByTestId('trail-tags')).toContainText('소형견 추천');
    await expect(page.locator('path.walk-line')).toHaveCount(1);
    await expect(page.getByText('출발', { exact: true }).first()).toBeVisible();
    await expect(page.getByText('도착', { exact: true }).first()).toBeVisible();
    await expect(page.getByTestId('trail-stats')).toContainText('km');
    const url = page.url();

    // 내 산책길 상세에서 상태를 볼 수 있다.
    await page.goto(`/my-walks/${walk.id}`);
    await expect(page.getByTestId('community-panel').getByRole('link', { name: '공유한 산책길 보기' })).toBeVisible();

    // 다른 사람에게는 원본 이름과 메모, 비공개 정보가 보이지 않는다.
    const guest = await asGuest(browser);
    await guest.goto('/community');
    await guest.getByLabel('산책길 검색').fill(title);
    const card = guest.getByTestId('trail-card').filter({ hasText: title });
    await expect(card).toBeVisible();
    await expect(card).toContainText('앨리스');
    await expect(card).toContainText('km');
    await expect(card.getByTestId('route-thumbnail')).toBeVisible();
    await card.getByRole('link').click();
    await expect(guest).toHaveURL(url);
    await expect(guest.getByTestId('trail-title')).toHaveText(title);
    await expect(guest.getByText(SECRET_TITLE)).toHaveCount(0);
    await expect(guest.getByText(SECRET_MEMO)).toHaveCount(0);
    await guest.context().close();
  });

  test('공유 화면에서 직접 기록과 GPX 경로를 골라 공유한다', async ({ page }) => {
    await signInAs(page);
    const recorded = await makeWalk(page, { title: `기록한 길 ${unique()}` });
    const imported = await makeWalk(page, { title: `가져온 길 ${unique()}`, source_type: 'imported', points: line(40, 37.55, 126.92) });

    await page.goto('/community');
    await page.getByRole('link', { name: '산책길 공유' }).click();
    await expect(page.getByTestId('shareable-walk').filter({ hasText: recorded.title })).toBeVisible();
    await expect(page.getByTestId('shareable-walk').filter({ hasText: imported.title })).toHaveCount(0);
    await page.getByRole('button', { name: 'GPX 가져옴' }).click();
    await page.getByTestId('shareable-walk').filter({ hasText: imported.title }).click();
    await expect(page.getByLabel('산책길 제목')).toHaveValue(imported.title);
    await page.getByRole('button', { name: '공유하기' }).click();
    await expect(page).toHaveURL(/\/community\/trails\/\d+$/);

    // 이미 공유한 길은 목록에서 빠진다.
    await page.goto('/community/share');
    await page.getByRole('button', { name: 'GPX 가져옴' }).click();
    await expect(page.getByTestId('shareable-walk').filter({ hasText: imported.title })).toHaveCount(0);
  });

  test('대표 이미지를 올려 고르면 카드와 상세에 나온다', async ({ page }) => {
    await signInAs(page);
    const walk = await makeWalk(page);
    await page.goto(`/community/share?walk=${walk.id}`);
    await page.getByLabel('대표 이미지 올리기').setInputFiles({ name: 'cover.jpg', mimeType: 'image/jpeg', buffer: await makeJpeg(page) });
    await expect(page.getByRole('button', { name: '사진 1을 대표 이미지로' })).toHaveAttribute('aria-pressed', 'true');
    const title = `사진 있는 길 ${unique()}`;
    await page.getByLabel('산책길 제목').fill(title);
    await page.getByRole('button', { name: '공유하기' }).click();
    const hero = page.getByTestId('trail-hero');
    await expect(hero).toBeVisible();
    await expect(async () => expect(await hero.evaluate((image: HTMLImageElement) => image.naturalWidth)).toBeGreaterThan(0)).toPass();

    await page.goto(`/community?q=${encodeURIComponent(title)}`);
    await expect(page.getByTestId('trail-card').getByTestId('trail-cover')).toBeVisible();
  });

  test('원본이 링크 공유 상태면 가리지 않은 경로가 열린다고 경고한다', async ({ page }) => {
    await signInAs(page);
    const walk = await makeWalk(page, { visibility: 'link' });
    await page.goto(`/community/share?walk=${walk.id}`);
    await expect(page.getByText('가리지 않은 경로가 열려요')).toBeVisible();
    const hidden = await makeWalk(page, { points: line(40, 37.55, 126.92) });
    await page.goto(`/community/share?walk=${hidden.id}`);
    await expect(page.getByTestId('trail-preview-summary')).toBeVisible();
    await expect(page.getByText('가리지 않은 경로가 열려요')).toHaveCount(0);
  });

  test('사진이 있어도 직접 고르기 전에는 대표 이미지로 공개하지 않는다', async ({ page, browser }) => {
    await signInAs(page);
    const walk = await makeWalk(page);
    expect((await page.request.post(`/api/my-walks/${walk.id}/photos`, { data: await makeJpeg(page), headers: { 'Content-Type': 'image/jpeg' } })).status()).toBe(201);
    await page.goto(`/community/share?walk=${walk.id}`);
    await expect(page.getByRole('button', { name: '사진 1을 대표 이미지로' })).toHaveAttribute('aria-pressed', 'false');
    await page.getByRole('button', { name: '공유하기' }).click();
    await expect(page).toHaveURL(/\/community\/trails\/\d+$/);
    await expect(page.getByTestId('trail-hero')).toHaveCount(0);
    const id = page.url().split('/').at(-1);
    const guest = await asGuest(browser);
    expect((await guest.request.get(`/api/community/trails/${id}/cover`)).status()).toBe(404);
    await guest.context().close();
  });

  test('자동 생성 경로는 공유 대상에 없고, 주소로 들어와도 공유할 수 없다', async ({ page }) => {
    await signInAs(page);
    const generated = await makeWalk(page, { title: `자동 생성 길 ${unique()}`, source_type: 'generated' });
    await page.goto(`/my-walks/${generated.id}`);
    const panel = page.getByTestId('community-panel');
    await expect(panel).toContainText('아직 아무도 걷지 않은 길');
    await expect(panel.getByRole('link', { name: '커뮤니티에 공유하기' })).toHaveCount(0);

    await page.goto('/community/share');
    await expect(page.getByRole('button', { name: '직접 기록' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'GPX 가져옴' })).toBeVisible();
    await expect(page.getByRole('button', { name: '자동 생성' })).toHaveCount(0);

    await page.goto(`/community/share?walk=${generated.id}`);
    await expect(page.getByText('직접 걸은 길만 공유할 수 있어요')).toBeVisible();
    await expect(page.getByRole('button', { name: '공유하기' })).toBeDisabled();
  });

  test('가리고 나면 너무 짧은 길은 이유를 알리고 공유를 막는다', async ({ page }) => {
    await signInAs(page);
    const walk = await makeWalk(page, { points: line(14) });
    await page.goto(`/community/share?walk=${walk.id}`);
    await expect(page.getByTestId('trail-preview-summary')).toBeVisible();
    await page.getByRole('button', { name: '500m' }).click();
    await expect(page.getByText('남는 길이 너무 짧아요')).toBeVisible();
    await expect(page.getByRole('button', { name: '공유하기' })).toBeDisabled();
  });
});

test.describe('로그인하지 않은 사용자', () => {
  test('목록과 상세는 보되 쓰기는 로그인으로 보내고, 로그인하면 돌아온다', async ({ page, browser }) => {
    const author = await asNewMember(browser, '작성자');
    const trail = await shareTrail(author);
    await author.context().close();

    await page.goto(`/community/trails/${trail.id}`);
    await expect(page.getByTestId('trail-title')).toHaveText(trail.title);
    await expect(page.getByText('로그인하면 후기를 남길 수 있어요')).toBeVisible();
    await expect(page.getByTestId('review-form')).toHaveCount(0);

    await page.getByTestId('like-button').click();
    await expect(page).toHaveURL(/\/login$/);
    // Google 로그인이 끝나면 원래 보던 산책길로 돌아오도록 주소를 넘긴다.
    const next = `/community/trails/${trail.id}`;
    await expect(page.getByRole('link', { name: 'Google로 계속하기' })).toHaveAttribute('href', `/api/auth/google/start?next=${encodeURIComponent(next)}`);
    // 처음 로그인한 보호자는 서버가 대표 프로필 설정을 거쳐 그 주소로 보낸다.
    await signIn(page, `user${unique()}`);
    await page.goto(`/profiles/setup?next=${encodeURIComponent(next)}`);
    await page.getByRole('button', { name: '시작하기', exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/community/trails/${trail.id}$`));
    await expect(page.getByTestId('review-form')).toBeVisible();
  });

  test('공유와 관리 화면은 로그인을 안내한다', async ({ page }) => {
    await page.goto('/community/share');
    await expect(page.getByText('로그인하면 산책길을 공유할 수 있어요')).toBeVisible();
    await page.goto('/community/my');
    await expect(page.getByText('로그인하면 공유하고 저장한 산책길을 관리할 수 있어요')).toBeVisible();
    const walk = await makeWalk(page, { title: `시연 보호자 길 ${unique()}` });
    await page.goto(`/my-walks/${walk.id}`);
    await expect(page.getByTestId('community-panel').getByRole('link', { name: '커뮤니티에 공유하기' })).toHaveCount(0);
    await expect(page.getByTestId('community-panel')).toContainText('로그인');
  });
});

test.describe('탐색', () => {
  test('검색, 필터, 정렬, 빈 목록, 더 보기', async ({ page, browser }) => {
    const author = await asNewMember(browser, '작성자');
    const marker = `검색어${unique()}`;
    const short = await shareTrail(author, { title: `${marker} 짧은 길`, suitable_for: ['senior'], region: '망원동' }, { points: line(15) });
    const long = await shareTrail(author, { title: `${marker} 긴 길`, suitable_for: ['active'], region: '합정동' }, { points: line(130, 37.55, 126.92) });

    await page.goto('/community');
    await expect(page.getByRole('heading', { name: '산책길 커뮤니티' })).toBeVisible();
    await page.getByLabel('산책길 검색').fill(marker);
    const cards = page.getByTestId('trail-card');
    await expect(page).toHaveURL(/q=/);
    await expect(cards).toHaveCount(2);
    // 최신순이 기본이다.
    await expect(cards.first()).toContainText(long.title);

    await page.getByTestId('trail-filters').locator('summary').click();
    await page.getByLabel('거리별 보기').selectOption('short');
    await expect(cards).toHaveCount(1);
    await expect(cards.first()).toContainText(short.title);
    await page.getByLabel('거리별 보기').selectOption('');
    await page.getByLabel('추천 대상별 보기').selectOption('active');
    await expect(cards).toHaveCount(1);
    await expect(cards.first()).toContainText(long.title);
    await page.getByLabel('추천 대상별 보기').selectOption('');
    await page.getByLabel('지역별 보기').selectOption('망원동');
    await expect(cards).toHaveCount(1);
    await page.getByLabel('지역별 보기').selectOption('');
    await page.getByLabel('난이도별 보기').selectOption('hard');
    await expect(cards).toHaveCount(1);
    await expect(cards.first()).toContainText(long.title);
    await page.getByLabel('난이도별 보기').selectOption('');
    await page.getByLabel('시간별 보기').selectOption('long');
    await expect(cards).toHaveCount(1);
    await page.getByLabel('시간별 보기').selectOption('');

    // 좋아요를 받은 길이 인기순에서 앞선다.
    await author.request.post(`/api/community/trails/${short.id}/like`);
    await page.getByRole('button', { name: '인기순' }).click();
    await expect(cards.first()).toContainText(short.title);
    await page.getByRole('button', { name: '평점순' }).click();
    await expect(cards).toHaveCount(2);
    await page.getByRole('button', { name: '최신순' }).click();

    // 조건에 맞는 길이 없으면 알리고 조건을 지울 수 있다.
    await page.getByLabel('산책길 검색').fill(`${marker}없는말`);
    await expect(page.getByText('조건에 맞는 산책길이 없어요')).toBeVisible();
    await page.getByRole('button', { name: '조건 지우기' }).click();
    await expect(page.getByLabel('산책길 검색')).toHaveValue('');
    await author.context().close();
  });

  test('인기 영역과 더 보기가 동작하고 다시 들어와도 조건이 유지된다', async ({ page, browser }) => {
    const author = await asNewMember(browser, '작성자');
    const marker = `여럿${unique()}`;
    for (let index = 0; index < 13; index += 1) {
      await shareTrail(author, { title: `${marker} ${index}` }, { points: line(12, 37.55, 126.9 + index * 0.001) });
    }
    const liked = await shareTrail(author, { title: `${marker} 인기` }, { points: line(12, 37.55, 126.95) });
    await author.request.post(`/api/community/trails/${liked.id}/like`);

    await page.goto('/community');
    const firstPopular = page.getByTestId('popular-trails').getByTestId('trail-card').first();
    await expect(firstPopular).toBeVisible();
    // 스크롤 스냅이 첫 카드를 화면 끝에 붙이지 않는다.
    expect((await firstPopular.boundingBox())!.x).toBeGreaterThanOrEqual(16);
    await page.goto(`/community?q=${marker}`);
    await expect(page.getByTestId('popular-trails')).toHaveCount(0);
    const list = page.getByRole('list', { name: '산책길 목록' }).getByTestId('trail-card');
    await expect(list).toHaveCount(12);
    await expect(page.getByTestId('trail-total')).toHaveText('14개');
    await page.getByRole('button', { name: '더 보기' }).click();
    await expect(list).toHaveCount(14);
    await expect(page.getByRole('button', { name: '더 보기' })).toHaveCount(0);

    await list.first().getByRole('link').click();
    await expect(page).toHaveURL(/\/community\/trails\/\d+$/);
    await page.goBack();
    await expect(page.getByLabel('산책길 검색')).toHaveValue(marker);
    await author.context().close();
  });

  test.describe('내 주변', () => {
    test.use({ permissions: ['geolocation'], geolocation: { latitude: 37.5512, longitude: 126.91, accuracy: 10 } });

    test('위치를 읽어 가까운 길을 본문으로 찾는다', async ({ page, browser }) => {
      const author = await asNewMember(browser, '작성자');
      const trail = await shareTrail(author);
      await author.context().close();
      const requests: string[] = [];
      page.on('request', (request) => requests.push(request.url()));
      await page.goto('/community?view=near');
      const card = page.getByRole('list', { name: '내 주변 산책길' }).getByTestId('trail-card').filter({ hasText: trail.title });
      await expect(card).toBeVisible();
      await expect(card).toContainText('내 위치에서 약');
      expect(requests.some((url) => url.includes('/community/trails/nearby'))).toBe(true);
      expect(requests.filter((url) => url.includes('37.5512'))).toEqual([]);
    });
  });

  test('위치 권한을 거부하면 이유를 알린다', async ({ page }) => {
    await page.addInitScript(() => {
      navigator.geolocation.getCurrentPosition = (_success, error) => {
        error?.({ code: 1, PERMISSION_DENIED: 1, POSITION_UNAVAILABLE: 2, TIMEOUT: 3, message: 'denied' } as GeolocationPositionError);
      };
    });
    await page.goto('/community');
    await page.getByRole('button', { name: '내 주변' }).click();
    await expect(page.getByText('위치 권한이 꺼져 있어요')).toBeVisible();
  });

  test('반려동물 맞춤 추천은 점수와 근거를 함께 보여 준다', async ({ page, browser }) => {
    const author = await asNewMember(browser, '작성자');
    await shareTrail(author, { suitable_for: ['small'] }, { points: line(20) });
    await author.context().close();
    await page.goto('/community');
    await page.getByRole('button', { name: '두부 맞춤' }).click();
    const list = page.getByRole('list', { name: '추천 산책길 목록' });
    await expect(list.getByTestId('trail-card').first()).toBeVisible();
    await expect(list.getByTestId('trail-reasons').first()).toContainText('맞춤 점수');
  });

  test('서버 오류와 불러오는 중을 각각 표시한다', async ({ page }) => {
    let release = () => {};
    const gate = new Promise<void>((resolve) => (release = resolve));
    await page.route('**/api/community/trails?*', async (route) => {
      await gate;
      await route.fulfill({ status: 500, json: { detail: '잠시 뒤 다시 시도해 주세요' } });
    });
    await page.goto('/community');
    await expect(page.getByRole('status')).toContainText('불러오는 중');
    release();
    await expect(page.getByText('잠시 뒤 다시 시도해 주세요')).toBeVisible();
  });
});

test.describe('좋아요와 저장', () => {
  test('누르는 즉시 바뀌고, 저장되며, 실패하면 되돌린다', async ({ page, browser }) => {
    const author = await asNewMember(browser, '작성자');
    const trail = await shareTrail(author);
    await author.context().close();
    await signInAs(page, '밥');
    await page.goto(`/community/trails/${trail.id}`);
    const like = page.getByTestId('like-button');
    const bookmark = page.getByTestId('bookmark-button');
    await expect(like).toHaveAttribute('aria-pressed', 'false');

    // 서버 응답 전에 화면이 먼저 바뀐다.
    let release = () => {};
    const gate = new Promise<void>((resolve) => (release = resolve));
    await page.route('**/like', async (route) => {
      await gate;
      await route.continue();
    });
    await like.click();
    await expect(like).toHaveAttribute('aria-pressed', 'true');
    await expect(like).toHaveText('좋아요 1');
    release();
    await page.waitForResponse((response) => response.url().includes('/like') && response.ok());
    await page.unroute('**/like');
    await page.reload();
    await expect(like).toHaveAttribute('aria-pressed', 'true');
    await expect(like).toHaveText('좋아요 1');

    await like.click();
    await expect(like).toHaveText('좋아요 0');
    await expect(like).toHaveAttribute('aria-pressed', 'false');

    // 실패하면 원래대로 돌아가고 이유를 알린다.
    await page.waitForLoadState('networkidle');
    await page.route('**/like', (route) => route.abort());
    await like.click();
    await expect(page.getByText('서버에 연결할 수 없어요')).toBeVisible();
    await expect(like).toHaveAttribute('aria-pressed', 'false');
    await expect(like).toHaveText('좋아요 0');
    await page.unroute('**/like');

    await bookmark.click();
    await expect(bookmark).toHaveAttribute('aria-pressed', 'true');
    await expect(bookmark).toHaveText('저장 1');
    await expect(page.getByText('저장한 산책길에 담았어요')).toBeVisible();

    await page.goto('/community/my?tab=bookmarks');
    const saved = page.getByRole('list', { name: '저장한 산책길' }).getByTestId('trail-card').filter({ hasText: trail.title });
    await expect(saved).toBeVisible();
    await saved.getByRole('link').click();
    await expect(bookmark).toHaveAttribute('aria-pressed', 'true');
    await bookmark.click();
    await expect(bookmark).toHaveText('저장 0');
    await page.goto('/community/my?tab=bookmarks');
    await expect(page.getByText('아직 저장한 산책길이 없어요')).toBeVisible();
  });
});

test.describe('후기', () => {
  test('별점과 사진을 남기고 수정, 삭제하면 평균이 함께 바뀐다', async ({ page, browser }) => {
    const author = await asNewMember(browser, '작성자');
    const trail = await shareTrail(author);
    await signInAs(page, '밥');
    await page.goto(`/community/trails/${trail.id}`);
    await expect(page.getByText('아직 후기가 없어요')).toBeVisible();

    const form = page.getByTestId('review-form');
    await expect(form.getByRole('button', { name: '후기 남기기' })).toBeDisabled();
    await form.getByRole('button', { name: '4점' }).click();
    await form.getByLabel('후기 내용').fill('그늘이 많아 좋았어요');
    await form.getByLabel('후기 사진 고르기').setInputFiles({ name: 'review.jpg', mimeType: 'image/jpeg', buffer: await makeJpeg(page) });
    await expect(form.getByTestId('review-pending-photo')).toHaveCount(1);
    await form.getByRole('button', { name: '후기 남기기' }).click();

    const item = page.getByTestId('review-item');
    await expect(item.getByTestId('review-content')).toHaveText('그늘이 많아 좋았어요');
    await expect(item.getByRole('img', { name: '별점 4점' })).toBeVisible();
    await expect(item.getByText('일반 후기')).toBeVisible();
    await expect(item.getByTestId('review-photo')).toHaveCount(1);
    await expect(item).toContainText('밥');
    await expect(page.getByTestId('trail-counters')).toContainText('평균 4.0점 (1)');
    // 후기는 한 번만 남기므로 입력 칸이 사라진다.
    await expect(page.getByRole('button', { name: '후기 남기기' })).toHaveCount(0);

    await item.getByRole('button', { name: '수정' }).click();
    await item.getByRole('button', { name: '2점' }).click();
    await item.getByLabel('후기 내용').fill('다시 가 보니 그저 그래요');
    await item.getByRole('button', { name: '후기 고치기' }).click();
    await expect(item.getByTestId('review-content')).toHaveText('다시 가 보니 그저 그래요');
    await expect(page.getByTestId('trail-counters')).toContainText('평균 2.0점 (1)');

    // 다른 보호자에게는 수정 버튼이 없고, 작성자는 자기 길에 후기를 쓰지 못한다.
    await author.goto(`/community/trails/${trail.id}`);
    await expect(author.getByTestId('review-item').getByRole('button', { name: '수정' })).toHaveCount(0);
    await expect(author.getByTestId('review-form')).toHaveCount(0);
    await expect(author.getByText('내가 공유한 산책길에는 후기를 남길 수 없어요')).toBeVisible();

    await page.goto('/community/my?tab=reviews');
    await expect(page.getByTestId('my-review').filter({ hasText: trail.title })).toBeVisible();
    page.once('dialog', (dialog) => dialog.accept());
    await page.getByRole('button', { name: '후기 삭제' }).click();
    await expect(page.getByText('아직 작성한 후기가 없어요')).toBeVisible();
    await page.goto(`/community/trails/${trail.id}`);
    await expect(page.getByTestId('trail-counters')).toContainText('평점 없음');
    await expect(page.getByTestId('review-form')).toBeVisible();
    await author.context().close();
  });

  test.describe('산책 시작과 인증', () => {
    test.use({ permissions: ['geolocation'], geolocation: { latitude: 37.5, longitude: 126.9, accuracy: 10 } });

    test('이 산책길로 GPS 산책을 마치면 피드백을 거쳐 인증 후기로 이어진다', async ({ page, context, browser }) => {
      const author = await asNewMember(browser, '작성자');
      const trail = await shareTrail(author);
      await author.context().close();
      await signInAs(page, '밥');
      expect((await page.request.post('/api/pets', { data: PET })).status()).toBe(201);

      await page.goto(`/community/trails/${trail.id}`);
      await page.getByRole('button', { name: '이 산책길로 산책 시작' }).click();
      await expect(page).toHaveURL(/\/navigate\?course=\d+$/);
      await expect(page.getByTestId('navigate-course-name')).toHaveText(trail.title);
      await expect(page.getByTestId('navigation-map')).toBeVisible();

      const courseId = new URL(page.url()).searchParams.get('course');
      const course = await (await page.request.get(`/api/courses/${courseId}`)).json();
      const model = buildRoute(course.route as LatLng[]);
      const moveTo = (point: LatLng) => context.setGeolocation({ latitude: point[0], longitude: point[1], accuracy: 10 });
      await moveTo(pointAt(model, 0));
      await expect(page.getByTestId('walk-progress')).toBeVisible();
      for (let meters = 40; meters < model.total; meters += 40) {
        await moveTo(pointAt(model, meters));
      }
      await moveTo(pointAt(model, model.total));
      await expect(page.getByText('코스를 완주했어요!')).toBeVisible();

      await page.getByRole('button', { name: '피드백 남기기' }).click();
      await expect(page).toHaveURL(/\/walk$/);
      await page.getByRole('button', { name: '산책 만족도 5점' }).click();
      await page.getByRole('button', { name: /만족도 4점$/ }).nth(1).click();
      await page.getByRole('button', { name: '딱 좋았어요' }).click();
      await page.getByRole('button', { name: '날씨 만족도 3점' }).click();
      await page.getByRole('button', { name: '또 갈래요' }).click();
      await page.getByRole('button', { name: '피드백 남기기' }).click();
      await page.getByRole('link', { name: '이 산책길에 후기 남기기' }).click();
      await expect(page).toHaveURL(new RegExp(`/community/trails/${trail.id}#reviews$`));

      await expect(page.getByText('이 산책길을 GPS로 걸은 기록이 있어')).toBeVisible();
      const form = page.getByTestId('review-form');
      await form.getByRole('button', { name: '5점' }).click();
      await form.getByLabel('후기 내용').fill('직접 걸어 보니 좋았어요');
      await form.getByRole('button', { name: '후기 남기기' }).click();
      await expect(page.getByTestId('review-item').getByText('산책 인증')).toBeVisible();
    });

    test('시연용 걷기로 끝낸 산책은 인증되지 않는다', async ({ page, browser }) => {
      const author = await asNewMember(browser, '작성자');
      const trail = await shareTrail(author);
      await author.context().close();
      await signInAs(page, '밥');
      const pet = await (await page.request.post('/api/pets', { data: PET })).json();
      const { course_id: courseId } = await (await page.request.post(`/api/community/trails/${trail.id}/start`)).json();
      const created = await page.request.post('/api/walks', { data: { pet_id: pet.id, course_id: courseId, duration_min: 20, tracking_source: 'simulation' } });
      expect(created.status()).toBe(201);
      await page.goto(`/community/trails/${trail.id}`);
      await expect(page.getByText('이 산책길을 GPS로 걸은 기록이 있어')).toHaveCount(0);
      await expect(page.getByText('GPS로 절반 이상 걸으면 산책 인증이 붙어요')).toBeVisible();
    });
  });
});

test.describe('내 산책길 관리와 권한', () => {
  test('조회수는 보는 사람별로 한 번 세고, 같은 탭에서 작성자가 먼저 열어도 다음 보호자를 센다', async ({ page, context }) => {
    await signInAs(page);
    const trail = await shareTrail(page);
    const views = async () => (await (await page.request.get(`/api/community/trails/${trail.id}`)).json()).view_count;
    await page.goto(`/community/trails/${trail.id}`);
    await expect(page.getByTestId('trail-title')).toHaveText(trail.title);
    await page.waitForLoadState('networkidle');
    expect(await views()).toBe(0);

    await context.clearCookies();
    await signInAs(page, '밥');
    await page.reload();
    await expect(page.getByTestId('trail-title')).toHaveText(trail.title);
    await expect(async () => expect(await views()).toBe(1)).toPass();
    await page.reload();
    await expect(page.getByTestId('trail-title')).toHaveText(trail.title);
    await page.waitForLoadState('networkidle');
    expect(await views()).toBe(1);
  });

  test('공개 상태를 바꾸면 다른 사람에게서 닫히고, 해제해도 원본은 남는다', async ({ page, browser }) => {
    await signInAs(page);
    const walk = await makeWalk(page);
    const trail = await shareTrail(page, {}, { points: line(40, 37.55, 126.93) });
    const other = await asNewMember(browser, '밥');
    await other.request.post(`/api/community/trails/${trail.id}/bookmark`);
    await other.goto(`/community/trails/${trail.id}`);
    await expect(other.getByTestId('trail-title')).toHaveText(trail.title);

    await page.goto('/community/my');
    const card = page.getByTestId('trail-card').filter({ hasText: trail.title });
    await expect(card.getByText('공개', { exact: true })).toBeVisible();
    await card.getByRole('button', { name: '비공개로' }).click();
    await expect(card.getByText('비공개', { exact: true })).toBeVisible();

    await other.reload();
    await expect(other.getByText('찾을 수 없는 산책길이에요')).toBeVisible();
    expect((await other.request.get(`/api/community/trails/${trail.id}/gpx`)).status()).toBe(404);
    await other.goto(`/community?q=${encodeURIComponent(trail.title)}`);
    await expect(other.getByText('조건에 맞는 산책길이 없어요')).toBeVisible();
    await other.goto('/community/my?tab=bookmarks');
    await expect(other.getByText('저장한 산책길 1개는 작성자가 비공개로 돌려')).toBeVisible();
    // 주인은 볼 수 있다.
    await page.goto(`/community/trails/${trail.id}`);
    await expect(page.getByText('비공개 산책길이에요')).toBeVisible();
    await expect(page.getByRole('button', { name: '링크 공유' })).toBeDisabled();

    await page.goto('/community/my');
    await card.getByRole('button', { name: '공개로' }).click();
    await expect(card.getByText('공개', { exact: true })).toBeVisible();
    await other.goto(`/community/trails/${trail.id}`);
    await expect(other.getByTestId('trail-title')).toHaveText(trail.title);

    page.once('dialog', (dialog) => dialog.accept());
    await card.getByRole('button', { name: '공유 해제' }).click();
    await expect(card).toHaveCount(0);
    await other.reload();
    await expect(other.getByText('찾을 수 없는 산책길이에요')).toBeVisible();
    expect((await page.request.get(`/api/my-walks/${walk.id}`)).status()).toBe(200);
    await other.context().close();
  });

  test('공유한 길을 수정한다', async ({ page }) => {
    await signInAs(page);
    const trail = await shareTrail(page, { features: ['park'] });
    await page.goto(`/community/trails/${trail.id}`);
    await page.getByRole('link', { name: '수정' }).click();
    await expect(page).toHaveURL(new RegExp(`/community/trails/${trail.id}/edit$`));
    await expect(page.getByLabel('산책길 제목')).toHaveValue(trail.title);
    await expect(page.getByRole('button', { name: '공원', exact: true })).toHaveAttribute('aria-pressed', 'true');
    const title = `고친 제목 ${unique()}`;
    await page.getByLabel('산책길 제목').fill(title);
    await page.getByRole('button', { name: '공원', exact: true }).click();
    await page.getByRole('button', { name: '숲길', exact: true }).click();
    await page.getByRole('button', { name: '저장하기' }).click();
    await expect(page).toHaveURL(new RegExp(`/community/trails/${trail.id}$`));
    await expect(page.getByTestId('trail-title')).toHaveText(title);
    await expect(page.getByTestId('trail-tags')).toHaveText('숲길');
  });

  test('다른 사람의 산책길에는 관리 메뉴가 없고 주소로 들어와도 고칠 수 없다', async ({ page, browser }) => {
    const author = await asNewMember(browser, '작성자');
    const trail = await shareTrail(author);
    await author.context().close();
    await signInAs(page, '밥');
    await page.goto(`/community/trails/${trail.id}`);
    await expect(page.getByTestId('trail-title')).toHaveText(trail.title);
    await expect(page.getByRole('button', { name: '공유 해제' })).toHaveCount(0);
    await expect(page.getByRole('link', { name: '수정' })).toHaveCount(0);
    await page.goto(`/community/trails/${trail.id}/edit`);
    await expect(page.getByText('내가 공유한 산책길만 고칠 수 있어요')).toBeVisible();
    expect((await page.request.patch(`/api/community/trails/${trail.id}`, { data: { title: '탈취' } })).status()).toBe(403);
    expect((await page.request.delete(`/api/community/trails/${trail.id}`)).status()).toBe(403);
  });

  test('없는 산책길 주소는 안내하고 커뮤니티로 돌려보낸다', async ({ page }) => {
    await page.goto('/community/trails/99999999');
    await expect(page.getByText('찾을 수 없는 산책길이에요')).toBeVisible();
    await expect(page.getByRole('link', { name: '커뮤니티로 돌아가기' })).toBeVisible();
  });

  test('원본 산책길을 지우면 커뮤니티 글도 함께 사라진다고 묻고 지운다', async ({ page }) => {
    await signInAs(page);
    const trail = await shareTrail(page);
    const walks = await (await page.request.get('/api/my-walks')).json();
    await page.goto(`/my-walks/${walks[0].id}`);
    let message = '';
    page.once('dialog', (dialog) => {
      message = dialog.message();
      void dialog.accept();
    });
    await page.getByRole('button', { name: '삭제' }).click();
    await expect(page).toHaveURL(/\/my-walks$/);
    expect(message).toContain('커뮤니티에 공유한 글');
    expect((await page.request.get(`/api/community/trails/${trail.id}`)).status()).toBe(404);
  });
});

test.describe('개인정보와 보안', () => {
  test('GPX를 내려받으면 가린 경로만 있고 시각, 고도, 원본 정보가 없다', async ({ page, browser }) => {
    const author = await asNewMember(browser, '작성자');
    const points = line().map((point, index) => ({ ...point, altitude: 10 + index }));
    const trail = await shareTrail(author, { title: `내려받는 길 ${unique()}` }, { points });
    await author.context().close();

    await page.goto(`/community/trails/${trail.id}`);
    const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', { name: 'GPX 다운로드' }).click()]);
    const path = await download.path();
    const gpx = readFileSync(path, 'utf-8');
    expect(gpx).toContain(trail.title);
    for (const secret of ['<time>', '<ele>', SECRET_TITLE, SECRET_MEMO, '작성자', '2026']) {
      expect(gpx).not.toContain(secret);
    }
    // 원본 출발점 좌표는 들어 있지 않다.
    expect(gpx).not.toContain('lat="37.55"');
    expect(download.suggestedFilename()).not.toContain('2026');
    expect(gpx.match(/<trkpt /g)?.length).toBeLessThan(points.length);
  });

  test('제목과 설명, 후기에 넣은 코드는 글자로만 보인다', async ({ page, browser }) => {
    const payload = '<img src=x onerror="window.__xss=1"><script>window.__xss=2</script>';
    const author = await asNewMember(browser, '작성자');
    const trail = await shareTrail(author, { title: `<img src=x onerror="window.__xss=1"> ${unique()}`, description: payload });
    await author.context().close();
    await signInAs(page, payload.slice(0, 20));
    const review = await page.request.post(`/api/community/trails/${trail.id}/reviews`, { data: { rating: 5, content: payload } });
    expect(review.status()).toBe(201);

    await page.goto(`/community/trails/${trail.id}`);
    await expect(page.getByTestId('trail-title')).toHaveText(trail.title);
    await expect(page.getByTestId('trail-description')).toHaveText(payload);
    await expect(page.getByTestId('review-content')).toHaveText(payload);
    await page.goto(`/community?q=${encodeURIComponent(trail.title.slice(-12))}`);
    await expect(page.getByTestId('trail-card-title')).toHaveText(trail.title);
    expect(await page.evaluate(() => (window as unknown as { __xss?: number }).__xss)).toBeUndefined();
  });

  test('링크 공유는 커뮤니티 주소를 넘기고 공유 토큰을 쓰지 않는다', async ({ page, browser }) => {
    const author = await asNewMember(browser, '작성자');
    const trail = await shareTrail(author);
    await author.context().close();
    await page.addInitScript(() => {
      navigator.share = async (data) => {
        (window as unknown as { __shared?: ShareData }).__shared = data;
      };
    });
    await page.goto(`/community/trails/${trail.id}`);
    await page.getByRole('button', { name: '링크 공유' }).click();
    const shared = await page.evaluate(() => (window as unknown as { __shared?: ShareData }).__shared);
    expect(shared?.url).toMatch(new RegExp(`/community/trails/${trail.id}$`));
  });
});

test.describe('모바일 화면', () => {
  for (const width of [320, 390, 768]) {
    test(`${width}px에서 가로로 넘치지 않고 메뉴가 모두 보인다`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      await signInAs(page);
      const walk = await makeWalk(page);
      const longTitle = `긴제목`.repeat(25);
      const trail = await shareTrail(page, { title: longTitle, description: '가'.repeat(400), features: ['park', 'shade', 'flat', 'paved', 'waterside', 'forest', 'quiet', 'lit'], suitable_for: ['small', 'medium', 'large', 'senior'] }, { points: line(40, 37.55, 126.94) });
      await page.request.post(`/api/community/trails/${trail.id}/like`);

      for (const [path, name] of [
        ['/community', '목록'],
        [`/community/trails/${trail.id}`, '상세'],
        [`/community/share?walk=${walk.id}`, '공유'],
        [`/community/trails/${trail.id}/edit`, '수정'],
        ['/community/my', '관리'],
        ['/community/my?tab=reviews', '후기'],
      ]) {
        await page.goto(path);
        await page.waitForLoadState('networkidle');
        await expectNoSideScroll(page, width, `${name} ${width}px`);
      }

      if (width < 768) {
        await page.goto('/community');
        const nav = page.locator('nav.fixed');
        await expect(nav.getByRole('link')).toHaveCount(4);
        await expect(nav.getByRole('button', { name: '산책', exact: true })).toBeVisible();
        for (const link of await nav.getByRole('link').all()) {
          const box = await link.boundingBox();
          expect(box!.x).toBeGreaterThanOrEqual(0);
          expect(box!.x + box!.width).toBeLessThanOrEqual(width + 0.5);
          expect(box!.height).toBeGreaterThanOrEqual(44);
        }
        await nav.getByRole('link', { name: '커뮤니티', exact: true }).click();
        await expect(page).toHaveURL(/\/community$/);
        await nav.getByRole('link', { name: '마이' }).click();
        await expect(page).toHaveURL(/\/my$/);
      }
    });
  }

  test('누를 수 있는 주요 버튼의 높이가 충분하다', async ({ page, browser }) => {
    const author = await asNewMember(browser, '작성자');
    const trail = await shareTrail(author);
    await author.context().close();
    await page.goto(`/community/trails/${trail.id}`);
    for (const target of [page.getByTestId('like-button'), page.getByTestId('bookmark-button'), page.getByRole('button', { name: '이 산책길로 산책 시작' }), page.getByRole('link', { name: 'GPX 다운로드' })]) {
      const box = await target.boundingBox();
      expect(box!.height).toBeGreaterThanOrEqual(44);
    }
  });
});
