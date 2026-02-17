#!/usr/bin/env bash
set -euo pipefail

SERVICE="${SERVICE:-home-satellite.service}"
DURATION_S="${DURATION_S:-1200}"
INTERVAL_S="${INTERVAL_S:-15}"

usage() {
	cat <<EOF
Usage: $(basename "$0") [options]

Run a timed voice-pipeline validation capture and summarize runtime behavior.

Options:
  --service <name>      systemd service name (default: $SERVICE)
  --duration <seconds>  test duration (default: $DURATION_S)
  --interval <seconds>  sample interval for temp/cpu (default: $INTERVAL_S)
  -h, --help            Show this help text
EOF
}

while [[ $# -gt 0 ]]; do
	case "$1" in
	--service)
		SERVICE="$2"
		shift 2
		;;
	--duration)
		DURATION_S="$2"
		shift 2
		;;
	--interval)
		INTERVAL_S="$2"
		shift 2
		;;
	-h | --help)
		usage
		exit 0
		;;
	*)
		echo "Unknown option: $1" >&2
		usage
		exit 1
		;;
	esac
done

if ! command -v systemctl >/dev/null 2>&1; then
	echo "systemctl not found." >&2
	exit 1
fi

if ! systemctl is-active --quiet "$SERVICE"; then
	echo "Service is not active: $SERVICE" >&2
	exit 1
fi

if command -v rg >/dev/null 2>&1; then
	filter_count() { rg -c "$1"; }
	filter_lines() { rg -n "$1"; }
else
	filter_count() { grep -E -c "$1"; }
	filter_lines() { grep -E -n "$1"; }
fi

START_TS="$(date '+%Y-%m-%d %H:%M:%S')"
END_EPOCH=$(( $(date +%s) + DURATION_S ))
TMP_SAMPLES="$(mktemp)"
trap 'rm -f "$TMP_SAMPLES"' EXIT

echo "[voice-test] Start: $START_TS"
echo "[voice-test] Service: $SERVICE"
echo "[voice-test] Duration: ${DURATION_S}s; sample interval: ${INTERVAL_S}s"
echo "[voice-test] Speak wakewords naturally during the window."

while [[ "$(date +%s)" -lt "$END_EPOCH" ]]; do
	NOW="$(date '+%Y-%m-%d %H:%M:%S')"
	TEMP_C="-"
	if command -v vcgencmd >/dev/null 2>&1; then
		TEMP_C="$(vcgencmd measure_temp 2>/dev/null | sed -E "s/^temp=([0-9.]+)'C$/\1/" || true)"
		[[ -z "$TEMP_C" ]] && TEMP_C="-"
	fi

	CPU_PCT="$(ps -eo args=,%cpu= | awk '/satellites\/main\.py/ {sum+=$NF; n++} END {if (n==0) print "0.0"; else printf "%.2f", sum}')"
	printf "%s %s %s\n" "$NOW" "$TEMP_C" "$CPU_PCT" >> "$TMP_SAMPLES"
	sleep "$INTERVAL_S"
done

END_TS="$(date '+%Y-%m-%d %H:%M:%S')"
LOGS="$(journalctl -u "$SERVICE" --since "$START_TS" --until "$END_TS" --no-pager 2>/dev/null || true)"

WAKE_COUNT="$(printf "%s\n" "$LOGS" | filter_count "Wakeword detected" || true)"
UTT_COUNT="$(printf "%s\n" "$LOGS" | filter_count "Utterance captured" || true)"
STATE_WAKE_COUNT="$(printf "%s\n" "$LOGS" | filter_count "Speech state: wake_detected" || true)"
GATE_OPEN_COUNT="$(printf "%s\n" "$LOGS" | filter_count "Wake gate transition.*gate_open=true" || true)"
GATE_CLOSE_COUNT="$(printf "%s\n" "$LOGS" | filter_count "Wake gate transition.*gate_open=false" || true)"
LED_LISTEN_COUNT="$(printf "%s\n" "$LOGS" | filter_count "led_state=listening" || true)"

SAMPLE_COUNT="$(wc -l < "$TMP_SAMPLES" | tr -d ' ')"
TEMP_STATS="$(awk '{if ($2 != "-") {sum+=$2; n++; if (min=="" || $2<min) min=$2; if (max=="" || $2>max) max=$2}} END {if (n==0) print "- - -"; else printf "%.2f %.2f %.2f", sum/n, min, max}' "$TMP_SAMPLES")"
CPU_STATS="$(awk '{sum+=$3; n++; if (min=="" || $3<min) min=$3; if (max=="" || $3>max) max=$3} END {if (n==0) print "0.00 0.00 0.00"; else printf "%.2f %.2f %.2f", sum/n, min, max}' "$TMP_SAMPLES")"

TEMP_AVG="$(echo "$TEMP_STATS" | awk '{print $1}')"
TEMP_MIN="$(echo "$TEMP_STATS" | awk '{print $2}')"
TEMP_MAX="$(echo "$TEMP_STATS" | awk '{print $3}')"
CPU_AVG="$(echo "$CPU_STATS" | awk '{print $1}')"
CPU_MIN="$(echo "$CPU_STATS" | awk '{print $2}')"
CPU_MAX="$(echo "$CPU_STATS" | awk '{print $3}')"

echo
echo "=== Voice Pipeline Test Summary ==="
echo "Start: $START_TS"
echo "End:   $END_TS"
echo "Samples: $SAMPLE_COUNT"
echo "Temp C avg/min/max: $TEMP_AVG / $TEMP_MIN / $TEMP_MAX"
echo "CPU % avg/min/max:  $CPU_AVG / $CPU_MIN / $CPU_MAX"
echo "Wakeword detections: $WAKE_COUNT"
echo "Utterances captured: $UTT_COUNT"
echo "State wake events:   $STATE_WAKE_COUNT"
echo "Gate opens/closes:   $GATE_OPEN_COUNT / $GATE_CLOSE_COUNT"
echo "LED listening logs:  $LED_LISTEN_COUNT"

echo
echo "Recent relevant logs:"
printf "%s\n" "$LOGS" | filter_lines "Wakeword detected|Utterance captured|Speech state:|Wake gate transition" | tail -n 20 || true
