#!/usr/bin/env bash
# Regenerate IDE type stubs for the core PyDevices packages into tools/typings/.
#
# Usage:
#   ./scripts/gen_package_pyi.sh
#   ./scripts/gen_package_pyi.sh --help
#
# Requires the repo-root .venv (mypy / stubgen). Output is committed under
# tools/typings/{displaydev,appdev,multimer}/ and the single-module stubs
# (events, keys, boarddev) for stubPath.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PACKAGES=(displaydev appdev multimer)
MODULES=(events keys boarddev)
OUT=tools/typings
STUBGEN="${ROOT}/.venv/bin/stubgen"
PYTHON="${ROOT}/.venv/bin/python"

usage() {
    cat <<'EOF'
Usage: ./scripts/gen_package_pyi.sh

Regenerate mypy stubgen .pyi trees for displaydev, appdev,
multimer, events, keys, and boarddev into tools/typings/ (Pylance / pyright stubPath).

(source is gitignored; public API is pygraphics.FrameBuffer).
EOF
}

case "${1:-}" in
    --help|-h)
        usage
        exit 0
        ;;
    "")
        ;;
    *)
        echo "Unknown option: $1" >&2
        usage >&2
        exit 1
        ;;
esac

if [[ ! -x "$STUBGEN" ]]; then
    echo "error: missing $STUBGEN — create .venv and pip install mypy" >&2
    exit 1
fi

for pkg in "${PACKAGES[@]}"; do
    rm -rf "${OUT}/${pkg}"
done
rm -rf "${OUT}/displaysys"
for mod in "${MODULES[@]}"; do
    rm -f "${OUT}/${mod}.pyi"
done

HW="$(cd "${ROOT}/../pydevices" 2>/dev/null && pwd || true)"
export PYTHONPATH="${ROOT}/lib/lib:${ROOT}/lib/utils${PYTHONPATH:+:$PYTHONPATH}"
if [[ -n "$HW" ]]; then
    export PYTHONPATH="${HW}/lib:${HW}/utils:${HW}/drivers/display:${PYTHONPATH}"
fi

echo "Running stubgen → ${OUT}/ …"
"$STUBGEN" --ignore-errors -o "$OUT" \
    -p displaydev -p appdev -p multimer \
    -m events -m keys -m boarddev

# Gitignored generated module; public FrameBuffer lives in _framebuf_plus.

# stubgen misses lazy ``multimer.asyncio`` (``__getattr__``); declare it explicitly.
MULTIMER_INIT="${OUT}/multimer/__init__.pyi"
if [[ -f "$MULTIMER_INIT" ]] && ! grep -q '^asyncio:' "$MULTIMER_INIT"; then
    "$PYTHON" - "$MULTIMER_INIT" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
needle = "\n__all__ = "
if "asyncio: Incomplete" not in text and needle in text:
    text = text.replace(
        needle,
        "\nfrom _typeshed import Incomplete\n\nasyncio: Incomplete\n" + needle,
        1,
    )
text = "\n".join(
    line
    for line in text.splitlines()
    if line.strip() not in ("# Names in __all__ with no definition:", "#   asyncio")
) + ("\n" if text.endswith("\n") else "")
path.write_text(text, encoding="utf-8")
PY
fi

echo
echo "Updated:"
for pkg in "${PACKAGES[@]}"; do
    count="$("$PYTHON" -c "from pathlib import Path; print(sum(1 for _ in Path('${OUT}/${pkg}').rglob('*.pyi')))")"
    echo "  ${OUT}/${pkg}/ (${count} .pyi)"
done
for mod in "${MODULES[@]}"; do
    echo "  ${OUT}/${mod}.pyi"
done
