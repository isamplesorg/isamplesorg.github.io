# iSamples Testing Infrastructure

Automated tests for the iSamples Cesium tutorial UI using Playwright.

## Setup

### Install Dependencies

```bash
npm install
npx playwright install chromium
```

### Start Development Server

Before running tests, start the Quarto preview server:

```bash
quarto preview tutorials/parquet_cesium.qmd --no-browser
```

This will typically start on `http://localhost:5860` (port may vary).

## Running Tests

### Run All Tests

```bash
npx playwright test
```

### Run Specific Test File

```bash
npx playwright test tests/playwright/cesium-queries.spec.js
```

### Run in UI Mode (Interactive)

```bash
npx playwright test --ui
```

### Run with Browser Visible

```bash
npx playwright test --headed
```

### Run Specific Test

```bash
npx playwright test -g "shows HTML table"
```

## Test Structure

```
tests/
├── playwright/
│   └── cesium-queries.spec.js   # Cesium UI tests
└── README.md                     # This file
```

## What's Tested

### Cesium Query Results UI (`cesium-queries.spec.js`)

Tests the HTML table UI for all three query paths:

1. **Eric's Query** (Path 1 only, authoritative)
2. **Path 1 Query** (direct event location)
3. **Path 2 Query** (via site location)

#### Test Coverage

- ✅ Page loads and shows geocode search box
- ✅ Geocode search triggers camera movement
- ✅ HTML tables render with correct 5-column structure
- ✅ Tables contain clickable sample PID links
- ✅ Tables contain "View site" links
- ✅ Tables show thumbnails or "No image" placeholders
- ✅ Result counts display correctly
- ✅ Empty states show friendly messages
- ✅ Tables are scrollable with sticky headers
- ✅ Zebra-striped rows for readability
- ✅ Visual consistency across all three tables

#### Test Data

**Location with samples** (PKAP):
- `geoloc_04d6e816218b1a8798fa90b3d1d43bf4c043a57f`
- Returns ~5 samples via Path 1

**Location without samples** (Larnaka site marker):
- `geoloc_7a05216d388682536f3e2abd8bd2ee3fb286e461`
- Returns 0 samples (tests empty state)

## Test Reports

After running tests, view the HTML report:

```bash
npx playwright show-report tests/playwright-report
```

## Debugging

### Take Screenshots

Tests automatically capture screenshots on failure.

### View Traces

For failed tests with retries:

```bash
npx playwright show-trace tests/playwright-report/trace.zip
```

### Debug Mode

Run tests in debug mode with Playwright Inspector:

```bash
npx playwright test --debug
```

## Configuration

Test configuration is in `playwright.config.js`:

- **Test directory**: `./tests/playwright`
- **Base URL**: `http://localhost:5860` (configurable via `TEST_URL` env var)
- **Timeouts**: Extended for remote parquet loading
- **Reporters**: HTML + list
- **Screenshots**: On failure
- **Video**: On failure

### Environment Variables

Set custom test URL:

```bash
TEST_URL=http://localhost:3000 npx playwright test
```

## Continuous Integration

Tests are designed to run on CI with:

```bash
# Start Quarto preview in background
quarto preview tutorials/parquet_cesium.qmd --no-browser &

# Wait for server to start
sleep 10

# Run tests
npx playwright test

# CI will automatically retry failed tests 2x
```

## Adding New Tests

### Test File Template

```javascript
const { test, expect } = require('@playwright/test');

test.describe('Feature Name', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('/tutorials/parquet_cesium.html');
    // Add setup code
  });

  test('should do something', async ({ page }) => {
    // Test code
    await expect(page.locator('selector')).toBeVisible();
  });
});
```

### Best Practices

1. **Use descriptive test names** - "Table shows result counts" not "test 1"
2. **Wait for data loading** - Remote parquet queries can be slow
3. **Test user workflows** - Not implementation details
4. **Use `test.describe` blocks** - Group related tests
5. **Keep tests independent** - Each test should work alone
6. **Use page objects** - For complex selectors (future enhancement)

## Known Issues

### Remote Parquet Loading

The remote parquet file (~700MB) can take time to load. Tests include generous timeouts:

- Action timeout: 15 seconds
- Navigation timeout: 60 seconds
- Additional `waitForTimeout` calls where needed

### Observable Cell Evaluation

Observable cells may not evaluate immediately after page load. Tests wait for specific UI elements before interacting.

## Future Enhancements

- [ ] Add visual regression tests (screenshots comparison)
- [ ] Test mobile responsive layouts
- [ ] Test keyboard navigation
- [ ] Test accessibility (ARIA labels, screen readers)
- [ ] Add performance metrics (query execution time)
- [ ] Page object pattern for cleaner test code
- [ ] API mocking to speed up tests (mock parquet responses)
- [ ] Cross-browser testing (Firefox, Safari)

## Maintenance

### Updating Test Data

If test geocode IDs change, update constants in `cesium-queries.spec.js`:

```javascript
const TEST_GEOCODE_WITH_SAMPLES = 'geoloc_...';
const TEST_GEOCODE_NO_SAMPLES = 'geoloc_...';
```

### Updating Selectors

If UI structure changes, update locators in tests:

```javascript
// Before
page.locator('text=Old Label')

// After
page.locator('text=New Label')
```

## Resources

- [Playwright Documentation](https://playwright.dev/)
- [Playwright Test API](https://playwright.dev/docs/api/class-test)
- [Playwright Best Practices](https://playwright.dev/docs/best-practices)
- [Quarto Documentation](https://quarto.org/)
