#!/usr/bin/env bash
set -euo pipefail

# Config
BASE_DIR="$PWD"
MODEL_DIR="$BASE_DIR/speech/models"
cd "$MODEL_DIR"

download() {
	local url="$1"
	local output="$2"

	if command -v wget >/dev/null 2>&1; then
		wget -O "$output" "$url"
	elif command -v curl >/dev/null 2>&1; then
		curl -L --fail -o "$output" "$url"
	else
		echo "Error: neither wget nor curl is installed" >&2
		exit 1
	fi
}

extract_rename() {
	local filename="$1"

	# Default target dir = filename without .tar.bz2
	local default_name="${filename%.tar.bz2}"
	local target_dir="${2:-$default_name}"

	# Get unique top-level entries
	local roots
	roots="$(
		tar -tjf "$filename" \
		| sed 's|^\./||' \
		| cut -d/ -f1 \
		| sort -u
	)"

	# Extract
	tar -xjf "$filename"

	# Count roots
	local root_count
	root_count="$(echo "$roots" | wc -l | tr -d ' ')"

	# Case 1: single real top-level directory
	if [[ "$root_count" -eq 1 && -d "$roots" ]]; then
		rm -rf "$target_dir"
		mv "$roots" "$target_dir"
	else
		# Case 2: flat or mixed archive
		rm -rf "$target_dir"
		mkdir "$target_dir"

		for item in $roots; do
			[[ -e "$item" ]] && mv "$item" "$target_dir/"
		done
	fi

	rm "$filename"
	
    local test_wavs_dir="$MODEL_DIR/$RENAME/test_wavs"
    if [[ -d "$test_wavs_dir" ]]; then
        rm -rf "$test_wavs_dir"
    fi

}

##############################################
# WAKE WORD DETECTION MODEL
##############################################
FILENAME="sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01.tar.bz2"
URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/${FILENAME}"
RENAME="wakeword"

# Download
download "$URL" "$FILENAME"
# Extract
extract_rename "$FILENAME" "$RENAME"


##############################################
# DENOISER MODEL
##############################################

FILENAME="gtcrn_simple.onnx"
URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/speech-enhancement-models/${FILENAME}"
RENAME="denoiser.onnx"

# Download
download "$URL" "$FILENAME"
# Rename
mv "$FILENAME" "$RENAME"

##############################################
# ASR MODEL
##############################################

FILENAME="sherpa-onnx-nemo-parakeet_tdt_ctc_110m-en-36000-int8.tar.bz2"
URL="https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/${FILENAME}"
RENAME="asr"

# Download
download "$URL" "$FILENAME"
# Extract
extract_rename "$FILENAME" "$RENAME"