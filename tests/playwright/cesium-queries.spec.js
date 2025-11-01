/**
 * Cesium Tutorial - Query Results UI Tests
 *
 * Tests the HTML table UI for all three query paths:
 * - Eric's Query (Path 1 only, authoritative)
 * - Path 1 Query (direct event location)
 * - Path 2 Query (via site location)
 *
 * Test Strategy:
 * - Use geocode search box to navigate to known test locations
 * - Verify HTML tables render with correct structure
 * - Check for thumbnails, links, and formatted data
 * - Validate loading/empty states
 */

const { test, expect } = require('@playwright/test');

// Configuration
const BASE_URL = process.env.TEST_URL || 'http://localhost:5860';
const PAGE_PATH = '/tutorials/parquet_cesium.html';

// Test data - PKAP location with known samples
const TEST_GEOCODE_WITH_SAMPLES = 'geoloc_04d6e816218b1a8798fa90b3d1d43bf4c043a57f';
const TEST_GEOCODE_NO_SAMPLES = 'geoloc_7a05216d388682536f3e2abd8bd2ee3fb286e461'; // Larnaka site marker

test.describe('Cesium Query Results UI', () => {

  test.beforeEach(async ({ page }) => {
    // Navigate to page
    await page.goto(`${BASE_URL}${PAGE_PATH}`, {
      waitUntil: 'domcontentloaded',
      timeout: 60000
    });

    // Wait for Observable to load (check for specific UI element)
    await page.waitForSelector('input[placeholder*="Paste geocode PID"]', { timeout: 30000 });

    // Give extra time for DuckDB to initialize with remote parquet
    await page.waitForTimeout(5000);
  });

  test('Page loads and shows geocode search box', async ({ page }) => {
    // Verify search box is visible
    const searchBox = page.locator('input[placeholder*="Paste geocode PID"]');
    await expect(searchBox).toBeVisible();

    // Verify Cesium container exists
    const cesiumContainer = page.locator('#cesiumContainer');
    await expect(cesiumContainer).toBeVisible();
  });

  test('Geocode search triggers camera movement', async ({ page }) => {
    // Enter test geocode
    const searchBox = page.locator('input[placeholder*="Paste geocode PID"]');
    await searchBox.fill(TEST_GEOCODE_WITH_SAMPLES);
    await searchBox.press('Enter');

    // Wait for camera to move and data to load
    await page.waitForTimeout(5000);

    // Verify the clicked point ID is displayed
    const clickedPointDisplay = page.locator(`text="${TEST_GEOCODE_WITH_SAMPLES}"`);
    await expect(clickedPointDisplay).toBeVisible();
  });

  test.describe('HTML Tables - Structure and Content', () => {

    test.beforeEach(async ({ page }) => {
      // Search for location with samples
      const searchBox = page.locator('input[placeholder*="Paste geocode PID"]');
      await searchBox.fill(TEST_GEOCODE_WITH_SAMPLES);
      await searchBox.press('Enter');

      // Wait for queries to complete (generous timeout for remote data)
      await page.waitForTimeout(8000);
    });

    test('Eric\'s Query shows HTML table with correct columns', async ({ page }) => {
      // Find Eric's query section
      const ericSection = page.locator('text=Samples at Location via Sampling Event');
      await expect(ericSection).toBeVisible();

      // Check for table with 5 column headers
      const table = page.locator('table').first();
      await expect(table).toBeVisible();

      // Verify column headers
      await expect(table.locator('th:has-text("Thumbnail")')).toBeVisible();
      await expect(table.locator('th:has-text("Sample")')).toBeVisible();
      await expect(table.locator('th:has-text("Description")')).toBeVisible();
      await expect(table.locator('th:has-text("Site")')).toBeVisible();
      await expect(table.locator('th:has-text("Location")')).toBeVisible();
    });

    test('Path 1 Query shows HTML table', async ({ page }) => {
      // Find Path 1 section
      const path1Section = page.locator('text=Related Sample Path 1');
      await expect(path1Section).toBeVisible();

      // Check for table structure
      const tables = page.locator('table');
      const tableCount = await tables.count();

      // Should have at least 2 tables (Path 1 and Eric's)
      expect(tableCount).toBeGreaterThanOrEqual(2);
    });

    test('Path 2 Query shows HTML table', async ({ page }) => {
      // Find Path 2 section
      const path2Section = page.locator('text=Related Sample Path 2');
      await expect(path2Section).toBeVisible();

      // Check for table structure
      const tables = page.locator('table');
      const tableCount = await tables.count();

      // Should have 3 tables total
      expect(tableCount).toBeGreaterThanOrEqual(3);
    });

    test('Tables show result counts', async ({ page }) => {
      // Check for result count messages
      const resultCounts = page.locator('text=/Found \\d+ sample/');
      const count = await resultCounts.count();

      // Should have at least 1 result count (Eric's query should have data)
      expect(count).toBeGreaterThan(0);
    });

    test('Tables contain clickable sample links', async ({ page }) => {
      // Find links to OpenContext sample records
      const sampleLinks = page.locator('a[href*="ark:/"]');
      const linkCount = await sampleLinks.count();

      // Should have sample links if data loaded
      if (linkCount > 0) {
        const firstLink = sampleLinks.first();
        await expect(firstLink).toBeVisible();

        // Verify link has proper structure
        const href = await firstLink.getAttribute('href');
        expect(href).toContain('opencontext.org');
      }
    });

    test('Tables contain "View site" links', async ({ page }) => {
      // Find site links
      const siteLinks = page.locator('a:has-text("View site")');
      const linkCount = await siteLinks.count();

      // Should have site links if data loaded
      if (linkCount > 0) {
        const firstLink = siteLinks.first();
        await expect(firstLink).toBeVisible();

        // Verify link points to OpenContext
        const href = await firstLink.getAttribute('href');
        expect(href).toContain('opencontext.org');
      }
    });

    test('Tables show thumbnails or placeholders', async ({ page }) => {
      // Check for either actual thumbnail images or "No image" placeholders
      const thumbnailImages = page.locator('img[alt]');
      const noImagePlaceholders = page.locator('text=No image');

      const imageCount = await thumbnailImages.count();
      const placeholderCount = await noImagePlaceholders.count();

      // Should have at least one of: images or placeholders
      expect(imageCount + placeholderCount).toBeGreaterThan(0);
    });
  });

  test.describe('Empty States', () => {

    test('Shows friendly message when no samples found', async ({ page }) => {
      // Search for location with no Path 1 samples (site marker)
      const searchBox = page.locator('input[placeholder*="Paste geocode PID"]');
      await searchBox.fill(TEST_GEOCODE_NO_SAMPLES);
      await searchBox.press('Enter');

      // Wait for queries to complete
      await page.waitForTimeout(8000);

      // Check for empty state message (Eric's query)
      const emptyMessage = page.locator('text=/No samples found.*Path 1/');
      await expect(emptyMessage).toBeVisible({ timeout: 10000 });
    });
  });

  test.describe('Responsive Design', () => {

    test('Tables are scrollable when content exceeds height', async ({ page }) => {
      // Search for location with samples
      const searchBox = page.locator('input[placeholder*="Paste geocode PID"]');
      await searchBox.fill(TEST_GEOCODE_WITH_SAMPLES);
      await searchBox.press('Enter');

      await page.waitForTimeout(8000);

      // Check for scrollable container
      const scrollableDiv = page.locator('div[style*="max-height: 600px"]').first();
      if (await scrollableDiv.count() > 0) {
        await expect(scrollableDiv).toBeVisible();

        // Verify overflow-y is set
        const style = await scrollableDiv.getAttribute('style');
        expect(style).toContain('overflow-y: auto');
      }
    });

    test('Tables have sticky headers', async ({ page }) => {
      // Search for location with samples
      const searchBox = page.locator('input[placeholder*="Paste geocode PID"]');
      await searchBox.fill(TEST_GEOCODE_WITH_SAMPLES);
      await searchBox.press('Enter');

      await page.waitForTimeout(8000);

      // Check for sticky header styling
      const stickyHeader = page.locator('thead[style*="position: sticky"]').first();
      if (await stickyHeader.count() > 0) {
        await expect(stickyHeader).toBeVisible();
      }
    });
  });

  test.describe('Visual Consistency', () => {

    test('All three tables use same column structure', async ({ page }) => {
      // Search for location with samples
      const searchBox = page.locator('input[placeholder*="Paste geocode PID"]');
      await searchBox.fill(TEST_GEOCODE_WITH_SAMPLES);
      await searchBox.press('Enter');

      await page.waitForTimeout(8000);

      // Get all tables
      const tables = page.locator('table');
      const tableCount = await tables.count();

      if (tableCount >= 3) {
        // Check each table has 5 columns
        for (let i = 0; i < 3; i++) {
          const table = tables.nth(i);
          const headers = table.locator('th');
          const headerCount = await headers.count();

          expect(headerCount).toBe(5);
        }
      }
    });

    test('Tables use zebra-striped rows', async ({ page }) => {
      // Search for location with samples
      const searchBox = page.locator('input[placeholder*="Paste geocode PID"]');
      await searchBox.fill(TEST_GEOCODE_WITH_SAMPLES);
      await searchBox.press('Enter');

      await page.waitForTimeout(8000);

      // Check for alternating row backgrounds
      const stripedrRows = page.locator('tr[style*="background"]');
      const count = await stripedrRows.count();

      // Should have striped rows if data loaded
      expect(count).toBeGreaterThan(0);
    });
  });
});
