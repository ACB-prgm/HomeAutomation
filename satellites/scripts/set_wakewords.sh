#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SAT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="${SAT_VENV_DIR:-$SAT_DIR/../sat_venv}"
MODEL_DIR="$SAT_DIR/speech/models"
WW_DIR="$MODEL_DIR/wakeword"
KW_DIR="$MODEL_DIR/wakeword_keywords"
RAW_FILE="$KW_DIR/keywords_raw.txt"
TOK_FILE="$WW_DIR/tokens.txt"
BPE_FILE="$WW_DIR/bpe.model"
OUT_FILE="$KW_DIR/keywords.txt"

usage() {
	cat <<EOF
Usage: $(basename "$0") "WAKEWORD 1" ["WAKEWORD 2" ...]

Writes custom wakeword phrases to:
  $RAW_FILE
Rebuilds:
  $OUT_FILE

Example:
  $(basename "$0") "HEY CORA" "GLADOS" "SPARK"
EOF
}

if [[ $# -lt 1 ]]; then
	usage
	exit 1
fi

if [[ ! -x "$VENV_DIR/bin/sherpa-onnx-cli" ]]; then
	echo "Missing sherpa-onnx-cli in $VENV_DIR/bin" >&2
	exit 1
fi

if [[ ! -f "$TOK_FILE" || ! -f "$BPE_FILE" ]]; then
	echo "Missing wakeword assets under $WW_DIR. Run satellite bootstrap first." >&2
	exit 1
fi

mkdir -p "$KW_DIR"
: > "$RAW_FILE"
for phrase in "$@"; do
	printf "%s\n" "$phrase" >> "$RAW_FILE"
done

"$VENV_DIR/bin/sherpa-onnx-cli" text2token \
	--tokens "$TOK_FILE" \
	--tokens-type bpe \
	--bpe-model "$BPE_FILE" \
	"$RAW_FILE" \
	"$OUT_FILE"

echo "Updated wakewords:"
cat "$RAW_FILE"
