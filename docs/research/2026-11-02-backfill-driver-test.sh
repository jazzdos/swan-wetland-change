#!/bin/bash
# Stub test for 2026-11-02-backfill-driver.sh. Usage:
#   bash docs/research/2026-11-02-backfill-driver-test.sh \
#     <abs path to driver> <abs path to 2026-11-02-backfill-fake-cli> <scratch dir>
# Overrides WT, DATA and BACKFILL_CMD, so it never touches the real data. Prints ok/FAIL per case.
DRV=$1; FAKE=$2; T=$3
export BACKOFF=1 NET_URL=file:///etc/hosts BACKFILL_CMD=$FAKE
setup() { local D=$T/t$1; rm -rf "$D"; mkdir -p "$D/wt/data/external" "$D/state"; echo x > "$D/wt/data/external/dbca_010_ramsar_sites.geojson"; echo x > "$D/wt/data/external/dea_waterbodies_v3_swan.geojson"; echo 2026-11-02 > "$D/state/end_date"; echo 1147 > "$D/state/reference_count"; }
run() { local n=$1; shift; ( cd /tmp && env WT="$T/t$n/wt" DATA="$T/t$n" "$@" bash "$DRV" ); }
check() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1: got '$2' want '$3'"; fails=1; fi; }
fails=0
setup 1; run 1; check happy_rc $? 0; D=$T/t1
check chunks "$(wc -l < "$D/state/all_chunks.txt" | tr -d ' ')" 17
check first "$(head -1 "$D/state/all_chunks.txt")" '2022-12-01 2022-12-31'
check last "$(tail -1 "$D/state/all_chunks.txt")" '2026-10-01 2026-11-02'
check calls "$(grep -c '^backfill' "$D/outputs/calls.txt")" 35
check dups "$(grep -c DUP "$D/outputs/calls.txt")" 0
check scores "$(grep -c '^score' "$D/outputs/calls.txt")" 1
check retried "$(grep -c 'chunk=2023-04-01..2023-06-30 lane=1 pass=1 rc=2' "$D/state/progress.log")" 1
check done_file "$([ -e "$D/state/DONE" ] && echo yes)" yes
run 1 2>/dev/null; check rerun_rc $? 0
check rerun_calls "$(grep -c '^backfill' "$D/outputs/calls.txt")" 35
setup 2; run 2 FAKE_FAIL_ALL=1 PASSES=2; check failall_rc $? 3
check failall_park "$(grep -c 'first chunk' "$T/t2/state/PARK")" 1
setup 3; echo 99999999999 > "$T/t3/state/reference_count"; run 3; check disk_rc $? 3
check disk_park "$(grep -c 'exceeds the free space' "$T/t3/state/PARK")" 1
setup 4; rm "$T/t4/wt/data/external/dea_waterbodies_v3_swan.geojson"; run 4; check aoi_rc $? 3
check aoi_park "$(cat "$T/t4/state/PARK")" 'missing DEA Waterbodies AOI file'
setup 5; run 5 FAKE_SCORE_RC=1; check score_rc $? 3
check score_no_done "$([ -e "$T/t5/state/DONE" ] && echo yes || echo no)" no
setup 6; cp "$DRV" "$T/t6/driver.sh"; ( cd /tmp && env WT="$T/t6/wt" DATA="$T/t6" bash "$T/t6/driver.sh" >/dev/null 2>&1 & ); sleep 8; pkill -9 -f "$T/t6/driver.sh"; sleep 1
check killed_no_done "$([ -e "$T/t6/state/DONE" ] && echo yes || echo no)" no
( cd /tmp && env WT="$T/t6/wt" DATA="$T/t6" bash "$T/t6/driver.sh" ); check relaunch_rc $? 0
check relaunch_done "$([ -e "$T/t6/state/DONE" ] && echo yes)" yes
check relaunch_dups "$(grep -c DUP "$T/t6/outputs/calls.txt")" 0
check secs_logged "$(grep -c 'chunk=.* rc=[0-9]* secs=[0-9]' "$T/t1/state/progress.log")" "$(grep -c 'chunk=.* rc=[0-9]* ' "$T/t1/state/progress.log")"
setup 7; run 7 FAKE_FAIL_START=2023-01-01 PASSES=2; check sweepfail_rc $? 3
check sweepfail_no_done "$([ -e "$T/t7/state/DONE" ] && echo yes || echo no)" no
check sweepfail_no_score "$(grep -c '^score' "$T/t7/outputs/calls.txt")" 0
check sweepfail_park "$(cat "$T/t7/state/PARK" | grep -c 'sweep chunks gave up: 2023-01-01..2023-03-31')" 1
exit $fails
