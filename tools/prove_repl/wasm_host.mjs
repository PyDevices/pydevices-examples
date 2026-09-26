// Drive the direct MicroPython WebAssembly build the way a browser page does:
// load the interpreter, mount the pydevices tree, run a timer script that ends,
// then RETURN to the JS event loop. The page loop is the wake source; nothing
// here pumps. Two reads a second apart must show the tick count growing, and
// multimer.report() must answer.
//
// usage: node wasm_host.mjs [path/to/micropython.mjs]
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { readdirSync, readFileSync, statSync } from "node:fs";

const HERE = dirname(fileURLToPath(import.meta.url));
const PD = process.env.PD || join(HERE, "../../../pydevices");
const MJS = process.argv[2] || join(PD, "bin/micropython.mjs");
const { loadMicroPython } = await import(MJS);

let captured = "";
const mp = await loadMicroPython({
    stdout: (line) => { captured += line + "\n"; console.log(line); },
    heapsize: 16 * 1024 * 1024,
});

function copyTree(src, dst) {
    mp.FS.mkdir(dst);
    for (const name of readdirSync(src)) {
        if (name === "__pycache__" || name.startsWith(".")) continue;
        const s = join(src, name), d = dst + "/" + name;
        if (statSync(s).isDirectory()) copyTree(s, d);
        else if (name.endsWith(".py")) mp.FS.writeFile(d, readFileSync(s));
    }
}
copyTree(join(PD, "lib"), "/lib");
copyTree(join(PD, "utils"), "/utils");
mp.runPython(`import sys
sys.path.insert(0, "/utils")
sys.path.insert(0, "/lib")`);

await mp.runPythonAsync(readFileSync(join(HERE, "demo_timers.py"), "utf8"));
console.log("[host] script returned to the JS event loop; not pumping anything");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
await sleep(1000);
mp.runPython("print('COUNT1', len(ticks), len(slow))");
await sleep(1000);
mp.runPython("print('COUNT2', len(ticks), len(slow))");
mp.runPython("import multimer; multimer.report()");

const c1 = captured.match(/COUNT1 (\d+) (\d+)/), c2 = captured.match(/COUNT2 (\d+) (\d+)/);
const grew = c1 && c2 && (+c2[1] > +c1[1] + 30) && (+c2[2] > +c1[2]);
const reported = /multimer on micropython\/webassembly/.test(captured) && /name='fast'/.test(captured);
console.log((grew ? "PASS" : "FAIL") + " wasm: ticks grow while the page loop idles");
console.log((reported ? "PASS" : "FAIL") + " wasm: report() answers");
process.exit((grew ? 0 : 1) + (reported ? 0 : 1));
