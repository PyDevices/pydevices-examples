/*! Keep the interpreter console locked to the display card's dimensions. */
(function () {
  var device = document.querySelector(".play-area .device");
  var panel = document.querySelector(".play-area .console-panel");
  if (!device) {
    return;
  }

  var showConsole =
    new URLSearchParams(window.location.search).get("console") === "true";
  var toggle = document.querySelector(".console-toggle");
  var standalone = window.parent === window;
  document.body.classList.add(standalone ? "interpreter-standalone" : "interpreter-embedded");

  function applyConsoleState(visible) {
    showConsole = visible;
    document.body.classList.toggle("interpreter-with-console", visible);
    document.body.classList.toggle("interpreter-without-console", !visible);
    if (panel) {
      panel.hidden = !visible;
      panel.style.width = visible && lastWidth > 0 ? lastWidth + "px" : "";
      panel.style.height = visible && lastHeight > 0 ? lastHeight + "px" : "";
    }
    if (toggle) {
      toggle.textContent = visible ? "Hide console" : "Show console";
      toggle.setAttribute("aria-expanded", visible ? "true" : "false");
    }
    var url = new URL(window.location.href);
    if (visible) {
      url.searchParams.set("console", "true");
    } else {
      url.searchParams.delete("console");
    }
    window.history.replaceState(null, "", url);
    syncConsoleSize();
  }

  var lastWidth = -1;
  var lastHeight = -1;

  function reportHeight() {
    requestAnimationFrame(function () {
      var main = document.querySelector(".loader-main");
      var height = main ? Math.ceil(main.getBoundingClientRect().bottom) : 0;
      if (window.parent !== window && height > 0) {
        var width = Math.ceil(device.getBoundingClientRect().width);
        window.parent.postMessage(
          { type: "pydevices-examples-interpreter-size", height: height, width: width },
          window.location.origin
        );
      }
    });
  }

  function syncConsoleSize() {
    var rect = device.getBoundingClientRect();
    var width = Math.round(rect.width);
    var height = Math.round(rect.height);
    if (width <= 0 || height <= 0) {
      reportHeight();
      return;
    }
    if (!showConsole || !panel) {
      lastWidth = width;
      lastHeight = height;
      if (panel && showConsole) {
        panel.style.width = width + "px";
      }
      reportHeight();
      return;
    }
    if (standalone) {
      if (lastWidth < 0) {
        panel.style.width = width + "px";
        lastWidth = width;
      }
      if (height !== lastHeight) {
        panel.style.height = height + "px";
        lastHeight = height;
      }
      reportHeight();
      return;
    }
    if (width === lastWidth) {
      reportHeight();
      return;
    }
    lastWidth = width;
    lastHeight = height;
    panel.style.width = width + "px";
    panel.style.height = height + "px";
    reportHeight();
  }

  applyConsoleState(showConsole);
  if (toggle) {
    toggle.addEventListener("click", function () {
      applyConsoleState(!showConsole);
    });
  }
  syncConsoleSize();
  window.addEventListener("resize", syncConsoleSize);
  window.addEventListener("load", reportHeight);
  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(syncConsoleSize).observe(device);
  }
})();
