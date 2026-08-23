const state = {
    phase: "loading",
    mp: null,
    errors: [],
    stdout: [],
    stderr: [],
};
globalThis.__pydevicesHost = state;

const logElement = () => document.getElementById("log");

function log(line, stream = "stdout") {
    state[stream].push(String(line));
    const element = logElement();
    if (element) {
        element.textContent += `${line}\n`;
        element.scrollTop = element.scrollHeight;
    }
}

function mkdirTree(fs, path) {
    const parts = path.split("/").filter(Boolean);
    let current = "";
    for (const part of parts) {
        current += `/${part}`;
        try {
            fs.mkdir(current);
        } catch (error) {
            if (!String(error).includes("File exists")) throw error;
        }
    }
}

async function fetchBytes(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${response.status} fetching ${url}`);
    return new Uint8Array(await response.arrayBuffer());
}

async function stagePython(mp, plan) {
    const response = await fetch("./python-files.json", {cache: "no-store"});
    if (!response.ok) throw new Error("python-files.json is unavailable");
    const paths = await response.json();
    for (const relative of paths) {
        const utility = relative.startsWith("utils/");
        const source = utility
            ? `./lib/${relative}`
            : `./lib/examples/${relative}`;
        const destination = utility ? `/${relative}` : `/examples/${relative}`;
        mkdirTree(mp.FS, destination.slice(0, destination.lastIndexOf("/")));
        mp.FS.writeFile(destination, await fetchBytes(source));
    }
    for (const name of plan.files) {
        if (!/^[A-Za-z_]\w*$/.test(name)) throw new Error(`invalid staged module: ${name}`);
        mp.FS.writeFile(`/examples/${name}.py`, await fetchBytes(`./staged/${name}.py`));
    }
}

function loaderPlan() {
    const params = new URLSearchParams(location.search);
    const split = (name) => (params.get(name) || "")
        .split(",").map((item) => item.trim()).filter(Boolean);
    const modules = split("modules");
    const manifests = split("manifests");
    let entry = "";
    let kind = "";
    for (const [name] of params) {
        if (name === "modules" && modules.length) {
            [entry] = modules; kind = "module"; break;
        }
        if (name === "manifests" && manifests.length) {
            [entry] = manifests; kind = "manifest"; break;
        }
    }
    return {modules, manifests, deps: split("deps"), files: split("files"), entry, kind, command: params.get("command")};
}

function pythonLiteral(value) {
    return JSON.stringify(String(value));
}

async function installPackages(mp, plan) {
    const index = "https://PyDevices.github.io/mip";
    await mp.runPythonAsync(`
import mip
mip.install("pydevices-desktop", index=${pythonLiteral(index)}, target="/lib")
`);
    for (const dependency of plan.deps) {
        await mp.runPythonAsync(
            `mip.install(${pythonLiteral(dependency)}, index=${pythonLiteral(index)}, target="/lib")`
        );
    }
    for (const manifest of plan.manifests) {
        const url = new URL(`./packages/${manifest}.json`, location.href).href;
        await mp.runPythonAsync(
            `mip.install(${pythonLiteral(url)}, index=${pythonLiteral(index)}, target="/lib")`
        );
    }
}

async function executePlan(mp, plan) {
    await mp.runPythonAsync(`
import os, sys
os.chdir("/")
for _path in ("/lib", "/examples", "/utils"):
    if _path not in sys.path:
        sys.path.insert(0, _path)
`);
    if (plan.command !== null) {
        await mp.runPythonAsync(plan.command);
    } else if (plan.entry) {
        await mp.runPythonAsync(`__import__(${pythonLiteral(plan.entry)})`);
    }
}

async function createRuntime() {
    const {loadMicroPython} = await import("/vendor/micropython/micropython.mjs");
    return loadMicroPython({
        stdout: (line) => log(line, "stdout"),
        stderr: (line) => log(line, "stderr"),
        heapsize: 16 * 1024 * 1024,
    });
}

async function boot() {
    state.phase = "loading";
    document.body.dataset.runtimeState = "loading";
    const plan = loaderPlan();
    try {
        const mp = state.mp || await createRuntime();
        state.mp = mp;
        await stagePython(mp, plan);
        await installPackages(mp, plan);
        await executePlan(mp, plan);
        state.phase = "ready";
        document.body.dataset.runtimeState = "ready";
        dispatchEvent(new CustomEvent("pydevices-ready", {detail: plan}));
    } catch (error) {
        const detail = String(error?.stack || error);
        state.errors.push(detail);
        log(detail, "stderr");
        state.phase = "failed";
        document.body.dataset.runtimeState = "failed";
        dispatchEvent(new CustomEvent("pydevices-failed", {detail}));
    }
}

state.runSource = async (source) => {
    if (!state.mp) throw new Error("runtime is not ready");
    return state.mp.runPythonAsync(source);
};
state.reset = async () => {
    if (state.mp) state.mp.softReset();
    const element = logElement();
    if (element) element.textContent = "";
    state.stdout.length = 0;
    state.stderr.length = 0;
    state.errors.length = 0;
    await boot();
};
state.enableAudio = async (microphone = false) => {
    if (!globalThis.Module?.pydevicesBridge) throw new Error("bridge is not ready");
    const permission = await Promise.race([
        Module.pydevicesBridge.enableAudio(microphone),
        new Promise((_, reject) => setTimeout(() => reject(new Error("browser audio permission timed out")), 5000)),
    ]);
    if (!permission.audio || (microphone && !permission.microphone)) {
        throw new Error(microphone ? "microphone permission was not granted" : "audio permission was not granted");
    }
    return permission;
};

async function enableFromControl(button, microphone) {
    button.disabled = true;
    try {
        state.permissions = await state.enableAudio(microphone);
        button.textContent = microphone ? "Microphone Enabled" : "Audio Enabled";
        button.dataset.enabled = "true";
    } catch (error) {
        log(String(error?.stack || error), "stderr");
        button.disabled = false;
    }
}

const audioButton = document.getElementById("enable-audio");
const microphoneButton = document.getElementById("enable-microphone");
audioButton?.addEventListener("click", () => enableFromControl(audioButton, false));
microphoneButton?.addEventListener("click", () => enableFromControl(microphoneButton, true));
document.getElementById("reset-runtime")?.addEventListener("click", () => state.reset());

await boot();
