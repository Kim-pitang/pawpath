import { expect, test, type Page } from '@playwright/test';

const EXPECTED_SENTENCE = '낯선 길을 싫어하는 두부를 위해 익숙한 공원 코스를 골랐어요. 비가 오기 전 짧게 다녀올 수 있어요.';

async function chooseScenario(page: Page, name: string) {
  await page.goto('/recommend');
  await page.getByRole('button', { name, exact: true }).click();
}

test.describe.configure({ mode: 'serial' });

test('메인 화면이 오늘의 산책 시간과 코스를 먼저 보여 준다', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('link', { name: 'mungo 홈' })).toBeVisible();
  await expect(page.getByRole('heading', { level: 1 })).toContainText('두부 산책은');
  await expect(page.getByRole('link', { name: '두부 프로필 보기: 말티즈, 5세, 4.2kg, 소심함' })).toBeVisible();
  await expect(page.getByText('16시 ~ 20시')).toBeVisible();
  await expect(page.getByRole('group', { name: '시간대별 산책 점수' })).toBeVisible();
  await page.getByRole('button', { name: '모의 날씨' }).click();
  await expect(page.getByRole('dialog', { name: '날씨 데이터 안내' })).toContainText('모의 날씨 데이터를 사용 중이에요.');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('link', { name: '이 코스로 산책' })).toBeVisible();
  await expect(page.getByRole('link', { name: '다른 코스와 추천 근거 보기' })).toBeVisible();
});

test('최종 검증 시나리오: 추천, 산책, 5점 피드백, 다음 추천 반영', async ({ page }) => {
  // 1~5. 날씨, 코스, 점수, TOP 3, 추천 이유
  await chooseScenario(page, '곧 비');
  await page.getByRole('button', { name: '시연용 곧 비' }).click();
  await expect(page.getByRole('dialog', { name: '날씨 데이터 안내' })).toContainText('시연용 시나리오: 곧 비가 오는 날');
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('course-card-1')).toBeVisible();
  await expect(page.getByTestId('course-card-3')).toBeVisible();
  await expect(page.getByTestId('course-card-1').getByTestId('reason-summary')).toHaveText(EXPECTED_SENTENCE);

  const firstCard = page.getByTestId('course-card-1');
  await firstCard.getByRole('button', { name: '점수 근거 보기' }).click();
  await expect(firstCard.getByLabel('항목별 점수').getByRole('listitem')).toHaveCount(6);
  await expect(firstCard.getByText('과거 만족도', { exact: true })).toBeVisible();
  await expect(firstCard.getByText('사용자 선호도', { exact: true })).toBeVisible();

  // 안전 평가: 출처를 구분하고, 데이터가 없는 항목은 확인 불가로 표시한다.
  const safety = firstCard.getByTestId('safety-panel');
  await expect(safety).toContainText('안전');
  await expect(safety).toContainText('확인 불가');
  await safety.getByRole('button', { name: '항목별 근거' }).click();
  await expect(safety.getByLabel('안전 평가 항목').getByRole('listitem').first()).toBeVisible();
  await expect(safety).toContainText('모의');
  await expect(safety).toContainText('보장하지 않아요');

  // 2위 코스로 산책해서 순위 변화까지 확인한다.
  const secondCard = page.getByTestId('course-card-2');
  const secondName = (await secondCard.getByRole('heading').textContent())!;
  await secondCard.getByRole('link', { name: '이 코스로 산책' }).click();
  await page.getByRole('link', { name: 'GPS 없이 기록하기' }).click();

  // 6. 산책 완료
  await expect(page.getByLabel('다녀온 코스')).toHaveValue(/\d+/);
  await page.getByRole('button', { name: '산책 완료' }).click();

  // 7. 만족도 5점 피드백
  await expect(page.getByText(`${secondName}, 어땠나요?`)).toBeVisible();
  await page.getByRole('button', { name: '산책 만족도 5점' }).click();
  await page.getByRole('button', { name: '두부 만족도 5점' }).click();
  await page.getByRole('button', { name: '딱 좋았어요' }).click();
  await page.getByRole('button', { name: '날씨 만족도 5점' }).click();
  await page.getByRole('button', { name: '또 갈래요' }).click();
  await page.getByPlaceholder('오늘 산책에서 기억하고 싶은 점').fill('꼬리를 흔들며 잘 걸었어요');
  await page.getByRole('button', { name: '피드백 남기기' }).click();
  await expect(page.getByTestId('affinity-change')).toContainText('50점에서');

  // 8. 다음 추천에 반영
  await page.getByRole('button', { name: '달라진 추천 보기' }).click();
  await expect(page.getByTestId('course-card-1').getByRole('heading')).toHaveText(secondName);
  await expect(page.getByTestId('course-card-1').getByText('학습 전보다 1계단 상승')).toBeVisible();
  const updated = page.getByRole('article').filter({ hasText: secondName });
  await expect(updated.getByText(/학습 효과 \+/)).toBeVisible();
  await expect(updated.getByTestId('reason-summary')).toContainText('지난번 만족도가 높았던');

  // 마이페이지 분석
  await page.getByRole('navigation', { name: '주요 메뉴' }).getByRole('link', { name: '마이' }).click();
  await expect(page.getByText('두부의 산책 리포트')).toBeVisible();
  await expect(page.getByText('1번').first()).toBeVisible();
  await expect(page.getByLabel('코스별 선호도').getByText(secondName)).toBeVisible();
  await expect(page.getByText('두부의 취향 분석')).toBeVisible();
  await expect(page.getByText('추천 결과 변화')).toBeVisible();
  await expect(page.getByRole('img', { name: '추천 회차별 코스 점수 변화' })).toBeVisible();
});

test('지도에 코스 경로와 시설이 표시된다', async ({ page }) => {
  await page.goto('/map');
  await expect(page.getByTestId('course-map')).toBeVisible();
  await expect(page.locator('path.course-line')).toHaveCount(10);
  await page.getByRole('list', { name: '코스 목록' }).getByRole('button').first().click();
  await expect(page.getByTestId('selected-course-name')).toBeVisible();
  await expect(page.locator('.pp-marker').first()).toBeVisible();
  await expect(page.getByText(/OpenStreetMap 기준/)).toBeVisible();
});

test('반려동물을 등록하고 수정하면 추천이 달라진다', async ({ page }) => {
  await page.goto('/pets/new');
  await page.getByLabel('이름').fill('바람');
  await page.getByLabel('견종').fill('보더콜리');
  await page.getByLabel('나이 (세)').fill('3');
  await page.getByLabel('체중 (kg)').fill('18');
  await page.getByRole('button', { name: '중형견' }).click();
  await page.getByRole('group', { name: '평소 활동량' }).getByRole('button', { name: '높음' }).click();
  await page.getByRole('button', { name: '활발함' }).click();
  await page.getByRole('button', { name: '새로운 길 선호' }).click();
  await page.getByRole('group', { name: '더위 민감도' }).getByRole('button', { name: '보통' }).click();
  await page.getByRole('button', { name: '금방 적응해요' }).click();
  await page.getByRole('button', { name: '등록하기' }).click();

  await expect(page.getByRole('heading', { name: '바람' })).toBeVisible();

  await page.getByRole('link', { name: '바람 프로필 수정' }).click();
  await expect(page.getByLabel('견종')).toHaveValue('보더콜리');
  await page.getByLabel('체중 (kg)').fill('19.5');
  await page.getByRole('button', { name: '수정 완료' }).click();
  await expect(page.getByText('보더콜리 · 3세 · 19.5kg')).toBeVisible();

  await chooseScenario(page, '실제 날씨');
  await expect(page.getByText('바람의 오늘의 산책각')).toBeVisible();
  await expect(page.getByTestId('course-card-1').getByTestId('reason-summary')).toContainText('바람');
  await expect(page.getByTestId('course-card-1').getByTestId('reason-summary')).not.toContainText('낯선 길을 싫어하는');
});

test('보호자 일정을 바꾸면 추천 시간이 그 안으로 들어온다', async ({ page }) => {
  await page.goto('/schedule');
  await page.getByRole('button', { name: '16시 ~ 20시 삭제' }).click();
  await page.getByRole('button', { name: /오전/ }).click();
  await page.getByRole('button', { name: '저장하기' }).click();
  await expect(page.getByText('7시 ~ 11시')).toBeVisible();

  await page.goto('/recommend');
  await expect(page.getByTestId('course-card-1')).toBeVisible();
  const columns = await page.getByRole('list', { name: '시간대별 산책 점수' }).getByRole('listitem').all();
  expect(columns.length).toBeGreaterThan(0);
  for (const column of columns) {
    const hour = Number((await column.getAttribute('aria-label'))!.match(/(\d+)시/)![1]);
    expect(hour).toBeGreaterThanOrEqual(7);
    expect(hour).toBeLessThan(11);
  }

  // 다음 테스트에 영향을 주지 않도록 일정을 되돌린다.
  await page.goto('/schedule');
  await page.getByRole('button', { name: '7시 ~ 11시 삭제' }).click();
  await page.getByLabel('시작 시각').selectOption('16');
  await page.getByLabel('끝나는 시각').selectOption('20');
  await page.getByRole('button', { name: '직접 입력한 시간 추가' }).click();
  await page.getByRole('button', { name: '저장하기' }).click();
  await expect(page.getByText('16시 ~ 20시')).toBeVisible();
});

test('폭우 시나리오에서는 코스 대신 실내 대안을 안내한다', async ({ page }) => {
  await page.goto('/pets');
  await page.getByRole('button', { name: '이 아이로 추천받기' }).first().click();
  await chooseScenario(page, '폭우');
  await expect(page.getByText('오늘은 실내 놀이를 추천해요')).toBeVisible();
  await expect(page.getByText(/노즈워크/)).toBeVisible();
  await expect(page.getByTestId('course-card-1')).toHaveCount(0);
});
