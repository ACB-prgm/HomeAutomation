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
DEFAULT_WAKEWORDS_FILE="${SAT_WAKEWORDS_FILE:-$SAT_DIR/config/wakewords.txt}"
INPUT_FILE=""
declare -a PHRASES=()

usage() {
	cat <<EOF
Usage:
  $(basename "$0") --file /path/to/wakewords.txt
  $(basename "$0") "WAKEWORD 1" ["WAKEWORD 2" ...]

Writes custom wakeword phrases to:
  $RAW_FILE
Rebuilds:
  $OUT_FILE

Example:
  $(basename "$0") "HEY CORA" "GLADOS" "SPARK"
  $(basename "$0") --file $DEFAULT_WAKEWORDS_FILE
EOF
}

while [[ $# -gt 0 ]]; do
	case "$1" in
	--file)
		if [[ $# -lt 2 ]]; then
			echo "Missing value for --file" >&2
			usage
			exit 1
		fi
		INPUT_FILE="$2"
		shift 2
		;;
	-h | --help)
		usage
		exit 0
		;;
	*)
		PHRASES+=("$1")
		shift
		;;
	esac
done

if [[ -n "$INPUT_FILE" && "${#PHRASES[@]}" -gt 0 ]]; then
	echo "Use either --file or inline phrases, not both." >&2
	usage
	exit 1
fi

if [[ -z "$INPUT_FILE" && "${#PHRASES[@]}" -eq 0 && -f "$DEFAULT_WAKEWORDS_FILE" ]]; then
	INPUT_FILE="$DEFAULT_WAKEWORDS_FILE"
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

if [[ -n "$INPUT_FILE" ]]; then
	if [[ ! -f "$INPUT_FILE" ]]; then
		echo "Wakewords file not found: $INPUT_FILE" >&2
		exit 1
	fi
	while IFS= read -r phrase || [[ -n "$phrase" ]]; do
		phrase="$(echo "$phrase" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
		if [[ -z "$phrase" || "${phrase:0:1}" == "#" ]]; then
			continue
		fi
		printf "%s\n" "$phrase" >> "$RAW_FILE"
	done < "$INPUT_FILE"
else
	for phrase in "${PHRASES[@]}"; do
		printf "%s\n" "$phrase" >> "$RAW_FILE"
	done
fi

if [[ ! -s "$RAW_FILE" ]]; then
	echo "No wakeword phrases provided." >&2
	exit 1
fi

"$VENV_DIR/bin/sherpa-onnx-cli" text2token \
	--tokens "$TOK_FILE" \
	--tokens-type bpe \
	--bpe-model "$BPE_FILE" \
	"$RAW_FILE" \
	"$OUT_FILE"

echo "Updated wakewords:"
cat "$RAW_FILE"
