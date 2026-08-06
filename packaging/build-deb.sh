#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_SOURCE="$ROOT_DIR/TuxGuard(1.0.0)"
VENV_SOURCE="$ROOT_DIR/.venv"
CONTROL_TEMPLATE="$ROOT_DIR/packaging/debian/control.in"
LAUNCHER="$ROOT_DIR/packaging/debian/tuxguard"
DESKTOP_FILE="$ROOT_DIR/packaging/debian/tuxguard.desktop"
OUTPUT_PATH="${1:-$ROOT_DIR/tuxGuard.deb}"

if [[ ! -x "$VENV_SOURCE/bin/python" ]]; then
    printf 'Missing runtime environment: %s\n' "$VENV_SOURCE" >&2
    exit 1
fi
if [[ ! -f "$APP_SOURCE/tuxguard_refactored.py" ]]; then
    printf 'Missing application source: %s\n' "$APP_SOURCE" >&2
    exit 1
fi

VERSION="$(sed -n 's/^[[:space:]]*APP_VERSION[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "$APP_SOURCE/config.py" | head -n 1)"
ARCHITECTURE="$(dpkg --print-architecture)"
if [[ -z "$VERSION" ]]; then
    printf 'Could not determine the application version.\n' >&2
    exit 1
fi

OUTPUT_PATH="$(realpath -m "$OUTPUT_PATH")"
mkdir -p "$(dirname "$OUTPUT_PATH")"

STAGE_DIR="$(mktemp -d)"
PACKAGE_ROOT="$STAGE_DIR/tuxguard"
APP_DESTINATION="$PACKAGE_ROOT/opt/tuxguard"
trap 'rm -rf "$STAGE_DIR"' EXIT

install -d "$PACKAGE_ROOT/DEBIAN" "$APP_DESTINATION" \
    "$PACKAGE_ROOT/usr/bin" "$PACKAGE_ROOT/usr/share/applications"

# Package only immutable application assets. User credentials, databases and
# runtime settings are created under XDG_STATE_HOME on the first application run.
tar \
    --exclude='./.pytest_cache' \
    --exclude='./__pycache__' \
    --exclude='./tests' \
    --exclude='./install.sh' \
    --exclude='./uninstall.sh' \
    --exclude='./pytest.ini' \
    --exclude='./face_recognition.db' \
    --exclude='./master_credentials.json' \
    --exclude='./runtime_settings.json' \
    --exclude='./*.log' \
    -C "$APP_SOURCE" -cf - . | tar -C "$APP_DESTINATION" -xf -

# The target virtual environment is intentionally bundled. apt only resolves
# system libraries; package installation never invokes pip or requires network access.
cp -a "$VENV_SOURCE/." "$APP_DESTINATION/.venv/"
find "$APP_DESTINATION/.venv" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$APP_DESTINATION/.venv" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
rm -rf "$APP_DESTINATION/.venv/include"

install -m 0755 "$LAUNCHER" "$PACKAGE_ROOT/usr/bin/tuxguard"
install -m 0644 "$DESKTOP_FILE" "$PACKAGE_ROOT/usr/share/applications/tuxguard.desktop"

sed \
    -e "s/@VERSION@/$VERSION/g" \
    -e "s/@ARCHITECTURE@/$ARCHITECTURE/g" \
    "$CONTROL_TEMPLATE" > "$PACKAGE_ROOT/DEBIAN/control"
printf '\n' >> "$PACKAGE_ROOT/DEBIAN/control"

dpkg-deb --root-owner-group --build "$PACKAGE_ROOT" "$OUTPUT_PATH"
printf 'Created Debian package: %s\n' "$OUTPUT_PATH"