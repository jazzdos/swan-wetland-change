#!/bin/bash
# st-b983: detached Collection 1 backfill and score. Safe to rerun after any
# interruption, because the ledger skips finished items. It ends by writing
# $STATE/DONE (finished) or $STATE/PARK (stopped, the text says why).
# WT defaults to the repository root (two levels above this script's directory).
# WT, DATA, BACKFILL_CMD, LANES, PASSES, BACKOFF and NET_URL are overridable
# for the stub test only.
set -u

WT=${WT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}
DATA=${DATA:-/Users/jarrodbaker/Documents/swan-wetland-change-data}
CMD=${BACKFILL_CMD:-uv run --no-sync wetland-change}
LANES=${LANES:-3}
PASSES=${PASSES:-4}
BACKOFF=${BACKOFF:-60}
NET_URL=${NET_URL:-https://earth-search.aws.element84.com/v1/collections/sentinel-2-c1-l2a}
START_DATE=2022-12-01
ROOT=$DATA/outputs
STATE=$DATA/state
LOGS=$DATA/logs

log() { echo "$(date -u +%FT%TZ) $*" >> "$STATE/progress.log"; }

park() {
  echo "$*" > "$STATE/PARK"
  log "PARK $*"
  exit 3
}

mkdir -p "$ROOT" "$STATE" "$LOGS"
cd "$WT" || exit 1
if [ -e "$STATE/DONE" ]; then
  echo "already finished: $(cat "$STATE/DONE")" >&2
  exit 0
fi
if [ -e "$STATE/PARK" ]; then
  echo "parked: $(cat "$STATE/PARK"); remove the file to resume" >&2
  exit 3
fi
if [ -e "$STATE/driver.pid" ] && kill -0 "$(cat "$STATE/driver.pid")" 2>/dev/null; then
  echo "driver already running as $(cat "$STATE/driver.pid")" >&2
  exit 0
fi
if pgrep -f 'bin/wetland-change (backfill|score) ' >/dev/null; then
  echo "a backfill or score process is still running" >&2
  exit 1
fi
echo $$ > "$STATE/driver.pid"

END_DATE=$(cat "$STATE/end_date" 2>/dev/null) || park "missing $STATE/end_date"
REF=$(cat "$STATE/reference_count" 2>/dev/null) || park "missing $STATE/reference_count"
[ -s data/external/dbca_010_ramsar_sites.geojson ] || park "missing Ramsar AOI file"
[ -s data/external/dea_waterbodies_v3_swan.geojson ] || park "missing DEA Waterbodies AOI file"

# December 2022, then calendar quarters, capped at END_DATE.
chunks() {
  local y q s e
  echo "$START_DATE 2022-12-31"
  for y in 2023 2024 2025 2026; do
    for q in 01-01:03-31 04-01:06-30 07-01:09-30 10-01:12-31; do
      s=$y-${q%:*}
      e=$y-${q#*:}
      if [[ "$s" > "$END_DATE" ]]; then continue; fi
      if [[ "$e" > "$END_DATE" ]]; then e=$END_DATE; fi
      echo "$s $e"
    done
  done
}

# Run ids have one-second resolution and come from --now, and the CLI refuses a
# reused id. Each lane only uses seconds congruent to its number, and never the
# same second twice, so no two invocations share a run id. The CLI reads a --now
# without a zone as local time. Sets RUN_NOW; must not run in a subshell.
LAST_T=0
lane_now() {
  local t
  while :; do
    t=$(date +%s)
    if [ "$t" -gt "$LAST_T" ] && [ $((t % LANES)) -eq "$1" ]; then
      LAST_T=$t
      RUN_NOW=$(date -r "$t" +%Y-%m-%dT%H:%M:%S)
      return
    fi
    sleep 1
  done
}

wait_for_network() {
  until curl -sf -m 30 -o /dev/null "$NET_URL"; do
    log "network: Earth Search unreachable, waiting"
    sleep 300
  done
}

# Exit 0 means nothing is left to process in the chunk. Exit 2 means scenes
# failed; a failed scene is retried on the next pass up to the ledger's cap of
# three attempts, so the last pass exits 0 even if a scene never succeeded.
run_chunk() {
  local s=$1 e=$2 lane=$3 pass rc=1 t0
  for pass in $(seq 1 "$PASSES"); do
    if [ -e "$STATE/PARK" ]; then return 3; fi
    wait_for_network
    lane_now "$lane"
    t0=$(date +%s)
    $CMD backfill --start "$s" --end "$e" --output-root "$ROOT" --now "$RUN_NOW" \
      </dev/null >>"$LOGS/backfill_${s}_${e}.out" 2>>"$LOGS/backfill_${s}_${e}.err"
    rc=$?
    # secs is the wall time of the backfill call alone; the run manifests
    # cannot give it, because both their timestamps come from --now.
    log "chunk=$s..$e lane=$lane pass=$pass rc=$rc secs=$(($(date +%s) - t0))"
    if [ "$rc" -eq 0 ]; then return 0; fi
    sleep $((pass * BACKOFF))
  done
  log "chunk=$s..$e lane=$lane GAVE_UP rc=$rc"
  return "$rc"
}

manifest_sum() {
  cat "$ROOT"/runs/*.json 2>/dev/null |
    awk -F'[:,]' -v key="\"$1\"" '$1 ~ key { s += $2 } END { print s + 0 }'
}

# Stop early when the first chunk shows a systematic failure.
gate_first_chunk() {
  local processed failed
  processed=$(manifest_sum processed)
  failed=$(manifest_sum failed)
  log "first chunk processed=$processed failed_attempts=$failed"
  if [ "$processed" -eq 0 ] || [ "$failed" -gt "$processed" ]; then
    park "first chunk processed $processed scenes with $failed failed attempts; see $LOGS"
  fi
}

# Project the final output size from the size per ledger part.
project() {
  local used parts need free
  used=$(du -sk "$ROOT" | cut -f1)
  parts=$(find "$ROOT/ledger" -name 'ledger_*.parquet' 2>/dev/null | wc -l | tr -d ' ')
  if [ "$parts" -eq 0 ]; then park "no ledger parts under $ROOT"; fi
  need=$((used * REF / parts))
  free=$(df -k "$DATA" | awk 'NR==2 { print $4 }')
  echo "$(date -u +%FT%TZ) used_kib=$used ledger_parts=$parts reference_items=$REF projected_total_kib=$need free_kib=$free" >> "$STATE/projection.txt"
  if [ $((need - used)) -ge "$free" ]; then
    park "projected output of $need KiB exceeds the free space: $used KiB used, $free KiB free"
  fi
}

log "driver start pid=$$ end_date=$END_DATE lanes=$LANES reference_items=$REF"
chunks > "$STATE/all_chunks.txt"
read -r first_start first_end < "$STATE/all_chunks.txt"
run_chunk "$first_start" "$first_end" 0
gate_first_chunk
project

tail -n +2 "$STATE/all_chunks.txt" > "$STATE/lane_chunks.txt"
for lane in $(seq 0 $((LANES - 1))); do
  (
    n=0
    while read -r s e; do
      if [ $((n % LANES)) -eq "$lane" ] && [ ! -e "$STATE/PARK" ]; then
        run_chunk "$s" "$e" "$lane"
        project
      fi
      n=$((n + 1))
    done < "$STATE/lane_chunks.txt"
  ) &
done
wait
if [ -e "$STATE/PARK" ]; then exit 3; fi

# One sequential sweep picks up chunks that gave up and late items. The pause
# puts the sweep's first run id after lane 0's last one.
sleep $((LANES + 1))
log "sweep start"
sweep_failed=""
while read -r s e; do
  run_chunk "$s" "$e" 0 || sweep_failed="$sweep_failed $s..$e"
done < "$STATE/all_chunks.txt"
if [ -e "$STATE/PARK" ]; then exit 3; fi
# A chunk that gives up in the sweep is not recovered by anything later, so
# scoring would rest on a partial store. DONE means every chunk finished.
if [ -n "$sweep_failed" ]; then park "sweep chunks gave up:$sweep_failed; see $LOGS"; fi

log "score start"
$CMD score --start "$START_DATE" --end "$END_DATE" --output-root "$ROOT" \
  </dev/null >"$LOGS/score.out" 2>"$LOGS/score.err"
rc=$?
log "score rc=$rc"
if [ "$rc" -ne 0 ]; then park "score exited $rc; see $LOGS/score.err"; fi
echo "finished $(date -u +%FT%TZ)" > "$STATE/DONE"
log "DONE"
