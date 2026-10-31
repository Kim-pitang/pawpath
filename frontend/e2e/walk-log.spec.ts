import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

// 다른 테스트의 학습 상태를 건드리지 않도록 테스트마다 새 반려동물을 만든다.
const PET = {
  name: '보리',
  breed: '푸들',
  age_years: 2,
  weight_kg: 5,
  size: 'small',
  activity_level: 'medium',
  personality: 'active',
  path_preference: 'new',
  heat_sensitivity: 'medium',
  novelty_reaction: 'calm',
};

test.use({ timezoneId: 'Asia/Seoul' });

const pad = (value: number) => String(value).padStart(2, '0');
const inputValue = (date: Date) =>
  `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;

async function openWithNewPet(page: Page, request: APIRequestContext) {
  const pet = await (await request.post('/api/pets', { data: PET })).json();
  const courses = await (await request.get('/api/courses')).json();
  await page.addInitScript((id) => localStorage.setItem('pawpath.selectedPetId', String(id)), pet.id);
  return { petId: pet.id as number, courseId: courses[0].id as number };
}

test('다른 시각에 다녀온 산책을 기록하고, 남은 피드백 항목을 알려 준다', async ({ page, request }) => {
  const { petId } = await openWithNewPet(page, request);
  await page.goto('/walk');
  await expect(page.getByRole('link', { name: '보리' })).toBeVisible();

  await page.getByLabel('다녀온 코스').selectOption({ index: 1 });
  await page.getByRole('button', { name: '다른 시각에 다녀왔어요' }).click();
  // 처음 열면 방금 끝난 산책의 출발 시각이 채워져 있다.
  await expect(page.getByLabel('출발 시각')).not.toHaveValue('');

  await page.getByLabel('출발 시각').fill(inputValue(new Date(Date.now() + 2 * 3600_000)));
  await expect(page.getByText('아직 끝나지 않은 시각이에요')).toBeVisible();
  await expect(page.getByRole('button', { name: '산책 완료' })).toBeDisabled();

  const yesterday = new Date(Date.now() - 86_400_000);
  yesterday.setHours(7, 30);
  await page.getByLabel('출발 시각').fill(inputValue(yesterday));
  await expect(page.getByText('아직 끝나지 않은 시각이에요')).toBeHidden();
  await page.getByRole('button', { name: '산책 완료' }).click();

  await expect(page.getByTestId('feedback-walk-time')).toHaveText(/^어제 오전 7:30 출발 · \d+분$/);
  const submit = page.getByRole('button', { name: '피드백 남기기' });
  await page.getByRole('button', { name: '산책 만족도 4점' }).click();
  await expect(submit).toBeDisabled();
  await expect(page.getByText('아직 고르지 않았어요: 보리 만족도, 난이도, 날씨 만족도, 또 갈지')).toBeVisible();

  await page.getByRole('button', { name: '보리 만족도 5점' }).click();
  await page.getByRole('button', { name: '딱 좋았어요' }).click();
  await page.getByRole('button', { name: '날씨 만족도 4점' }).click();
  await page.getByRole('button', { name: '또 갈래요' }).click();
  await expect(page.getByText(/아직 고르지 않았어요/)).toBeHidden();
  await submit.click();
  await expect(page.getByTestId('affinity-change')).toBeVisible();

  await expect(page.getByRole('list', { name: '지난 산책' }).getByRole('listitem').first()).toContainText('어제 오전 7:30');
  const walks = await (await request.get(`/api/walks?pet_id=${petId}`)).json();
  expect(walks[0].started_at).toBe(`${inputValue(yesterday)}:00`);
});

test('잘못 남긴 산책은 지울 수 있고, 피드백 대기 목록은 최근 3개만 먼저 보인다', async ({ page, request }) => {
  const { petId, courseId } = await openWithNewPet(page, request);
  for (const daysAgo of [1, 2, 3, 4]) {
    const started = new Date(Date.now() - daysAgo * 86_400_000);
    started.setHours(8, 0);
    await request.post('/api/walks', { data: { pet_id: petId, course_id: courseId, duration_min: 20, started_at: `${inputValue(started)}:00` } });
  }
  await page.goto('/walk');

  const pending = page.getByRole('list', { name: '피드백을 기다리는 산책' }).getByRole('listitem');
  await expect(pending).toHaveCount(3);
  await page.getByRole('button', { name: '1개 더 보기' }).click();
  await expect(pending).toHaveCount(4);

  // 확인 창에서 취소하면 지우지 않는다.
  page.once('dialog', (dialog) => dialog.dismiss());
  await pending.first().getByRole('button', { name: /기록 지우기/ }).click();
  await expect(pending).toHaveCount(4);

  page.once('dialog', (dialog) => dialog.accept());
  await pending.first().getByRole('button', { name: /기록 지우기/ }).click();
  await expect(pending).toHaveCount(3);

  // 피드백 폼에서도 바로 지울 수 있다.
  await pending.first().getByRole('button', { name: /피드백 남기기/ }).click();
  await expect(page.getByRole('heading', { name: /어땠나요\?/ })).toBeVisible();
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: '잘못 기록했어요. 이 기록 지우기' }).click();
  await expect(page.getByRole('heading', { name: /어땠나요\?/ })).toBeHidden();
  await expect(pending).toHaveCount(2);

  const walks = await (await request.get(`/api/walks?pet_id=${petId}`)).json();
  expect(walks).toHaveLength(2);
});
