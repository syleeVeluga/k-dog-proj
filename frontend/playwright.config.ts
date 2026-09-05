import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1,
  timeout: 45000,
  use: { baseURL: 'http://127.0.0.1:8765', viewport: { width: 1440, height: 1000 }, screenshot: 'only-on-failure' },
  webServer: {
    command: 'uv run --locked python -X utf8 -m tests.browser_server',
    cwd: '../backend',
    url: 'http://127.0.0.1:8765/',
    reuseExistingServer: false,
    timeout: 30000,
  },
});
