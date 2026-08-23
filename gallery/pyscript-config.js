import { parse as parseTOML } from './vendor/toml-Blg7Izee.js';

async function loadConfig(url) {
    const response = await fetch(url);
    if (!response.ok) {
        throw new Error(`Unable to load ${response.url}: HTTP ${response.status}`);
    }
    const text = await response.text();
    return parseTOML(text);
}

function mergeConfigs(configs) {
    const merged = Object.assign({}, ...configs);
    merged.files = Object.assign({}, ...configs.map((config) => config.files || {}));
    const packages = configs.flatMap((config) => config.packages || []).filter(Boolean);
    if (packages.length > 0) {
        merged.packages = Array.from(new Set(packages));
    }
    return merged;
}

(async function configurePyScript() {
    try {
        const targets = Array.from(document.querySelectorAll('script[data-configs]'));
        await Promise.all(targets.map(async (target) => {
            const urls = target.dataset.configs.split(/\s+/).filter(Boolean);
            const configs = await Promise.all(urls.map(loadConfig));
            target.setAttribute('config', JSON.stringify(mergeConfigs(configs)));
            target.removeAttribute('data-configs');
        }));
        await import('./vendor/core.js');
    } catch (error) {
        const log = document.getElementById('log');
        const status = document.getElementById('status');
        const spinner = document.getElementById('spinner');
        if (log) {
            log.hidden = false;
            log.textContent += `Unable to configure PyScript: ${error.message}\n`;
        }
        if (status) {
            status.textContent = 'Configuration error — see console.';
            status.classList.add('status-error');
        }
        if (spinner) {
            spinner.hidden = true;
        }
        console.error(error);
    }
})();
