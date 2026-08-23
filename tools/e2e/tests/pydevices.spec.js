const { test, expect } = require('@playwright/test');
const path = require('path');
const fs = require('fs');

const DOMAINS = {
  local: 'http://127.0.0.1:8000',
  live: 'https://pydevices.github.io'
};

const RTD_SITES = [
  'https://pydevices.readthedocs.io/en/latest/',
  'https://pygraphics.readthedocs.io/en/latest/',
  'https://pdwidgets.readthedocs.io/en/latest/'
];

// Base routes for the pydevices-examples gallery
const GALLERY_ROUTES = [
  'dom.html',
  'async.html',
  'micropython.html?modules=hello',
  'pyodide.html?modules=hello',
  'mp.html?modules=hello',
  'py.html?modules=hello',
  'harness.html?modules=hello',
  'editor.html',
  'repl.html',
  'peterhinch.html?touch'
];

const OTHER_ROUTES = [
  '/',
  '/pydevices/',
  '/pydevices-examples/',
  '/simulator/'
];

const OUTPUT_DIR = '/tmp/e2e-screenshots';
if (!fs.existsSync(OUTPUT_DIR)) {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
}

for (const [env, base] of Object.entries(DOMAINS)) {
  test.describe(`Environment: ${env}`, () => {
    
    // Test non-gallery routes
    for (const route of OTHER_ROUTES) {
      test(`Verify ${route}`, async ({ page }) => {
        const url = `${base}${route}`;
        const errors = [];
        page.on('pageerror', err => errors.push(err.message));
        page.on('console', msg => {
          if (msg.type() === 'error') errors.push(msg.text());
        });

        await page.goto(url, { waitUntil: 'networkidle' });
        await page.waitForTimeout(1000); // Wait for WASM snippets
        
        expect(errors).toEqual([]); // No errors allowed
        
        const sanitizedRoute = route === '/' ? 'index' : route.replace(/[^a-zA-Z0-9]/g, '_');
        await page.screenshot({ path: path.join(OUTPUT_DIR, `${env}-${sanitizedRoute}.png`), fullPage: true });
      });
    }

    // Test gallery routes
    for (const route of GALLERY_ROUTES) {
      test(`Verify gallery app: ${route}`, async ({ page }) => {
        // Local serves from .site/gallery, Live serves from gallery
        const galleryPrefix = env === 'local' ? '/pydevices-examples/.site/gallery/' : '/pydevices-examples/gallery/';
        const url = `${base}${galleryPrefix}${route}`;
        
        const errors = [];
        page.on('pageerror', err => errors.push(err.message));
        page.on('console', msg => {
          if (msg.type() === 'error') {
            const text = msg.text();
            if (!text.includes('favicon') && !text.includes('status of 404')) {
              errors.push(text);
            }
          }
        });

        await page.goto(url, { waitUntil: 'domcontentloaded' });
        
        // Ensure no error status
        const statusEl = await page.$('#status');
        if (statusEl) {
           const status = await statusEl.textContent();
           expect(status.toLowerCase()).not.toContain('error');
        }
        
        // Wait for canvas if the route typically uses one
        if (!route.includes('editor') && !route.includes('repl')) {
           await page.waitForSelector('canvas', { timeout: 15000 });
        }
        
        // Wait an extra second for painting to finish
        await page.waitForTimeout(2000);
        
        expect(errors).toEqual([]);
        
        const sanitizedRoute = route.replace(/[^a-zA-Z0-9]/g, '_');
        await page.screenshot({ path: path.join(OUTPUT_DIR, `${env}-gallery-${sanitizedRoute}.png`), fullPage: true });
      });
    }
  });
}

test.describe('RTD Sites', () => {
  for (const site of RTD_SITES) {
    test(`Verify ${site}`, async ({ page }) => {
      const errors = [];
      page.on('pageerror', err => errors.push(err.message));
      page.on('console', msg => {
        if (msg.type() === 'error') errors.push(msg.text());
      });

      await page.goto(site, { waitUntil: 'networkidle' });
      await page.waitForTimeout(2000);
      
      const sanitized = site.replace(/[^a-zA-Z0-9]/g, '_');
      await page.screenshot({ path: path.join(OUTPUT_DIR, `rtd-${sanitized}.png`), fullPage: true });
    });
  }
});
