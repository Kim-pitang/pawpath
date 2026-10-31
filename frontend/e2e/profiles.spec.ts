import { expect, test, type Page } from '@playwright/test';

const PASSWORD = 'walk-with-dubu-1';
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
const POINTS = Array.from({ length: 4 }, (_, index) => ({ latitude: 37.55 + index * 0.0003, longitude: 126.91, segment: 0 }));
const newId = () => `fam${Date.now()}${Math.floor(Math.random() * 1000)}`;

/** 이메일로 가입해 대표 프로필을 정하고 홈으로 들어간다. */
async function signUpFamily(page: Page, email: string) {
  await page.goto('/login');
  await page.getByRole('link', { name: '로그인하지 않고 시연 보호자로 둘러보기' }).waitFor();
  await page.getByRole('button', { name: '회원가입' }).click();
  await page.getByLabel('아이디 또는 이메일').fill(email);
  await page.getByLabel('비밀번호').fill(PASSWORD);
  await page.getByLabel('이름', { exact: true }).fill('우리 가족');
  await page.getByRole('button', { name: '가입하고 시작하기' }).click();

  await expect(page.getByRole('heading', { name: '내 프로필을 정해 주세요' })).toBeVisible();
  await page.getByLabel('프로필 이름').fill('엄마');
  await page.getByRole('button', { name: '하트' }).click();
  await page.getByRole('button', { name: '시작하기', exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByTestId('current-profile')).toContainText('엄마');
}

async function addProfile(page: Page, name: string, avatar: string) {
  await page.getByRole('link', { name: '프로필 추가' }).click();
  await expect(page.getByRole('heading', { name: '프로필 추가' })).toBeVisible();
  await page.getByLabel('프로필 이름').fill(name);
  await page.getByRole('button', { name: avatar }).click();
  await page.getByRole('button', { name: '프로필 만들기' }).click();
  await expect(page.getByRole('heading', { name: '누구의 산책을 기록할까요?' })).toBeVisible();
}

test.describe('가족 프로필', () => {
  test('이메일로 가입하고 프로필을 더 만들어 넷플릭스처럼 고르고 바꾼다', async ({ page }) => {
    const email = `${newId()}@example.com`;
    await signUpFamily(page, email);
    expect((await page.request.post('/api/pets', { data: PET })).status()).toBe(201);
    // 엄마 프로필로 산책길을 하나 남긴다.
    expect((await page.request.post('/api/my-walks', { data: { title: '엄마 아침 길', points: POINTS } })).status()).toBe(201);

    await page.goto('/profiles');
    await addProfile(page, '아빠', '달');
    await expect(page.getByTestId('profile-count')).toHaveText('2/5');

    // 로그아웃 후 다시 로그인하면 누구의 산책인지 먼저 고른다.
    await page.getByRole('button', { name: '로그아웃' }).click();
    await expect(page).toHaveURL(/\/login$/);
    await page.getByLabel('아이디 또는 이메일').fill(email.toUpperCase());
    await page.getByLabel('비밀번호').fill(PASSWORD);
    await page.getByRole('button', { name: '로그인하기' }).click();
    await expect(page).toHaveURL(/\/profiles$/);
    await expect(page.getByRole('heading', { name: '누구의 산책을 기록할까요?' })).toBeVisible();
    await expect(page.getByRole('button', { name: '엄마 (대표)' })).toBeVisible();

    await page.getByRole('button', { name: '아빠', exact: true }).click();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByTestId('current-profile')).toContainText('아빠');
    // 반려동물은 가족 공용이라 아빠 프로필에서도 보인다.
    await expect(page.locator('header').getByRole('link', { name: '콩' })).toBeVisible();

    // 아빠의 산책길 목록에는 엄마의 길이 없고, 가족 전체로 바꾸면 누가 만들었는지 함께 보인다.
    await page.goto('/my-walks');
    await expect(page.getByText('아직 저장한 산책길이 없어요')).toBeVisible();
    await page.getByRole('button', { name: '가족 전체' }).click();
    await expect(page.getByTestId('saved-walk-card')).toHaveCount(1);
    await expect(page.getByTestId('saved-walk-owner')).toHaveText('엄마');
    await page.getByTestId('saved-walk-card').click();
    await expect(page.getByText('엄마님이 만든 산책길이에요')).toBeVisible();
    await expect(page.getByRole('button', { name: '수정' })).toHaveCount(0);
    await expect(page.getByRole('link', { name: 'GPX 다운로드' })).toBeVisible();

    // 상단 메뉴로 바로 엄마로 바꾸면 보던 화면이 엄마 기준으로 다시 그려진다.
    await page.getByTestId('current-profile').click();
    await page.getByRole('menuitem', { name: '엄마' }).click();
    await expect(page.getByTestId('current-profile')).toContainText('엄마');
    await expect(page.getByText('엄마님이 만든 산책길이에요')).toHaveCount(0);
    await expect(page.getByRole('button', { name: '수정' })).toBeVisible();
  });

  test('프로필을 고치고 지우며, 대표 프로필은 지울 수 없다', async ({ page }) => {
    await signUpFamily(page, `${newId()}@example.com`);
    await page.goto('/profiles');
    await addProfile(page, '지우', '별');

    await page.getByRole('button', { name: '프로필 관리' }).click();
    await expect(page.getByRole('heading', { name: '프로필 관리' })).toBeVisible();
    await page.getByRole('link', { name: '엄마 프로필 고치기' }).click();
    await expect(page.getByText('대표 프로필은 지울 수 없어요')).toBeVisible();
    await expect(page.getByRole('button', { name: '프로필 삭제' })).toBeDisabled();
    await page.getByRole('link', { name: '취소' }).click();

    await page.getByRole('link', { name: '지우 프로필 고치기' }).click();
    await page.getByLabel('프로필 이름').fill('지우랑');
    await page.getByRole('button', { name: '저장하기' }).click();
    await expect(page.getByRole('link', { name: '지우랑 프로필 고치기' })).toBeVisible();

    await page.getByRole('link', { name: '지우랑 프로필 고치기' }).click();
    page.once('dialog', (dialog) => dialog.accept());
    await page.getByRole('button', { name: '프로필 삭제' }).click();
    await expect(page.getByRole('heading', { name: '프로필 관리' })).toBeVisible();
    await expect(page.getByRole('link', { name: '지우랑 프로필 고치기' })).toHaveCount(0);
    await expect(page.getByTestId('profile-count')).toHaveText('1/5');
  });

  test('다섯 개를 채우면 더 만들 수 없다고 알린다', async ({ page }) => {
    await signUpFamily(page, `${newId()}@example.com`);
    for (const name of ['아빠', '할머니', '지우', '민우']) {
      expect((await page.request.post('/api/profiles', { data: { name } })).status()).toBe(201);
    }
    expect((await page.request.post('/api/profiles', { data: { name: '여섯째' } })).status()).toBe(409);
    await page.goto('/profiles');
    await expect(page.getByRole('list', { name: '프로필 목록' }).getByRole('listitem')).toHaveCount(5);
    await expect(page.getByRole('link', { name: '프로필 추가' })).toHaveCount(0);
    await expect(page.getByText('5개까지 만들 수 있어요')).toBeVisible();
  });

  test('가족 산책 기록에서 구성원별 통계를 본다', async ({ page }) => {
    await signUpFamily(page, `${newId()}@example.com`);
    const pet = await (await page.request.post('/api/pets', { data: PET })).json();
    const courseId = (await (await page.request.get('/api/courses')).json())[0].id;
    const walk = () => page.request.post('/api/walks', { data: { pet_id: pet.id, course_id: courseId, duration_min: 20 } });
    expect((await walk()).status()).toBe(201);
    const dad = await (await page.request.post('/api/profiles', { data: { name: '아빠', avatar_key: 'moon' } })).json();
    expect((await page.request.post(`/api/profiles/${dad.id}/select`)).status()).toBe(200);
    expect((await walk()).status()).toBe(201);
    expect((await walk()).status()).toBe(201);

    await page.goto('/my');
    await page.getByRole('navigation', { name: '가족 계정 메뉴' }).getByRole('link', { name: '가족 산책 기록' }).click();
    await expect(page.getByRole('heading', { name: '가족 산책 기록' })).toBeVisible();
    await expect(page.getByTestId('family-totals')).toContainText('3번');
    const members = page.getByTestId('family-member');
    await expect(members).toHaveCount(2);
    await expect(members.filter({ hasText: '엄마' })).toContainText('산책 1번');
    await expect(members.filter({ hasText: '아빠' })).toContainText('산책 2번');
    await expect(page.getByRole('list', { name: '최근 가족 산책' }).getByRole('listitem')).toHaveCount(3);
  });
});

test.describe('프로필을 고르기 전과 바꿀 때', () => {
  /** 프로필 둘을 만들고 다시 로그인해, 아직 프로필을 고르지 않은 세션을 만든다. */
  async function loginWithTwoProfiles(page: Page) {
    const email = `${newId()}@example.com`;
    expect((await page.request.post('/api/auth/signup', { data: { email, password: PASSWORD, name: '엄마' } })).status()).toBe(201);
    expect((await page.request.post('/api/profiles', { data: { name: '아빠', avatar_key: 'moon' } })).status()).toBe(201);
    await page.request.post('/api/auth/logout');
    const account = await (await page.request.post('/api/auth/login', { data: { login_id: email, password: PASSWORD } })).json();
    expect(account.profile_required).toBe(true);
  }

  test('메뉴 없는 기록 화면도 프로필을 고른 뒤 돌아온다', async ({ page }) => {
    await loginWithTwoProfiles(page);
    await page.goto('/record');
    await expect(page).toHaveURL(/\/profiles$/);
    await page.getByRole('button', { name: '아빠', exact: true }).click();
    await expect(page).toHaveURL(/\/record$/);
  });

  test('메뉴 없는 길 안내 화면도 프로필을 먼저 고른다', async ({ page }) => {
    await loginWithTwoProfiles(page);
    await page.goto('/navigate?course=1');
    await expect(page).toHaveURL(/\/profiles$/);
    await page.getByRole('button', { name: '엄마 (대표)' }).click();
    await expect(page).toHaveURL(/\/navigate\?course=1$/);
  });

  test('저장하지 않은 기록이 있으면 프로필을 바꾸기 전에 묻고, 바꾸면 지운다', async ({ page }) => {
    await signUpFamily(page, `${newId()}@example.com`);
    expect((await page.request.post('/api/profiles', { data: { name: '아빠', avatar_key: 'moon' } })).status()).toBe(201);
    await page.reload();
    await expect(page.getByTestId('current-profile')).toContainText('엄마');
    await page.evaluate(() => localStorage.setItem('pawpath.recording.v1', JSON.stringify({ id: 'unsaved', points: [], status: 'paused' })));
    const draft = () => page.evaluate(() => localStorage.getItem('pawpath.recording.v1'));

    page.once('dialog', (dialog) => dialog.dismiss());
    await page.getByTestId('current-profile').click();
    await page.getByRole('menuitem', { name: '아빠' }).click();
    await expect(page.getByTestId('current-profile')).toContainText('엄마');
    expect(await draft()).toContain('unsaved');

    // 취소하면 메뉴가 닫히므로 다시 연다.
    page.once('dialog', (dialog) => dialog.accept());
    await page.getByTestId('current-profile').click();
    await page.getByRole('menuitem', { name: '아빠' }).click();
    await expect(page.getByTestId('current-profile')).toContainText('아빠');
    expect(await draft()).toBeNull();
  });
});
