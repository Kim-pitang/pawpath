import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { defineConfig, devices } from '@playwright/test';

const API_PORT = 8010;
const WEB_PORT = 5183;
const dbDir = mkdtempSync(join(tmpdir(), 'pawpath-e2e-'));

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  workers: 1,
  fullyParallel: false,
  reporter: 'list',
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'mobile', use: { ...devices['Pixel 7'] } }],
  webServer: [
    {
      // 실제 외부 날씨에 흔들리지 않도록 임시 DB와 Mock 날씨로 띄운다.
      command: `uv run uvicorn app.main:app --port ${API_PORT}`,
      cwd: '../backend',
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      reuseExistingServer: false,
      env: {
        DATABASE_URL: `sqlite:///${dbDir}/e2e.db`,
        WEATHER_PROVIDER: 'mock',
        SEED_DEMO_PET: 'true',
        ROUTING_PROVIDER: 'none',
        // 개발자의 .env 설정과 무관하게 같은 결과가 나오도록 고정한다. 환경변수가 .env보다 우선한다.
        LLM_PROVIDER: 'none',
        RECOMMENDER_WEIGHTS: '{}',
        SERVICE_AREA: 'mangwon',
        AUTH_REQUIRED: 'false',
        ENVIRONMENT_PROVIDER: 'none',
        // 가짜 Google 클라이언트. E2E는 Google 화면으로 보내는 데까지만 확인하고 실제 Google을 부르지 않는다.
        GOOGLE_CLIENT_ID: 'e2e-client.apps.googleusercontent.com',
        GOOGLE_CLIENT_SECRET: 'e2e-google-secret',
        GOOGLE_REDIRECT_URI: `http://127.0.0.1:${WEB_PORT}/api/auth/google/callback`,
        BACKUP_ENABLED: 'false',
        BACKUP_DIR: `${dbDir}/backups`,
      },
    },
    {
      command: 'npm run dev -- --host 127.0.0.1',
      url: `http://127.0.0.1:${WEB_PORT}`,
      reuseExistingServer: false,
      env: {
        PAWPATH_WEB_PORT: String(WEB_PORT),
        PAWPATH_API_TARGET: `http://127.0.0.1:${API_PORT}`,
      },
    },
  ],
});
