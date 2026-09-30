const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

const FPS = 30;
const DUR = 20;
const TOTAL = FPS * DUR;
const OUT = path.join(__dirname, 'frames');

(async () => {
  if (!fs.existsSync(OUT)) fs.mkdirSync(OUT);
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
  await page.goto('file://' + path.join(__dirname, 'scene.html'));
  await page.waitForTimeout(500); // let webfont/lucide settle
  await page.evaluate(() => document.fonts.ready);

  for (let i = 0; i < TOTAL; i++) {
    const t = i / FPS;
    await page.evaluate((tt) => window.__setTime(tt), t);
    await page.waitForTimeout(10);
    const fname = path.join(OUT, `f${String(i).padStart(5, '0')}.png`);
    await page.screenshot({ path: fname });
    if (i % 30 === 0) console.log(`frame ${i}/${TOTAL}`);
  }
  await browser.close();
  console.log('done');
})();
