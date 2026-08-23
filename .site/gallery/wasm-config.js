// wasm-config.js - Bootstraps the MicroPython WASM port and injects _wasm_bridge

import { loadMicroPython } from 'https://cdn.jsdelivr.net/npm/@micropython/micropython-webassembly-pyscript@1.22.0/micropython.mjs';

// Configuration and state
let mp = null;
let displayCanvas = null;
let displayCtx = null;
let displayBufferAddr = null;
let displayWidth = 0;
let displayHeight = 0;
let eventQueue = [];

// Audio Context
let audioCtx = null;

export async function bootstrapWasm() {
    displayCanvas = document.getElementById('display_canvas');
    if (displayCanvas) {
        displayCtx = displayCanvas.getContext('2d');
    }

    mp = await loadMicroPython();
    
    // Inject _wasm_bridge
    mp.registerJsModule('_wasm_bridge', {
        register_display: (width, height, address) => {
            displayWidth = width;
            displayHeight = height;
            displayBufferAddr = address;
        },
        render_display: (x, y, w, h) => {
            if (!displayCtx || !displayBufferAddr) return;
            if (x === undefined) {
                x = 0; y = 0; w = displayWidth; h = displayHeight;
            }
            // Read from HEAPU8
            const buffer = new Uint8Array(mp.module.HEAPU8.buffer, displayBufferAddr, displayWidth * displayHeight * 2);
            // Convert RGB565 to RGBA
            const imgData = displayCtx.createImageData(w, h);
            let ptr = 0;
            for (let r = y; r < y + h; r++) {
                for (let c = x; c < x + w; c++) {
                    const idx = (r * displayWidth + c) * 2;
                    const rgb565 = buffer[idx] | (buffer[idx + 1] << 8);
                    const red = (rgb565 >> 11) & 0x1f;
                    const green = (rgb565 >> 5) & 0x3f;
                    const blue = rgb565 & 0x1f;
                    imgData.data[ptr++] = (red * 255) / 31;
                    imgData.data[ptr++] = (green * 255) / 63;
                    imgData.data[ptr++] = (blue * 255) / 31;
                    imgData.data[ptr++] = 255;
                }
            }
            displayCtx.putImageData(imgData, x, y);
        },
        get_events: () => {
            if (eventQueue.length === 0) return null;
            const ev = eventQueue.shift();
            // Convert event to Python dict or tuple
            // For now, return a basic dict
            return ev;
        },
        // Audio output stub
        audio_out_open: (rate, channels) => {
            if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: rate });
        },
        audio_out_write: (address, length) => {
            // Read PCM bytes from HEAPU8
        },
        audio_out_queued_ms: () => {
            return 0;
        },
        audio_out_close: () => {},
        // Audio input stub
        audio_in_open: (rate) => {},
        audio_in_read: (address, max_len) => { return 0; },
        audio_in_close: () => {},
        // Timers stub
        set_timeout: (cb, ms) => {
            return setTimeout(() => { cb(); }, ms);
        },
        set_interval: (cb, ms) => {
            return setInterval(() => { cb(); }, ms);
        },
        clear_timer: (id) => {
            clearTimeout(id);
            clearInterval(id);
        }
    });

    // Capture events on canvas
    if (displayCanvas) {
        displayCanvas.addEventListener('pointerdown', e => {
            const rect = displayCanvas.getBoundingClientRect();
            eventQueue.push({type: 'pointerdown', x: e.clientX - rect.left, y: e.clientY - rect.top});
        });
        displayCanvas.addEventListener('pointerup', e => {
            const rect = displayCanvas.getBoundingClientRect();
            eventQueue.push({type: 'pointerup', x: e.clientX - rect.left, y: e.clientY - rect.top});
        });
        displayCanvas.addEventListener('pointermove', e => {
            const rect = displayCanvas.getBoundingClientRect();
            eventQueue.push({type: 'pointermove', x: e.clientX - rect.left, y: e.clientY - rect.top});
        });
    }

    // Execute scripts
    const scripts = document.querySelectorAll('script[type="text/python"]');
    for (const script of scripts) {
        mp.runPython(script.textContent);
    }
}

document.addEventListener("DOMContentLoaded", bootstrapWasm);
