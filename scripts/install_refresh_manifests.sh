#!/usr/bin/env bash
# Refresh install manifests derived from lib/ (packages/*.json and pydevices-examples.toml).
#
# Usage:
#   ./scripts/install_refresh_manifests.sh           # apply updates (default)
#   ./scripts/install_refresh_manifests.sh --audit   # show drift vs lib/, then restore
#   ./scripts/install_refresh_manifests.sh --help

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

EXAMPLES_TOML="pydevices-examples.toml"

GENERATED_LIB_PACKAGES=(
    packages/utils.json
    packages/examples.json
)

MANUAL_PACKAGES=(
    packages/micropython-micro-gui.json
    packages/micropython-nano-gui.json
    packages/micropython-touch.json
)

usage() {
    cat <<'EOF'
Usage: ./scripts/install_refresh_manifests.sh [OPTION]

Regenerate files derived from lib/ for GitHub installs and PyScript.

Options:
  (none)        Run install_gen_manifests.py and generate_pyscript_filesystem_toml.py.
  --audit, -a   Compare generated output to the working tree, print a summary,
                then restore the original files (no changes kept).
  --help, -h    Show this message.

Generated artifacts:
  packages/{utils,examples}.json
  packages/<example-subdir>.json for each lib/examples/*/ (except personal)
  pydevices-examples.toml (PyScript filesystem mapping)
  .site/pyscript/pydevices-examples.toml (symlink)
  .site/pyscript/packages (symlink)
  .site/pyscript/lib (symlink)
EOF
}

find_generator_script() {
    # From a git worktree the sibling checkouts sit beside the main checkout,
    # not beside this directory.
    local main_root
    main_root="$(dirname "$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null || echo "$PWD/.git")")"
    if [[ -f "../dotgithub/scripts/generate_pyscript_filesystem_toml.py" ]]; then
        echo "../dotgithub/scripts/generate_pyscript_filesystem_toml.py"
    elif [[ -f "$main_root/../dotgithub/scripts/generate_pyscript_filesystem_toml.py" ]]; then
        echo "$main_root/../dotgithub/scripts/generate_pyscript_filesystem_toml.py"
    elif [[ -f ".pydevices-publishing-tools/scripts/generate_pyscript_filesystem_toml.py" ]]; then
        echo ".pydevices-publishing-tools/scripts/generate_pyscript_filesystem_toml.py"
    else
        echo ""
    fi
}

run_toml_generator() {
    local check_flag="${1:-}"
    local script
    script="$(find_generator_script)"
    if [[ -z "$script" ]]; then
        echo "Note: generate_pyscript_filesystem_toml.py not found locally; skipping TOML generation."
        return 0
    fi
    local cmd=(
        python3 "$script"
        --repository "PyDevices/pydevices-examples"
        --output "$EXAMPLES_TOML"
        --source "lib/utils=/utils"
        --source "lib/examples=/examples"
    )
    if [[ -n "$check_flag" ]]; then
        cmd+=(--check)
    fi
    "${cmd[@]}"
}

list_package_diff() {
    local old_path="$1" new_path="$2"
    python3 - "$old_path" "$new_path" <<'PY'
import json
import sys

def dest_paths(pkg_data):
    return {entry[0] for entry in pkg_data.get("urls", [])}

old_path, new_path = sys.argv[1], sys.argv[2]
with open(old_path) as f:
    old = json.load(f)
with open(new_path) as f:
    new = json.load(f)
old_set = dest_paths(old)
new_set = dest_paths(new)
added = sorted(new_set - old_set)
removed = sorted(old_set - new_set)
if not added and not removed:
    sys.exit(0)
name = old_path.rsplit("/", 1)[-1]
print(f"\n{name}:")
for path in added:
    print(f"  + {path}")
for path in removed:
    print(f"  - {path}")
PY
}

example_package_jsons() {
    find packages -maxdepth 1 -type f -name '*.json' ! -name 'examples.json' \
        | while read -r path; do
            stem="${path#packages/}"
            stem="${stem%.json}"
            case " ${GENERATED_LIB_PACKAGES[*]} ${MANUAL_PACKAGES[*]} " in
                *" packages/${stem}.json "*) continue ;;
            esac
            if [[ -d "lib/examples/${stem}" ]]; then
                echo "$path"
            fi
        done | sort
}

audit_repo_packages() {
    local tmp
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' RETURN

    echo "Backing up generated files to $tmp"
    cp -a packages "$tmp/"
    if [[ -f "$EXAMPLES_TOML" ]]; then
        cp "$EXAMPLES_TOML" "$tmp/$EXAMPLES_TOML"
    fi

    echo "Running scripts/install_gen_manifests.py..."
    python3 scripts/install_gen_manifests.py

    echo "Auditing $EXAMPLES_TOML..."
    run_toml_generator "--check"

    local generated=("${GENERATED_LIB_PACKAGES[@]}")
    local example_pkgs=()
    mapfile -t example_pkgs < <(example_package_jsons)
    generated+=("${example_pkgs[@]}")

    echo
    echo "=== File-level diff ==="
    local changed=0
    for path in "${generated[@]}"; do
        if ! diff -q "$tmp/packages/${path#packages/}" "$path" >/dev/null 2>&1; then
            echo "changed: $path"
            changed=1
        fi
    done
    if [[ -f "$tmp/$EXAMPLES_TOML" ]] && ! diff -q "$tmp/$EXAMPLES_TOML" "$EXAMPLES_TOML" >/dev/null 2>&1; then
        echo "changed: $EXAMPLES_TOML"
        changed=1
    fi

    if [[ "$changed" -eq 0 ]]; then
        echo "No differences — generated files match lib/."
    fi

    echo
    echo "=== Package entry diff (dest paths) ==="
    for path in "${generated[@]}"; do
        list_package_diff \
            "$tmp/packages/${path#packages/}" \
            "$path" || true
    done

    echo
    echo "Restoring original files (audit mode does not keep changes)."
    rm -rf packages
    cp -a "$tmp/packages" packages/
    if [[ -f "$tmp/$EXAMPLES_TOML" ]]; then
        cp "$tmp/$EXAMPLES_TOML" "$EXAMPLES_TOML"
    fi

    if [[ "$changed" -ne 0 ]]; then
        echo
        echo "ERROR: generated files are stale — run ./scripts/install_refresh_manifests.sh"
        exit 1
    fi
}

regenerate_repo_packages() {
    echo "Running scripts/install_gen_manifests.py..."
    python3 scripts/install_gen_manifests.py

    echo "Generating $EXAMPLES_TOML..."
    run_toml_generator ""

    echo
    echo "Updated lib packages:"
    for path in "${GENERATED_LIB_PACKAGES[@]}"; do
        echo "  $path"
    done
    echo "Updated example packages:"
    example_package_jsons | while read -r path; do
        echo "  $path"
    done
    echo "  $EXAMPLES_TOML"
    echo "  .site/pyscript/pydevices-examples.toml (symlink)"
    echo "  .site/pyscript/packages (symlink)"
    echo "  .site/pyscript/lib (symlink)"
    echo
    echo "Remember to review git diff. Manual packages were not changed:"
    for path in "${MANUAL_PACKAGES[@]}"; do
        echo "  $path"
    done
}

case "${1:-}" in
    --audit|-a)
        audit_repo_packages
        ;;
    --help|-h)
        usage
        ;;
    "" )
        regenerate_repo_packages
        ;;
    *)
        echo "Unknown option: $1" >&2
        usage >&2
        exit 1
        ;;
esac
