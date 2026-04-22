#!/usr/bin/env bash
# Deterministic fake of `claude -p --output-format stream-json` used by
# the session-runner and supervisor tests. Behaviour is selected by the
# FAKE_CLAUDE_MODE environment variable; default is "clean".
#
# Modes:
#   clean      — emit system, two assistant events with usage, then result; exit 0
#   crash      — emit system + one assistant, then exit 1 without a result event
#   hang       — emit system, then sleep long enough to trip a test-side timeout
#   malformed  — emit valid JSON lines interleaved with one unparseable line
#   version    — respond to --version with "2.1.91 (fake)"; exit 0
#   old-version — respond to --version with "2.0.99 (fake)"; exit 0 (for version-too-old tests)

set -eu

# --version handling. The runner's version-check subprocess call reaches
# here with --version as $1 (or early in the argv). Handle it before we
# look at FAKE_CLAUDE_MODE so a single fake script covers both code paths.
for arg in "$@"; do
    if [ "$arg" = "--version" ]; then
        case "${FAKE_CLAUDE_MODE:-version}" in
            old-version)
                echo "2.0.99 (fake)"
                ;;
            *)
                echo "2.1.91 (fake)"
                ;;
        esac
        exit 0
    fi
done

MODE="${FAKE_CLAUDE_MODE:-clean}"
SESSION_ID="${FAKE_CLAUDE_SESSION_ID:-01JAKE0000000000000000001}"
MODEL="${FAKE_CLAUDE_MODEL:-claude-opus-4-7}"

emit_system() {
    printf '{"type":"system","subtype":"init","session_id":"%s","model":"%s"}\n' \
        "$SESSION_ID" "$MODEL"
}

emit_assistant() {
    local input_tokens="$1"
    local output_tokens="$2"
    printf '{"type":"assistant","session_id":"%s","message":{"model":"%s","usage":{"input_tokens":%s,"output_tokens":%s,"cache_creation_input_tokens":0,"cache_read_input_tokens":0}}}\n' \
        "$SESSION_ID" "$MODEL" "$input_tokens" "$output_tokens"
}

emit_result() {
    local input_tokens="$1"
    local output_tokens="$2"
    local cost="$3"
    printf '{"type":"result","subtype":"success","session_id":"%s","model":"%s","usage":{"input_tokens":%s,"output_tokens":%s,"cache_creation_input_tokens":0,"cache_read_input_tokens":0},"total_cost_usd":%s,"is_error":false,"duration_ms":123}\n' \
        "$SESSION_ID" "$MODEL" "$input_tokens" "$output_tokens" "$cost"
}

case "$MODE" in
    clean)
        emit_system
        emit_assistant 100 50
        emit_assistant 80 40
        emit_result 180 90 0.0125
        exit 0
        ;;
    crash)
        emit_system
        emit_assistant 50 25
        echo "fatal: simulated crash" >&2
        exit 1
        ;;
    hang)
        emit_system
        # ``exec`` replaces bash with sleep so SIGTERM reaches the
        # actual sleeper directly instead of getting stuck on bash's
        # child-wait. Long enough that even permissive test timeouts
        # will trip.
        exec sleep 600
        ;;
    malformed)
        emit_system
        # An unparseable line between valid ones.
        echo '{"type":"assistant","message":{"model":"' "$MODEL"
        emit_assistant 40 20
        emit_result 40 20 0.003
        exit 0
        ;;
    old-version)
        # Only --version is expected in this mode; unexpected invocation.
        echo "fake-claude: old-version mode reached non-version path" >&2
        exit 2
        ;;
    *)
        echo "fake-claude: unknown FAKE_CLAUDE_MODE=$MODE" >&2
        exit 2
        ;;
esac
