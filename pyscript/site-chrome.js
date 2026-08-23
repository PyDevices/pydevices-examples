/*
 * PyDevices — shared site header, footer & left-side navigation drawer
 *
 * Injects identical chrome into pages that provide mount points:
 *   <div id="pydevices-site-header"></div>
 *   ...
 *   <div id="pydevices-site-footer"></div>
 *   <script src="https://pydevices.github.io/assets/js/site-chrome.js"></script>
 *   <script src="https://pydevices.github.io/assets/js/theme-toggle.js"></script>
 */
(function () {
  'use strict';

  var chromeScript = document.querySelector('script[src*="site-chrome.js"]');
  var ROOT = '';
  if (chromeScript && chromeScript.src.startsWith('http')) {
    try {
      var scriptUrl = new URL(chromeScript.src);
      if (scriptUrl.origin !== window.location.origin) {
        ROOT = scriptUrl.origin;
      }
    } catch (e) {}
  }
  var LOGO = (ROOT || '') + '/assets/img/logo.svg';

  var HEADER =
    '<header class="site-header">' +
    '<div class="wrap">' +
    '<a class="brand" href="' +
    (ROOT || '/') +
    '/">' +
    '<span class="logo"><img src="' +
    LOGO +
    '" alt="" width="30" height="30"></span>' +
    "PyDevices" +
    "</a>" +
    '<nav class="nav">' +
    '<a href="' +
    ROOT +
    '/pydevices/">Core Stack</a>' +
    '<a href="' +
    ROOT +
    '/simulator/">Simulator</a>' +
    '<a href="' +
    ROOT +
    '/displayif/">Native C</a>' +
    '<a href="' +
    ROOT +
    '/pydevices-examples/gallery/" class="nav-gallery-link">Gallery</a>' +
    '<a href="https://github.com/PyDevices">GitHub</a>' +
    "</nav>" +
    '<button type="button" class="theme-toggle" id="theme-toggle" aria-label="Toggle color theme" title="Toggle color theme">' +
    '<svg class="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>' +
    '<svg class="icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>' +
    "</button>" +
    "</div>" +
    "</header>";

  var FOOTER =
    '<footer class="site-footer">' +
    '<div class="wrap">' +
    "<span>&copy; 2026 PyDevices &middot; MIT License</span>" +
    '<span><a href="https://github.com/PyDevices">github.com/PyDevices</a></span>' +
    "</div>" +
    "</footer>";

  var ECOSYSTEM_DATA = [
    {
      tier: 0,
      name: "Organization Portal",
      color: "var(--tier-1-amber, #d97706)",
      repos: [
        {
          id: "root",
          name: "PyDevices",
          path: "/",
          url: ROOT + "/",
          tag: "HOME",
          desc: "Universal board contract & Python graphics umbrella",
          icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5"/></svg>'
        }
      ]
    },
    {
      tier: 1,
      name: "Core Platform & HAL",
      color: "var(--tier-1-amber, #d97706)",
      repos: [
        {
          id: "pydevices",
          name: "pydevices",
          path: "/pydevices/",
          url: ROOT + "/pydevices/",
          tag: "Core HAL",
          desc: "Unified display HAL & device driver abstraction",
          icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>'
        },
        {
          id: "displayif",
          name: "displayif",
          path: "/displayif/",
          url: ROOT + "/displayif/",
          tag: "C Bus",
          desc: "Native C SPI, I2C, 8080 & RGB usermods",
          icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>'
        },
        {
          id: "pydevices-examples",
          name: "examples",
          path: "/pydevices-examples/",
          url: ROOT + "/pydevices-examples/",
          tag: "Showcase",
          desc: "Multi-interpreter demos, benchmarks & PyScript runner",
          icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 9h6M9 12h6M9 15h4"/><circle cx="17" cy="15" r="1.5"/></svg>'
        }
      ]
    },
    {
      tier: 2,
      name: "Framebuffers & UI Toolkits",
      color: "var(--tier-2-emerald, #059669)",
      repos: [
        {
          id: "pygraphics",
          name: "pygraphics",
          path: "/pygraphics/",
          url: ROOT + "/pygraphics/",
          tag: "2D FrameBuffer",
          desc: "0-dependency pure-Python raster graphics primitives",
          icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/></svg>'
        },
        {
          id: "pdwidgets",
          name: "pdwidgets",
          path: "/pdwidgets/",
          url: ROOT + "/pdwidgets/",
          tag: "UI Toolkit",
          desc: "Embedded widgets with gauges, sliders & switches",
          icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg>'
        },
        {
          id: "palettes",
          name: "palettes",
          path: "/palettes/",
          url: ROOT + "/palettes/",
          tag: "Color Engine",
          desc: "Color quantization, HSL & RGB565 format conversion",
          icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="13.5" cy="6.5" r=".5"/><circle cx="17.5" cy="10.5" r=".5"/><circle cx="8.5" cy="7.5" r=".5"/><circle cx="6.5" cy="12.5" r=".5"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.9 0 2-.8 2-2 0-.5-.2-1-.2-1.5 0-.8.7-1.5 1.5-1.5H17c2.8 0 5-2.2 5-5 0-5.5-4.5-10-10-10z"/></svg>'
        }
      ]
    },
    {
      tier: 3,
      name: "LVGL Native Extensions",
      color: "var(--tier-3-blue, #2563eb)",
      repos: [
        {
          id: "lvgl-bindings",
          name: "lvgl-bindings",
          path: "/lvgl-bindings/",
          url: ROOT + "/lvgl-bindings/",
          tag: "Generator",
          desc: "C header AST parser & zero-copy binding generator",
          icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>'
        },
        {
          id: "lvgl-micropython",
          name: "lvgl-micropython",
          path: "/lvgl-micropython/",
          url: ROOT + "/lvgl-micropython/",
          tag: "MicroPython",
          desc: "Precompiled LVGL v9 usermod bindings for MicroPython",
          icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 17V7l8-4 8 4v10l-8 4z"/><path d="M4 7l8 4 8-4M12 11v10"/></svg>'
        },
        {
          id: "lvgl-python",
          name: "lvgl-python",
          path: "/lvgl-python/",
          url: ROOT + "/lvgl-python/",
          tag: "CPython / WASM",
          desc: "LVGL Python wheels for Linux, macOS & WebAssembly",
          icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2a4 4 0 0 1 4 4v1h1a3 3 0 0 1 3 3v1a4 4 0 0 1-4 4h-1v1a4 4 0 0 1-4 4 4 4 0 0 1-4-4v-1H6a4 4 0 0 1-4-4v-1a3 3 0 0 1 3-3h1V6a4 4 0 0 1 4-4z"/></svg>'
        },
        {
          id: "lvgl-circuitpython",
          name: "lvgl-circuitpython",
          path: "/lvgl-circuitpython/",
          url: ROOT + "/lvgl-circuitpython/",
          tag: "CircuitPython",
          desc: "Custom firmware builds with LVGL for CircuitPython",
          icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="4"/><path d="M12 3v3M12 18v3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M3 12h3M18 12h3M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/></svg>'
        }
      ]
    },
    {
      tier: 4,
      name: "App Hosts & Mobile",
      color: "var(--tier-4-purple, #7c3aed)",
      repos: [
        {
          id: "pyscript-template",
          name: "pyscript-template",
          path: "/pyscript-template/",
          url: ROOT + "/pyscript-template/",
          tag: "PWA Template",
          desc: "Zero-config PyScript & WebAssembly app scaffold",
          icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="14" rx="2"/><path d="M8 21h8M12 18v3"/><path d="M8 9h8M8 13h5"/></svg>'
        },
        {
          id: "android-template",
          name: "android-template",
          path: "/android-template/",
          url: ROOT + "/android-template/",
          tag: "Android APK",
          desc: "Kivy / python-for-android packaging template",
          icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="2" width="12" height="20" rx="2"/><path d="M10 19h4"/></svg>'
        }
      ]
    },
    {
      tier: 5,
      name: "Developer Tools & Infrastructure",
      color: "var(--tier-5-steel, #0284c7)",
      repos: [
        {
          id: "mip",
          name: "mip",
          path: "/mip",
          url: "https://PyDevices.github.io/mip",
          tag: "MIP Index",
          desc: "Single source of truth for .mpy package distributions",
          icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 16V8a2 2 0 0 0-1-1.7l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.7l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><path d="M3.3 7L12 12l8.7-5M12 22V12"/></svg>'
        },
        {
          id: "cmods",
          name: "cmods",
          path: "/cmods/",
          url: ROOT + "/cmods/",
          tag: "C Workspace",
          desc: "Out-of-tree multi-usermod C firmware compilation",
          icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2l9 5v10l-9 5-9-5V7z"/><path d="M3 7l9 5 9-5M12 12v10"/></svg>'
        },
        {
          id: "mpftp",
          name: "mpftp",
          path: "/mpftp/",
          url: ROOT + "/mpftp/",
          tag: "IDE Extension",
          desc: "Serial FTP file manager & in-editor REPL for IDEs",
          icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="3" width="12" height="18" rx="2"/><path d="M9 7h6M9 11h6M9 15h4"/><circle cx="15" cy="15" r="1"/><path d="M15 16v3M13 19h4"/></svg>'
        }
      ]
    }
  ];

  function buildSidebarHtml() {
    var curPath = window.location.pathname;

    var html = '<div class="pydevices-nav-scrim" id="pydevices-nav-scrim"></div>';
    html += '<aside class="pydevices-nav-sidebar" id="pydevices-nav-sidebar" aria-label="PyDevices Ecosystem Navigation">';

    // 1. Peeking Handle (visible on screens <= 1400px when collapsed)
    html += '<div class="pydevices-nav-peeking-tab" id="pydevices-nav-peeking-tab" title="Click to browse PyDevices Ecosystem">';
    html += '  <img src="' + LOGO + '" alt="" class="peeking-logo" width="22" height="22">';
    html += '  <span class="peeking-title">PYDEVICES</span>';
    html += '  <svg class="peeking-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M9 18l6-6-6-6"/></svg>';
    html += '</div>';

    // 2. Full Navigation Panel
    html += '<div class="pydevices-nav-panel">';
    html += '  <div class="pydevices-nav-header">';
    html += '    <a class="pydevices-nav-brand" href="' + ROOT + '/">';
    html += '      <img src="' + LOGO + '" alt="PyDevices" width="28" height="28">';
    html += '      <div>';
    html += '        <div class="pydevices-nav-brand-title">PyDevices</div>';
    html += '        <div class="pydevices-nav-brand-sub">Ecosystem Navigator</div>';
    html += '      </div>';
    html += '    </a>';
    html += '    <button type="button" class="pydevices-nav-close" id="pydevices-nav-close" aria-label="Close navigation">&times;</button>';
    html += '  </div>';

    // Search Filter Input
    html += '  <div class="pydevices-nav-search-wrap">';
    html += '    <svg class="pydevices-nav-search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>';
    html += '    <input type="text" class="pydevices-nav-search" id="pydevices-nav-search" placeholder="Filter..." autocomplete="off">';
    html += '  </div>';

    // Scrollable Body with Tiers & Cards
    html += '  <div class="pydevices-nav-body" id="pydevices-nav-body">';
    for (var t = 0; t < ECOSYSTEM_DATA.length; t++) {
      var tierObj = ECOSYSTEM_DATA[t];
      html += '    <div class="pydevices-nav-tier-group" data-tier="' + tierObj.tier + '">';
      html += '      <div class="pydevices-nav-tier-head">';
      html += '        <span class="pydevices-nav-tier-pill" style="background:' + tierObj.color + '">T' + tierObj.tier + '</span>';
      html += '        <span class="pydevices-nav-tier-name">' + tierObj.name + '</span>';
      html += '      </div>';
      html += '      <div class="pydevices-nav-cards">';

      for (var r = 0; r < tierObj.repos.length; r++) {
        var repo = tierObj.repos[r];
        var isCurrent = false;

        if (repo.id === 'root') {
          isCurrent = (curPath === '/' || curPath === '/index.html' || curPath === '');
        } else if (curPath.indexOf(repo.path) !== -1 || (repo.id === 'mip' && curPath.indexOf('/mip') !== -1)) {
          isCurrent = true;
        }

        html += '        <a class="pydevices-nav-card' + (isCurrent ? ' is-active' : '') + '" href="' + repo.url + '" data-name="' + repo.name.toLowerCase() + '" data-tag="' + repo.tag.toLowerCase() + '" data-desc="' + repo.desc.toLowerCase() + '">';
        html += '          <div class="nav-card-icon" style="color:' + tierObj.color + '">' + repo.icon + '</div>';
        html += '          <div class="nav-card-content">';
        html += '            <div class="nav-card-title-row">';
        html += '              <span class="nav-card-title">' + repo.name + '</span>';
        html += '              <span class="nav-card-tag tag-tier-' + tierObj.tier + '">' + repo.tag + '</span>';
        html += '            </div>';
        html += '            <div class="nav-card-desc">' + repo.desc + '</div>';
        html += '          </div>';
        html += '        </a>';
      }

      html += '      </div>';
      html += '    </div>';
    }
    html += '  </div>';

    // Footer Links
    html += '  <div class="pydevices-nav-footer">';
    html += '    <a href="' + ROOT + '/pydevices-examples/gallery/" class="nav-foot-link">Interactive Gallery</a> &middot; ';
    html += '    <a href="https://PyDevices.github.io/mip" class="nav-foot-link">MIP Index</a> &middot; ';
    html += '    <a href="https://github.com/PyDevices" class="nav-foot-link">GitHub</a>';
    html += '  </div>';

    html += '</div>';
    html += '</aside>';

    return html;
  }

  function setupNavigationEvents() {
    var sidebar = document.getElementById('pydevices-nav-sidebar');
    var scrim = document.getElementById('pydevices-nav-scrim');
    var peekingTab = document.getElementById('pydevices-nav-peeking-tab');
    var closeBtn = document.getElementById('pydevices-nav-close');
    var searchInput = document.getElementById('pydevices-nav-search');

    if (!sidebar || !scrim) return;

    function openDrawer() {
      sidebar.classList.add('is-open');
      scrim.classList.add('is-open');
      document.body.classList.add('pydevices-drawer-open');
      var activeCard = sidebar.querySelector('.pydevices-nav-card.is-active');
      if (activeCard) {
        activeCard.focus({ preventScroll: true });
        activeCard.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      } else {
        var firstCard = sidebar.querySelector('.pydevices-nav-card');
        if (firstCard) {
          firstCard.focus({ preventScroll: true });
        }
      }
    }

    function closeDrawer() {
      sidebar.classList.remove('is-open');
      scrim.classList.remove('is-open');
      document.body.classList.remove('pydevices-drawer-open');
    }

    if (peekingTab) {
      peekingTab.addEventListener('click', function (e) {
        e.stopPropagation();
        openDrawer();
      });
    }

    if (closeBtn) {
      closeBtn.addEventListener('click', function (e) {
        e.stopPropagation();
        closeDrawer();
      });
    }

    scrim.addEventListener('click', closeDrawer);

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && sidebar.classList.contains('is-open')) {
        closeDrawer();
      }
    });

    // Instant Search Filter
    if (searchInput) {
      searchInput.addEventListener('input', function (e) {
        var query = e.target.value.toLowerCase().trim();
        var tierGroups = sidebar.querySelectorAll('.pydevices-nav-tier-group');

        tierGroups.forEach(function (group) {
          var cards = group.querySelectorAll('.pydevices-nav-card');
          var visibleInGroup = 0;

          cards.forEach(function (card) {
            if (!query) {
              card.style.display = '';
              visibleInGroup++;
              return;
            }
            var name = card.getAttribute('data-name') || '';
            var tag = card.getAttribute('data-tag') || '';
            var desc = card.getAttribute('data-desc') || '';

            if (name.indexOf(query) !== -1 || tag.indexOf(query) !== -1 || desc.indexOf(query) !== -1) {
              card.style.display = '';
              visibleInGroup++;
            } else {
              card.style.display = 'none';
            }
          });

          group.style.display = visibleInGroup > 0 ? '' : 'none';
        });
      });
    }
  }

  function setupThemeToggle() {
    var toggle = document.getElementById("theme-toggle");
    if (!toggle || toggle.getAttribute("data-bound")) {
      return;
    }
    toggle.setAttribute("data-bound", "true");
    toggle.addEventListener("click", function () {
      var root = document.documentElement;
      var current = root.getAttribute("data-theme") === "light" ? "light" : "dark";
      var next = current === "light" ? "dark" : "light";
      if (next === "light") {
        root.setAttribute("data-theme", "light");
      } else {
        root.removeAttribute("data-theme");
      }
      try {
        localStorage.setItem("pydevices-theme", next);
      } catch (e) {}
    });
  }

  function inject() {
    var headerMount = document.getElementById("pydevices-site-header");
    var footerMount = document.getElementById("pydevices-site-footer");
    if (headerMount) {
      headerMount.outerHTML = HEADER;
    }
    if (footerMount) {
      footerMount.outerHTML = FOOTER;
    }

    // Bind theme toggle on header
    setupThemeToggle();

    // Inject Left-Side Navigation Drawer
    if (!document.getElementById("pydevices-nav-sidebar")) {
      document.body.insertAdjacentHTML("afterbegin", buildSidebarHtml());
      setupNavigationEvents();
      document.body.classList.add("has-pydevices-nav");
    }

    var scriptEl = document.querySelector('script[src*="site-chrome.js"]');
    var base = scriptEl ? scriptEl.src.replace(/\/site-chrome\.js.*$/, '') : '/assets/chrome';

    if (document.querySelector('[data-hero-canvas]') && !document.querySelector('script[src*="hero-runtime.js"]')) {
      var heroScript = document.createElement('script');
      heroScript.src = base + '/hero-runtime.js';
      document.head.appendChild(heroScript);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", inject);
  } else {
    inject();
  }
})();
