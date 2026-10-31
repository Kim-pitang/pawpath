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
    await expect(page.locator('path.nav-approach')).toHaveCount(1);
    await expect(progress).toHaveAttribute('aria-valuenow', reached);

    // 벗어나면 돌아갈 길을 다시 찾는다.
    await expect(page.getByText('돌아갈 길을 다시 찾았어요')).toBeVisible();

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

  test('위치 권한을 거부하면 이유를 안내하고 대안을 제공한다', async ({ page, request }) => {
    const { id } = await firstCourse(request);
    await page.addInitScript(() => {
      navigator.geolocation.watchPosition = (_success, error) => {
        setTimeout(() => error?.({ code: 1, PERMISSION_DENIED: 1, POSITION_UNAVAILABLE: 2, TIMEOUT: 3, message: 'denied' } as GeolocationPositionError), 50);
        return 1;
      };
    });
    await openNavigation(page, id);
    await expect(page.getByRole('alert')).toContainText('위치 권한');
    await expect(page.getByRole('button', { name: '시연용 위치로 걷기' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'GPS 없이 기록하기' })).toBeVisible();
  });

  test('시연 중 비가 내리면 복귀 경로와 대체 코스를 안내하고 복귀까지 이어진다', async ({ page, request }) => {
    const { id } = await firstCourse(request);
    await openNavigation(page, id);
    await page.getByRole('button', { name: '시연용 위치로 걷기' }).click();
    await expect(page.getByTestId('walk-progress')).toBeVisible();
    await expect(page.getByTestId('walk-environment')).toContainText('안전');
    // 출발점 25m 안에서 복귀를 고르면 바로 도착이 맞으므로, 코스를 조금 걸은 뒤 비를 내리게 한다.
    await expect(async () => {
      expect(Number(await page.getByTestId('walk-progress').getAttribute('aria-valuenow'))).toBeGreaterThanOrEqual(10);
    }).toPass({ timeout: 20000 });

    await page.getByRole('button', { name: '시연: 지금부터 비 내리기' }).click();
    const panel = page.getByTestId('alternative-panel');
    await expect(panel).toContainText('산책을 줄이는 편이 좋아요');
    await expect(panel).toContainText('시연용 시나리오');
    await expect(panel).toContainText('실시간 강수 감지가 아니니');

    await panel.getByRole('button', { name: /출발점으로 돌아가기/ }).click();
    await expect(page.getByTestId('return-summary')).toContainText('복귀 안내 중');
    await expect(page.locator('path.nav-approach')).toHaveCount(1);
    await expect(page.getByText('출발점에 도착했어요')).toBeVisible({ timeout: 20000 });

    await page.getByRole('button', { name: '피드백 남기기' }).click();
    await expect(page.getByRole('heading', { name: /어땠나요\?/ })).toBeVisible();
    await expect(page.getByText('시연용', { exact: true }).first()).toBeVisible();
  });

  test('복귀를 고르면 바로 도착으로 넘어가지 않고 복귀 안내가 이어진다', async ({ page, request }) => {
    const { id } = await firstCourse(request);
    await openNavigation(page, id);
    await page.getByRole('button', { name: '시연용 위치로 걷기' }).click();
    const progress = page.getByTestId('walk-progress');
    await expect(async () => {
      expect(Number(await progress.getAttribute('aria-valuenow'))).toBeGreaterThanOrEqual(20);
    }).toPass({ timeout: 20000 });

    await page.getByRole('button', { name: '시연: 지금부터 비 내리기' }).click();
    await page.getByTestId('alternative-panel').getByRole('button', { name: /출발점으로 돌아가기/ }).click();
    const summary = page.getByTestId('return-summary');
    await expect(summary).toContainText('복귀 안내 중');
    // 첫 화면만 스쳐 지나가는 경우를 걸러 낸다. 시연용 걷기는 0.5초에 20m를 가므로 1초 뒤에도 복귀 중이어야 한다.
    await page.waitForTimeout(1000);
    await expect(summary).toBeVisible();
    await expect(page.getByText('출발점에 도착했어요')).toBeHidden();
  });

  test('코스 없이 들어오면 추천으로 안내한다', async ({ page }) => {
    await page.goto('/navigate');
    await expect(page.getByRole('link', { name: '오늘의 추천 보기' })).toBeVisible();
  });
});

test.describe('추천과 리포트 고도화', () => {
  test('지도에서 코스 주변 시설을 검색하고 출처와 한계를 함께 보여 준다', async ({ page, request }) => {
    const { id } = await firstCourse(request);
    await page.goto(`/map?course=${id}`);
    const nearby = page.getByTestId('nearby-places');
    await expect(nearby).toContainText('코스 주변 시설');
    await expect(nearby).toContainText('OpenStreetMap');
    await expect(nearby).toContainText('없는 것처럼 보여도 실제로는 있을 수 있어요');
    await expect(nearby).toContainText('경로에서');
    await nearby.getByRole('button', { name: '공원' }).click();
    await expect(nearby).toContainText('망원정마당');
  });

  test('날씨 조건에 따라 위험 코스를 제외하고 이유를 보여 준다', async ({ page }) => {
    await page.goto('/recommend');
    await page.getByRole('button', { name: '폭염', exact: true }).click();
    await page.getByRole('button', { name: '시연용 폭염' }).click();
    await expect(page.getByRole('dialog', { name: '날씨 데이터 안내' })).toContainText('시연용 시나리오: 폭염');
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('course-card-1')).toBeVisible();
    const excluded = page.getByTestId('excluded-courses');
    await expect(excluded).toContainText('위험 조건으로 제외한 코스');
    await excluded.locator('summary').click();
    await expect(excluded).toContainText('그늘을 확인할 수 없어요');
    await expect(page.getByTestId('course-card-1').getByTestId('safety-panel')).toContainText(/위험|주의/);
  });

  test('선호 거리와 시간을 입력하면 저장되고 사용자 선호도에 반영된다', async ({ page, request }) => {
    const pets: { id: number; name: string }[] = await (await request.get('/api/pets')).json();
    const dubu = pets.find((pet) => pet.name === '두부')!;
    await page.goto(`/pets/${dubu.id}/edit`);
    await expect(page.getByLabel('견종')).toHaveValue('말티즈');
    await page.getByRole('group', { name: '선호 거리' }).getByRole('button', { name: '2km' }).click();
    await page.getByRole('group', { name: '선호 시간대' }).getByRole('button', { name: '오후' }).click();
    await page.getByRole('button', { name: '수정 완료' }).click();
    await expect(page.getByRole('heading', { name: '반려동물 프로필' })).toBeVisible();

    const saved = await (await request.get(`/api/pets/${dubu.id}`)).json();
    expect(saved.preferred_distance_km).toBe(2);
    expect(saved.preferred_time_bucket).toBe('afternoon');

    // 다음 테스트에 영향을 주지 않도록 되돌린다.
    await request.put(`/api/pets/${dubu.id}`, { data: { ...saved, preferred_distance_km: null, preferred_time_bucket: null } });
  });

  test('주간 리포트가 실제 산책만 집계하고 시연용 산책을 따로 알린다', async ({ page, request }) => {
    const pets: { id: number; name: string }[] = await (await request.get('/api/pets')).json();
    const pet = await (
      await request.post('/api/pets', {
        data: { name: '리포트견', breed: '믹스', age_years: 4, weight_kg: 10, size: 'medium', activity_level: 'medium', personality: 'curious', path_preference: 'new', heat_sensitivity: 'medium', novelty_reaction: 'calm' },
      })
    ).json();
    expect(pets.length).toBeGreaterThan(0);
    const courses: { id: number }[] = await (await request.get('/api/courses')).json();
    const walk = await (
      await request.post('/api/walks', { data: { pet_id: pet.id, course_id: courses[0].id, duration_min: 25, tracking_source: 'gps', distance_km: 1.5 } })
    ).json();
    await request.post('/api/feedback', { data: { walk_id: walk.id, walk_rating: 5, pet_rating: 4, difficulty: 'just_right', weather_rating: 5, would_revisit: true, memo: '' } });
    await request.post('/api/walks', { data: { pet_id: pet.id, course_id: courses[1].id, duration_min: 30, tracking_source: 'simulation' } });

    await page.addInitScript((id) => localStorage.setItem('pawpath.selectedPetId', String(id)), pet.id);
    await page.goto('/my');
    await expect(page.getByText('시연용 산책 1건은 아래 활동 통계에서 제외했어요')).toBeVisible();
    await page.getByRole('link', { name: '주간 활동 리포트 보기' }).click();
    await expect(page.getByRole('heading', { name: '리포트견의 주간 리포트' })).toBeVisible();
    await expect(page.getByText('시연용 산책 1건은 통계에서 제외했어요')).toBeVisible();
    await expect(page.getByText('1번').first()).toBeVisible();
    await expect(page.getByText('1.5km').first()).toBeVisible();
    await expect(page.getByRole('list', { name: '요일별 산책 거리' })).toBeVisible();
    await expect(page.getByRole('list', { name: '선호 코스' })).toBeVisible();

    await page.getByRole('button', { name: '지난주' }).click();
    await expect(page.getByText('이 주에는 실제 산책 기록이 없어요')).toBeVisible();
  });
});
