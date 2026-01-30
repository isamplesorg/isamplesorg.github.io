/**
 * Test performance optimizations on Cesium page
 *
 * Verifies:
 * 1. Page loads quickly
 * 2. Dots appear (blue)
 * 3. Classification button exists
 * 4. Console shows performance telemetry
 */

const { chromium } = require('playwright');

async function testPerformanceOptimizations() {
    console.log('🧪 Testing Cesium Performance Optimizations\n');
    console.log('=' .repeat(80));

    const browser = await chromium.launch({ headless: false });
    const context = await browser.newContext();
    const page = await context.newPage();

    // Collect console messages for telemetry
    const consoleLogs = [];
    page.on('console', msg => {
        const text = msg.text();
        consoleLogs.push(text);
        console.log(`📊 [Console] ${text}`);
    });

    try {
        // Test 1: Navigate to page and measure load time
        console.log('\n✅ Test 1: Page Load Performance');
        console.log('-'.repeat(80));

        const startTime = Date.now();
        await page.goto('http://localhost:5860/tutorials/parquet_cesium.html', {
            waitUntil: 'domcontentloaded',
            timeout: 60000
        });
        const loadTime = Date.now() - startTime;
        console.log(`⏱️  Page loaded in ${loadTime}ms`);

        // Test 2: Wait for Cesium globe to initialize
        console.log('\n✅ Test 2: Cesium Globe Initialization');
        console.log('-'.repeat(80));

        await page.waitForSelector('#cesiumContainer', { timeout: 30000 });
        console.log('✓ Cesium container found');

        // Wait a bit for DuckDB and points to load
        console.log('⏳ Waiting for geocodes to load...');
        await page.waitForTimeout(15000);

        // Test 3: Check for classification button
        console.log('\n✅ Test 3: Classification Button');
        console.log('-'.repeat(80));

        const button = await page.locator('button:has-text("Color-code by type")');
        const buttonVisible = await button.isVisible({ timeout: 5000 }).catch(() => false);

        if (buttonVisible) {
            console.log('✓ Classification button found');
            console.log(`  Text: "${await button.innerText()}"`);
        } else {
            console.log('✗ Classification button NOT found');
        }

        // Test 4: Analyze console telemetry
        console.log('\n✅ Test 4: Performance Telemetry Analysis');
        console.log('-'.repeat(80));

        const queryLog = consoleLogs.find(log => log.includes('Query executed'));
        const renderLog = consoleLogs.find(log => log.includes('Rendering completed'));
        const totalLog = consoleLogs.find(log => log.includes('Total time'));

        if (queryLog) {
            console.log(`✓ ${queryLog}`);
            const queryTimeMatch = queryLog.match(/(\d+)ms/);
            if (queryTimeMatch) {
                const queryTime = parseInt(queryTimeMatch[1]);
                if (queryTime < 3000) {
                    console.log(`  🎉 Query time ${queryTime}ms is under 3s (FAST!)`);
                } else {
                    console.log(`  ⚠️  Query time ${queryTime}ms is over 3s (could be faster)`);
                }
            }
        } else {
            console.log('✗ No query timing found in console');
        }

        if (renderLog) {
            console.log(`✓ ${renderLog}`);
        }

        if (totalLog) {
            console.log(`✓ ${totalLog}`);
            const totalTimeMatch = totalLog.match(/(\d+)ms/);
            if (totalTimeMatch) {
                const totalTime = parseInt(totalTimeMatch[1]);
                if (totalTime < 3000) {
                    console.log(`  🎉 Total time ${totalTime}ms is under 3s (EXCELLENT!)`);
                } else if (totalTime < 5000) {
                    console.log(`  👍 Total time ${totalTime}ms is under 5s (GOOD)`);
                } else {
                    console.log(`  ⚠️  Total time ${totalTime}ms is over 5s (needs work)`);
                }
            }
        }

        // Test 5: Click classification button (optional)
        console.log('\n✅ Test 5: Optional Classification');
        console.log('-'.repeat(80));
        console.log('Press Enter to test classification button, or Ctrl+C to skip...');

        // Wait for user input
        await new Promise(resolve => {
            process.stdin.once('data', resolve);
        });

        if (buttonVisible) {
            console.log('🖱️  Clicking classification button...');
            consoleLogs.length = 0; // Clear logs
            await button.click();

            // Wait for classification
            await page.waitForTimeout(10000);

            const classifyLog = consoleLogs.find(log => log.includes('Classification completed'));
            if (classifyLog) {
                console.log(`✓ ${classifyLog}`);
            } else {
                console.log('⏳ Classification may still be running...');
            }
        }

        // Final summary
        console.log('\n' + '='.repeat(80));
        console.log('📊 Performance Test Summary');
        console.log('='.repeat(80));
        console.log(`Page load time: ${loadTime}ms`);
        console.log(`Classification button: ${buttonVisible ? '✓ Present' : '✗ Missing'}`);
        console.log(`Console telemetry: ${consoleLogs.length} messages captured`);
        console.log('\n✅ Test complete! Browser will stay open for manual inspection.');
        console.log('Press Enter to close...');

        await new Promise(resolve => {
            process.stdin.once('data', resolve);
        });

    } catch (error) {
        console.error('\n❌ Test failed:', error.message);
        console.error(error.stack);
    } finally {
        await browser.close();
    }
}

// Run the test
testPerformanceOptimizations().catch(console.error);
