// @ts-check
const { defineConfig, devices } = require('@playwright/test');

/**
 * Playwright Configuration for iSamples Cesium Tutorial Tests
 *
 * @see https://playwright.dev/docs/test-configuration
 */
module.exports = defineConfig({
  testDir: './tests/playwright',

  /* Run tests in files in parallel */
  fullyParallel: false,

  /* Fail the build on CI if you accidentally left test.only in the source code. */
  forbidOnly: !!process.env.CI,

  /* Retry on CI only */
  retries: process.env.CI ? 2 : 0,

  /* Opt out of parallel tests on CI. */
  workers: process.env.CI ? 1 : undefined,

  /* Reporter to use. See https://playwright.dev/docs/test-reporters */
  reporter: [
    ['html', { outputFolder: 'tests/playwright-report' }],
    ['list']
  ],

  /* Shared settings for all the projects below. See https://playwright.dev/docs/api/class-testoptions. */
  use: {
    /* Base URL to use in actions like `await page.goto('/')`. */
    baseURL: process.env.TEST_URL || 'http://localhost:5860',

    /* Collect trace when retrying the failed test. See https://playwright.dev/docs/trace-viewer */
    trace: 'on-first-retry',

    /* Screenshot on failure */
    screenshot: 'only-on-failure',

    /* Video on failure */
    video: 'retain-on-failure',

    /* Extend timeout for slow remote parquet loading */
    actionTimeout: 15000,
    navigationTimeout: 60000,
  },

  /* Configure projects for major browsers */
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },

    // #313 P6: narrow, targeted Firefox coverage — scoped to ONLY the
    // facetIndexReady pending/failed race spec (tests/playwright/
    // facet-index-meta-pending.spec.js). This is NOT "enable Firefox
    // broadly" (Codex's review explicitly warned that would add flake risk
    // — Cesium/DuckDB-WASM under Firefox/WebKit — without catching this
    // class of bug, since the existing smoke suite avoids data-dependent
    // facet-count assertions). Firefox's background-tab/network throttling
    // behavior is exactly what the #313 findings doc flags as the
    // Firefox-specific amplifier of the boot race this spec exercises.
    {
      name: 'firefox-facet-index-meta',
      use: { ...devices['Desktop Firefox'] },
      testMatch: /facet-index-meta-pending\.spec\.js/,
    },

    // Uncomment to broadly enable other browsers
    // {
    //   name: 'firefox',
    //   use: { ...devices['Desktop Firefox'] },
    // },
    //
    // {
    //   name: 'webkit',
    //   use: { ...devices['Desktop Safari'] },
    // },

    /* Test against mobile viewports. */
    // {
    //   name: 'Mobile Chrome',
    //   use: { ...devices['Pixel 5'] },
    // },
    // {
    //   name: 'Mobile Safari',
    //   use: { ...devices['iPhone 12'] },
    // },
  ],

  /* Run your local dev server before starting the tests */
  // webServer: {
  //   command: 'quarto preview tutorials/parquet_cesium.qmd --no-browser',
  //   url: 'http://localhost:5860',
  //   timeout: 120 * 1000,
  //   reuseExistingServer: !process.env.CI,
  // },
});
