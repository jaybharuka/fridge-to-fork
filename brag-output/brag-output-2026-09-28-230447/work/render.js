const { chromium } = require('C:/Projects/fridge-to-fork/brag-output/work/node_modules/playwright');
const path = require('path');
const FPS = 30, DUR = 20;
(async () => {
  const times = process.argv[2] ? process.argv[2].split(',').map(Number) : null;
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  await page.goto('file://' + path.join(__dirname, 'scene.html'));
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(800);
  const list = times ? times.map(t => [t, path.join(__dirname, `still_${t}.png`)])
    : Array.from({ length: FPS * DUR }, (_, i) => [i / FPS, path.join(__dirname, 'frames', `f${String(i).padStart(5, '0')}.png`)]);
  for (const [t, f] of list) {
    await page.evaluate(tt => window.__setTime(tt), t);
    await page.screenshot({ path: f });
  }
  await browser.close();
})();
