const { chromium } = require('playwright');
const path = require('path');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1080, height: 1920 } });
  await page.goto('file://' + path.join(__dirname, 'scene.html'));
  await page.waitForTimeout(500);
  await page.evaluate(() => document.fonts.ready);
  const times = [0.5, 1.5, 2.2, 3.5, 5.5, 8.0, 9.5, 12.0, 15.5, 18.5];
  for (const t of times) {
    await page.evaluate((tt) => window.__setTime(tt), t);
    await page.waitForTimeout(30);
    await page.screenshot({ path: path.join(__dirname, `still_${t}.png`) });
  }
  await browser.close();
  console.log('done');
})();
