/*! pydevices-examples gallery loaders — hide the loading row when PyScript is ready or failed */
(function () {
  var interpreter = document.body && document.body.getAttribute('data-loader-interpreter');
  if (interpreter !== 'mpy' && interpreter !== 'py') {
    return;
  }

  var btn = document.getElementById('run-btn');
  var spin = document.querySelector('#loading .spinner');
  var status = document.getElementById('status');
  var readyEvent = interpreter === 'mpy' ? 'mpy:ready' : 'py:ready';
  var doneEvent = interpreter === 'mpy' ? 'mpy:done' : 'py:done';
  var polls = 0;
  var maxPolls = 800; // ~120s at 150ms — slow WASM / first visit
  var timer = null;

  function hideSpinner() {
    if (spin) {
      spin.style.display = 'none';
    }
  }

  function interpreterFailed() {
    hideSpinner();
    if (!btn || !btn.disabled) {
      return;
    }
    if (status && /Loading/i.test(status.textContent)) {
      status.textContent = 'Interpreter failed — see console output below.';
    }
  }

  function interpreterReady() {
    hideSpinner();
  }

  function stopPolling() {
    if (timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  }

  addEventListener(readyEvent, function () {
    if (status && /Loading/i.test(status.textContent)) {
      status.textContent =
        interpreter === 'mpy' ? 'Starting MicroPython…' : 'Starting Python…';
    }
  });

  addEventListener(doneEvent, function () {
    stopPolling();
    if (btn && !btn.disabled) {
      interpreterReady();
    } else {
      interpreterFailed();
    }
  });

  timer = setInterval(function () {
    polls += 1;
    if (btn && !btn.disabled) {
      stopPolling();
      interpreterReady();
    } else if (polls >= maxPolls) {
      stopPolling();
      interpreterFailed();
    }
  }, 150);
})();
