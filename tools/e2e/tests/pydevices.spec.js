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

// Check if a canvas is solid (blank/all one color)
async function expectCanvasNotSolid(page, selector) {
  const isSolid = await page.evaluate((sel) => {
    const canvas = document.querySelector(sel);
    if (!canvas) return true; // Treat missing canvas as failure
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) return true;
    const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
    const data = imageData.data;
    if (data.length === 0) return true;
    
    // Check if all pixels are identical to the first pixel
    const r0 = data[0], g0 = data[1], b0 = data[2], a0 = data[3];
    for (let i = 4; i < data.length; i += 4) {
      if (data[i] !== r0 || data[i+1] !== g0 || data[i+2] !== b0 || data[i+3] !== a0) {
        return false; // Found a different pixel, canvas is NOT solid!
      }
    }
    return true; // All pixels are the same
  }, selector);
  
  expect(isSolid).toBe(false);
}

for (const [env, base] of Object.entries(DOMAINS)) {
  test.describe(`Environment: ${env}`, () => {
    
    // Test non-gallery routes
    for (const route of OTHER_ROUTES) {
      test(`Verify ${route}`, async ({ page }) => {
        const url = `${base}${route}`;
        const errors = [];
        let sawInit = false;
        
        page.on('pageerror', err => errors.push(err.message));
        page.on('console', msg => {
          if (msg.type() === 'error') errors.push(msg.text());
          if (msg.text().includes('Initializing ')) sawInit = true;
        });

        await page.goto(url, { waitUntil: 'networkidle' });
        await page.waitForTimeout(1000); // Wait for WASM snippets
        
        // Simulator expects a display to initialize
        if (route.includes('/simulator/')) {
           // Wait extra time for simulator to boot
           await page.waitForTimeout(5000);
           expect(sawInit).toBe(true);
           await expectCanvasNotSolid(page, 'canvas');
        }
        
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
        let sawInit = false;
        
        page.on('pageerror', err => errors.push(err.message));
        page.on('console', msg => {
          const text = msg.text();
          if (text.includes('Initializing ')) sawInit = true;
          if (msg.type() === 'error') {
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
           await page.waitForTimeout(2000); // Wait for paint
           expect(sawInit).toBe(true);
           await expectCanvasNotSolid(page, 'canvas');
        }
        
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
      let sawInit = false;
      
      page.on('pageerror', err => errors.push(err.message));
      page.on('console', msg => {
        if (msg.type() === 'error') errors.push(msg.text());
        if (msg.text().includes('Initializing ')) sawInit = true;
      });

      await page.goto(site, { waitUntil: 'networkidle' });
      await page.waitForTimeout(5000); // Wait for embed to boot
      
      expect(sawInit).toBe(true);
      await expectCanvasNotSolid(page, 'canvas');
      
      const sanitized = site.replace(/[^a-zA-Z0-9]/g, '_');
      await page.screenshot({ path: path.join(OUTPUT_DIR, `rtd-${sanitized}.png`), fullPage: true });
    });
  }
});
