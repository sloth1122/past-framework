const puppeteer = require('puppeteer');
const path = require('path');

(async () => {
  const browser = await puppeteer.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });
  
  const page = await browser.newPage();
  await page.setViewport({ width: 1200, height: 800, deviceScaleFactor: 2 });
  
  const htmlPath = path.resolve(__dirname, 'PAST_Architecture_Diagram.html');
  await page.goto(`file://${htmlPath}`, { waitUntil: 'networkidle0' });
  
  await page.waitForTimeout(1000);
  
  await page.screenshot({
    path: path.resolve(__dirname, 'PAST_Architecture_Diagram.png'),
    fullPage: false
  });
  
  console.log('Screenshot saved to PAST_Architecture_Diagram.png');
  await browser.close();
})();
