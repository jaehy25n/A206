#!/usr/bin/env bash
#
# Pull READY sessions from the EC2 CPU server into the GPU-local mirror.
#
#   ./scripts/sync_processed_from_cpu.sh                # pull what is new
#   ./scripts/sync_processed_from_cpu.sh -n             # dry run, list only
#   ./scripts/sync_processed_from_cpu.sh -s <uuid>      # one session
#   ./scripts/sync_processed_from_cpu.sh --resync       # replace STALE sessions
#   ./scripts/sync_processed_from_cpu.sh --force-resync # replace every session
#
# Contract
#   * only sessions that carry a READY marker are pulled -- a session directory
#     can exist on the CPU while preprocessing is still writing into it;
#   * every transfer lands in .incoming/<session>.partial and is moved into
#     place only after it validates, so the converter never sees a half-copy;
#   * a session already present is skipped -- UNLESS the CPU re-published it,
#     which is detected and never skipped silently (see "staleness" below);
#   * a session present locally that the CPU no longer publishes is reported as
#     orphaned. It stays on disk and the converter would still read it, so it is
#     never passed over in silence;
#   * nothing is ever deleted. Replacing a session moves the old copy into
#     .superseded/<session>.<timestamp>/ so a bad re-export can be undone.
#
# Staleness
#   rsync -a preserves mtimes, so the local READY file carries the timestamp the
#   CPU wrote it with. Comparing that against the remote READY mtime tells us
#   whether the CPU re-preprocessed the same session id since we pulled it.
#   Both values come from the CPU's clock, so clock skew between the two hosts
#   cannot cause a false result.
#
#     remote READY mtime == local READY mtime   -> up to date, skip
#     remote READY mtime != local READY mtime   -> STALE, reported loudly
#
#   This is the case that matters right now: the 7 sessions already mirrored here
#   came from CPU preprocessing that is being fixed. Once the CPU re-publishes
#   them under the same session ids, `--resync` replaces them.
#
# GPU never pushes, never writes back to the CPU, and never modifies its local
# mirror -- it is a read-only input to the UMI converter.
set -euo pipefail

ENV_FILE="${CPU_SYNC_ENV:-$HOME/umi-gpu/config/cpu_sync.env}"
DRY_RUN=0
ONLY_SESSION=""
RESYNC=0            # replace sessions detected as stale
FORCE_RESYNC=0      # replace every READY session regardless
PRUNE_ORPHANS=0     # move locally-present sessions the CPU dropped

usage() {
    cat <<USAGE
usage: $(basename "$0") [-n] [-s SESSION_ID] [-e ENV_FILE] [--resync] [--force-resync]

  -n, --dry-run    list what would happen, transfer nothing
  -s SESSION       act on this session id only
  -e ENV_FILE      config file (default: \$HOME/umi-gpu/config/cpu_sync.env,
                   override with CPU_SYNC_ENV)
      --resync     re-pull sessions whose CPU copy changed since we mirrored it.
                   The local copy is moved to .superseded/, never deleted.
      --force-resync
                   re-pull every READY session, changed or not. Use after a CPU
                   preprocessing fix that did not alter the READY timestamp.
      --prune-orphans
                   move local sessions the CPU no longer publishes into
                   .superseded/. They are always reported; without this flag they
                   are left in place, and the converter WILL still read them.
  -h, --help       this message
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        -n|--dry-run)     DRY_RUN=1; shift ;;
        -s)               ONLY_SESSION="$2"; shift 2 ;;
        -e)               ENV_FILE="$2"; shift 2 ;;
        --resync)         RESYNC=1; shift ;;
        --force-resync)   FORCE_RESYNC=1; RESYNC=1; shift ;;
        --prune-orphans)  PRUNE_ORPHANS=1; shift ;;
        -h|--help)        usage; exit 0 ;;
        *)                echo "unknown argument: $1" >&2; usage; exit 2 ;;
    esac
done

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: config not found: $ENV_FILE" >&2
    echo "       cp config/cpu_sync.env.example \"$ENV_FILE\" and fill it in" >&2
    exit 2
fi
# shellcheck disable=SC1090
source "$ENV_FILE"

for var in CPU_USER CPU_HOST CPU_PROCESSED_ROOT GPU_PROCESSED_ROOT SSH_KEY; do
    if [ -z "${!var:-}" ]; then
        echo "ERROR: $var is not set in $ENV_FILE" >&2
        exit 2
    fi
done
if [ "$CPU_HOST" = "<EC2_HOST>" ]; then
    echo "ERROR: CPU_HOST is still the placeholder in $ENV_FILE" >&2
    exit 2
fi
if [ ! -f "$SSH_KEY" ]; then
    echo "ERROR: SSH key not found: $SSH_KEY" >&2
    echo "       ssh-keygen -t ed25519 -f $SSH_KEY   # then register the .pub on EC2" >&2
    exit 2
fi

REMOTE="${CPU_USER}@${CPU_HOST}"
SSH_PORT="${SSH_PORT:-22}"
SSH_CMD="ssh -p ${SSH_PORT} -i ${SSH_KEY} -o BatchMode=yes"
FINAL_ROOT="${GPU_PROCESSED_ROOT}"
STAGING_ROOT="${FINAL_ROOT}/.incoming"
SUPERSEDED_ROOT="${FINAL_ROOT}/.superseded"
LOG_ROOT="${FINAL_ROOT}/.logs"
mkdir -p "$FINAL_ROOT" "$STAGING_ROOT" "$SUPERSEDED_ROOT" "$LOG_ROOT"

STAMP="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_ROOT}/sync_${STAMP}.log"
exec > >(tee -a "$LOG_FILE") 2>&1

LOCK="${FINAL_ROOT}/.sync.lock"
exec 9>"$LOCK"
if ! flock -n 9; then
    echo "another sync is already running (lock: $LOCK)"; exit 0
fi

echo "=============================================================================="
echo "CPU -> GPU processed sync   $(date -Is)"
echo "  source      : ${REMOTE}:${CPU_PROCESSED_ROOT}"
echo "  destination : ${FINAL_ROOT}"
echo "  log         : ${LOG_FILE}"
[ "$DRY_RUN" -eq 1 ]      && echo "  MODE        : dry run"
[ "$FORCE_RESYNC" -eq 1 ] && echo "  MODE        : FORCE RESYNC (replace every session)"
[ "$FORCE_RESYNC" -eq 0 ] && [ "$RESYNC" -eq 1 ] && echo "  MODE        : resync stale sessions"
[ "$PRUNE_ORPHANS" -eq 1 ] && echo "  MODE        : prune orphaned local sessions"
echo "=============================================================================="

echo "[1/4] looking for READY sessions on the CPU server..."
if ! $SSH_CMD "$REMOTE" 'echo CPU_CONNECTION_OK' | grep -q CPU_CONNECTION_OK; then
    echo "ERROR: cannot reach ${REMOTE} over SSH" >&2
    exit 1
fi

# "<READY mtime, epoch seconds>\t<session dir>"
READY_LINES="$(
    $SSH_CMD "$REMOTE" \
        "find '${CPU_PROCESSED_ROOT}' -mindepth 2 -maxdepth 2 -type f -name READY -printf '%T@\t%h\n' 2>/dev/null" \
        | sort -t$'\t' -k2 || true
)"

if [ -z "$READY_LINES" ]; then
    echo
    echo "No READY sessions found under ${CPU_PROCESSED_ROOT}."
    echo "  A session is only pulled once CPU preprocessing has written its READY"
    echo "  marker. If sessions exist there but carry no READY, the CPU side still"
    echo "  needs   (session_output_dir / 'READY').touch()   after validation."
    exit 0
fi

N_TOTAL=0; N_SYNCED=0; N_SKIPPED=0; N_FAILED=0; N_STALE=0; N_REPLACED=0
FAILED_IDS=""; STALE_IDS=""

while IFS=$'\t' read -r REMOTE_MTIME REMOTE_SESSION_DIR; do
    [ -z "${REMOTE_SESSION_DIR:-}" ] && continue
    REMOTE_MTIME="${REMOTE_MTIME%%.*}"                  # drop the fraction
    SESSION_ID="$(basename "$REMOTE_SESSION_DIR")"
    if [ -n "$ONLY_SESSION" ] && [ "$SESSION_ID" != "$ONLY_SESSION" ]; then
        continue
    fi
    N_TOTAL=$((N_TOTAL + 1))

    FINAL_DIR="${FINAL_ROOT}/${SESSION_ID}"
    STAGING_DIR="${STAGING_ROOT}/${SESSION_ID}.partial"

    echo
    echo "=== session ${SESSION_ID} ==="

    REPLACE=0
    if [ -d "$FINAL_DIR" ] && [ -f "$FINAL_DIR/READY" ]; then
        LOCAL_MTIME="$(stat -c %Y "$FINAL_DIR/READY")"
        DIFF=$(( REMOTE_MTIME - LOCAL_MTIME )); DIFF=${DIFF#-}
        if [ "$FORCE_RESYNC" -eq 1 ]; then
            echo "present; --force-resync requested"
            REPLACE=1
        elif [ "$DIFF" -le 1 ]; then
            echo "already synced, skipping  (READY mtime $(date -d @"$LOCAL_MTIME" -Is 2>/dev/null || echo "$LOCAL_MTIME"))"
            N_SKIPPED=$((N_SKIPPED + 1))
            continue
        else
            N_STALE=$((N_STALE + 1)); STALE_IDS="${STALE_IDS} ${SESSION_ID}"
            echo "STALE: the CPU re-published this session after we mirrored it"
            echo "       local  READY $(date -d @"$LOCAL_MTIME"  -Is 2>/dev/null || echo "$LOCAL_MTIME")"
            echo "       remote READY $(date -d @"$REMOTE_MTIME" -Is 2>/dev/null || echo "$REMOTE_MTIME")"
            if [ "$RESYNC" -eq 1 ]; then
                REPLACE=1
            else
                echo "       not replaced. Re-run with --resync to pull the new copy."
                continue
            fi
        fi
    elif [ -d "$FINAL_DIR" ]; then
        echo "ERROR: ${FINAL_DIR} exists but has no READY marker."
        echo "       That is a half-published directory. Inspect it and move it"
        echo "       aside by hand before retrying; this script will not delete data."
        N_FAILED=$((N_FAILED + 1)); FAILED_IDS="${FAILED_IDS} ${SESSION_ID}"
        continue
    fi

    if [ "$DRY_RUN" -eq 1 ]; then
        if [ "$REPLACE" -eq 1 ]; then
            echo "would REPLACE ${FINAL_DIR}/ (old copy -> .superseded/)"
        else
            echo "would pull ${REMOTE_SESSION_DIR}/ -> ${FINAL_DIR}/"
        fi
        continue
    fi

    rm -rf "$STAGING_DIR"       # a replacement must not resume a stale partial
    mkdir -p "$STAGING_DIR"
    echo "[2/4] rsync -> ${STAGING_DIR}"
    if ! rsync -a --partial --checksum --info=progress2 \
            ${RSYNC_EXTRA_FLAGS:-} \
            -e "ssh -p ${SSH_PORT} -i ${SSH_KEY} -o BatchMode=yes" \
            "${REMOTE}:${REMOTE_SESSION_DIR}/" "${STAGING_DIR}/"; then
        echo "ERROR: rsync failed for ${SESSION_ID}; staging kept for resume"
        N_FAILED=$((N_FAILED + 1)); FAILED_IDS="${FAILED_IDS} ${SESSION_ID}"
        continue
    fi

    echo "[3/4] validating the local copy"
    if [ ! -f "${STAGING_DIR}/READY" ]; then
        echo "ERROR: READY missing after transfer -- not publishing"
        N_FAILED=$((N_FAILED + 1)); FAILED_IDS="${FAILED_IDS} ${SESSION_ID}"
        continue
    fi
    EPISODE_COUNT="$(find "$STAGING_DIR" -mindepth 2 -maxdepth 2 -type f -name frames.csv | wc -l)"
    if [ "$EPISODE_COUNT" -eq 0 ]; then
        echo "ERROR: no frames.csv found -- not publishing"
        N_FAILED=$((N_FAILED + 1)); FAILED_IDS="${FAILED_IDS} ${SESSION_ID}"
        continue
    fi
    echo "episodes = ${EPISODE_COUNT}"

    if [ "$REPLACE" -eq 1 ]; then
        SUPERSEDED_DIR="${SUPERSEDED_ROOT}/${SESSION_ID}.${STAMP}"
        echo "[4/4] superseding the old copy -> ${SUPERSEDED_DIR}"
        mv "$FINAL_DIR" "$SUPERSEDED_DIR"
        N_REPLACED=$((N_REPLACED + 1))
    else
        echo "[4/4] atomic publish"
    fi

    mv "$STAGING_DIR" "$FINAL_DIR"          # same filesystem -> atomic rename
    {
        echo "synced_at=$(date -Is)"
        echo "cpu_host=${CPU_HOST}"
        echo "cpu_path=${REMOTE_SESSION_DIR}"
        echo "remote_ready_mtime=${REMOTE_MTIME}"
        echo "episodes=${EPISODE_COUNT}"
        [ "$REPLACE" -eq 1 ] && echo "replaced_previous=${SUPERSEDED_DIR}"
    } > "${FINAL_DIR}/GPU_SYNCED"
    echo "SYNC COMPLETE: ${SESSION_ID}"
    N_SYNCED=$((N_SYNCED + 1))
done <<< "$READY_LINES"

# ---------------------------------------------------------------- orphans ---
# A session the CPU no longer publishes -- typically one its fixed preprocessing
# now rejects. It stays on disk and the converter WILL read it, so it can never
# be left unreported.
N_ORPHAN=0; ORPHAN_IDS=""
REMOTE_IDS="$(echo "$READY_LINES" | awk -F'\t' '{n=split($2,a,"/"); print a[n]}' | sort)"
for LOCAL_DIR in "$FINAL_ROOT"/*/; do
    [ -d "$LOCAL_DIR" ] || continue
    SID="$(basename "$LOCAL_DIR")"
    case "$SID" in .*) continue ;; esac
    if echo "$REMOTE_IDS" | grep -qx "$SID"; then continue; fi
    N_ORPHAN=$((N_ORPHAN + 1)); ORPHAN_IDS="${ORPHAN_IDS} ${SID}"
    if [ "$PRUNE_ORPHANS" -eq 1 ] && [ "$DRY_RUN" -eq 0 ]; then
        mv "$LOCAL_DIR" "${SUPERSEDED_ROOT}/${SID}.orphan.${STAMP}"
        echo "orphan pruned: ${SID} -> .superseded/${SID}.orphan.${STAMP}"
    fi
done

echo
echo "=============================================================================="
echo "READY on CPU: ${N_TOTAL}   synced: ${N_SYNCED} (replaced ${N_REPLACED})   up to date: ${N_SKIPPED}   stale: ${N_STALE}   failed: ${N_FAILED}   orphaned: ${N_ORPHAN}"

if [ "$N_ORPHAN" -gt 0 ] && [ "$PRUNE_ORPHANS" -eq 0 ]; then
    echo
    echo "  ${N_ORPHAN} local session(s) are NOT published by the CPU any more:"
    for s in $ORPHAN_IDS; do echo "    $s"; done
    echo "  Most likely the fixed CPU preprocessing now rejects them."
    echo "  They are STILL ON DISK and the converter will still read them. Move"
    echo "  them aside with:"
    echo "      $0 --prune-orphans"
    echo "  (moved to .superseded/, not deleted)"
fi

if [ "$N_STALE" -gt 0 ] && [ "$RESYNC" -eq 0 ]; then
    echo
    echo "  ${N_STALE} session(s) were re-published by the CPU after we mirrored them:"
    for s in $STALE_IDS; do echo "    $s"; done
    echo "  The local copies are OUT OF DATE. Replace them with:"
    echo "      $0 --resync"
    echo "  The old copies are kept under .superseded/ so nothing is lost."
fi

if [ -d "$SUPERSEDED_ROOT" ] && [ -n "$(ls -A "$SUPERSEDED_ROOT" 2>/dev/null)" ]; then
    echo
    echo "  .superseded/ holds $(du -sh "$SUPERSEDED_ROOT" | cut -f1) of replaced copies."
    echo "  The converter never reads it. Remove it once the new data checks out:"
    echo "      rm -rf ${SUPERSEDED_ROOT}"
fi

if [ "$N_FAILED" -gt 0 ]; then
    echo "failed sessions:${FAILED_IDS}"
    echo "=============================================================================="
    exit 1
fi
echo "next: python scripts/inspect_synced_processed.py --root ${FINAL_ROOT}"
echo "=============================================================================="
