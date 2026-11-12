#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
IMAGE=${IMAGE:-cockpit-process360:customer-20261103}
PLATFORM=${PLATFORM:-linux/amd64}
ONTOLOGY=${ONTOLOGY:-}
SEED=${SEED:-}
WHEELS=${WHEELS:-}
OUTPUT=${OUTPUT:-}

usage() {
  cat <<'USAGE'
Usage: scripts/build_customer_image.sh --ontology DIR --wheels DIR [--seed DIR] [options]

Options:
  --ontology DIR    Directory containing catalog.json, manifest.json and the source Excel.
  --seed DIR        Optional directory containing frozen-annual.json. Without it the
                    customer page starts with no AI cards; each stage is published
                    after its first manual analysis.
  --wheels DIR      Offline wheelhouse for linux/amd64.
  --image NAME      Image tag to build. Default: cockpit-process360:customer-20261103
  --platform ARCH   Build platform. Default: linux/amd64
  --output FILE     Optional docker-save tar path. Default: <cwd>/images/cockpit-linux-amd64.tar
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --ontology) ONTOLOGY=$2; shift 2 ;;
    --seed) SEED=$2; shift 2 ;;
    --wheels) WHEELS=$2; shift 2 ;;
    --image) IMAGE=$2; shift 2 ;;
    --platform) PLATFORM=$2; shift 2 ;;
    --output) OUTPUT=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[ -n "$ONTOLOGY" ] && [ -n "$WHEELS" ] || {
  usage >&2
  echo "missing required build context" >&2
  exit 2
}
[ -f "$ONTOLOGY/catalog.json" ] || { echo "missing $ONTOLOGY/catalog.json" >&2; exit 2; }
[ -f "$ONTOLOGY/manifest.json" ] || { echo "missing $ONTOLOGY/manifest.json" >&2; exit 2; }
if [ -n "$SEED" ]; then
  [ -f "$SEED/frozen-annual.json" ] || { echo "missing $SEED/frozen-annual.json" >&2; exit 2; }
  set -- --build-context "cockpit-seed=$SEED"
else
  echo "no --seed: image starts without published AI cards" >&2
  set --
fi
[ -d "$WHEELS" ] || { echo "missing wheelhouse: $WHEELS" >&2; exit 2; }
OUTPUT=${OUTPUT:-"$PWD/images/cockpit-linux-amd64.tar"}

docker buildx build --platform "$PLATFORM" \
  --build-context "wheelhouse=$WHEELS" \
  "$@" \
  --build-context "builtin-ontology=$ONTOLOGY" \
  -f "$ROOT/deploy/customer/Dockerfile" \
  -t "$IMAGE" --load "$ROOT"

mkdir -p "$(dirname -- "$OUTPUT")"
tmp="$OUTPUT.$$.tmp"
docker save "$IMAGE" -o "$tmp"
mv "$tmp" "$OUTPUT"
echo "image=$IMAGE"
echo "tar=$OUTPUT"
echo "sha256=$(shasum -a 256 "$OUTPUT" | awk '{print $1}')"
