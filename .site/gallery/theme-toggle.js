/*! PyDevices shared dark/light theme toggle */
(function () {
  var STORAGE_KEY = "pydevices-theme";
  var root = document.documentElement;

  function currentTheme() {
    return root.getAttribute("data-theme") === "light" ? "light" : "dark";
  }

  function applyTheme(theme) {
    if (theme === "light") {
      root.setAttribute("data-theme", "light");
    } else {
      root.removeAttribute("data-theme");
    }
  }

  function applyThemeToFrames(theme) {
    document.querySelectorAll("iframe").forEach(function (frame) {
      try {
        var frameRoot = frame.contentDocument && frame.contentDocument.documentElement;
        if (!frameRoot) {
          return;
        }
        if (theme === "light") {
          frameRoot.setAttribute("data-theme", "light");
        } else {
          frameRoot.removeAttribute("data-theme");
        }
      } catch (error) {
        // Cross-origin frames manage their own theme.
      }
    });
  }

  function init() {
    var toggle = document.getElementById("theme-toggle");
    if (!toggle) {
      return;
    }
    toggle.addEventListener("click", function () {
      var next = currentTheme() === "light" ? "dark" : "light";
      applyTheme(next);
      applyThemeToFrames(next);
      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch (error) {
        // The theme still changes for this visit when storage is unavailable.
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.addEventListener("storage", function (event) {
    if (event.key === STORAGE_KEY) {
      applyTheme(event.newValue === "light" ? "light" : "dark");
    }
  });
})();
