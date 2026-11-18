import { defineConfig, devices } from '@playwright/test'

// The end-to-end smoke test (`npm run e2e`): the spec starts its own backend and Graph stub.
export default defineConfig({
  testDir: 'e2e',
  timeout: 120_000,
  forbidOnly: !!process.env.CI,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: { trace: 'retain-on-failure', timezoneId: 'UTC' }, // the studio runs with TIMEZONE=UTC
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
})
