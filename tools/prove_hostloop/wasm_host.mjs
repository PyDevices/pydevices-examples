// Drive the real PyScript micropython.wasm build the way a browser page does:
// load the interpreter, mount the source trees, run the script, then RETURN to
// the host event loop. Nothing here pumps the app -- if ticks keep arriving
// after "script body ends here", the ambient strategy works.
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { readdirSync, readFileSync, statSync } from "node:fs";

const HERE = dirname(fileURLToPath(import.meta.url));
const PD = process.env.PD || join(HERE, "../../../pydevices");
const { loadMicroPython } = await import(join(HERE, "../../../pydevices/bin/micropython.mjs"));

const mp = await loadMicroPython({
    stdout: (line) => console.log(line),
    heapsize: 16 * 1024 * 1024,
});

// This build has no NODEFS, so copy the trees into MEMFS instead.
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
copyTree(HERE, "/demo");
mp.runPython(`import sys
sys.path.insert(0, "/demo")
sys.path.insert(0, "/utils")
sys.path.insert(0, "/lib")`);

const script = process.argv[2] || "demo_noloop.py";
// A browser page runs the script and returns; the page's event loop lives on.
await mp.runPythonAsync(readFileSync(join(HERE, script), "utf8"));
console.log("[host] script returned to the JS event loop; not pumping anything");

// Keep the node process alive the way a browser page stays open. The app must
// finish on its own, driven only by the interpreter's asyncio-over-setTimeout.
await new Promise((r) => setTimeout(r, 3000));
console.log("[host] done");
