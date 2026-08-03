// Abre la app de Streamlit con un navegador headless para que el servidor
// ejecute el script (y con el, sync_today_picks) y quede registrada la jornada.
// Un simple ping HTTP NO basta: Streamlit corre el script solo cuando se abre
// una sesion real de navegador. Por eso usamos Playwright/Chromium.
const { chromium } = require('playwright');

(async () => {
  const url = process.env.APP_URL;
  if (!url) { console.error('Falta APP_URL'); process.exit(1); }

  const browser = await chromium.launch();
  const page = await browser.newPage();
  console.log('Abriendo', url);
  // La app puede estar dormida: goto con timeout holgado para que despierte.
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 120000 });

  // El registro (sync_today_picks) corre al ejecutarse el script; damos tiempo
  // a que termine el analisis (150k simulaciones) y se grabe el dia.
  await page.waitForTimeout(75000);

  const txt = await page.evaluate(() =>
    (document.body.innerText || '').replace(/\s+/g, ' ').slice(0, 240));
  console.log('Contenido tras la visita:', txt || '(vacio)');

  await browser.close();
})().catch((e) => { console.error('Fallo la visita:', e); process.exit(1); });
