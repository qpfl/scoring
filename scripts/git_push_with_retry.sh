#!/usr/bin/env bash

set -u

remote="${1:-origin}"
branch="${2:-main}"
max_attempts="${3:-5}"

if ! [[ "$max_attempts" =~ ^[1-9][0-9]*$ ]]; then
    echo "attempt count must be a positive integer" >&2
    exit 2
fi

for ((attempt = 1; attempt <= max_attempts; attempt++)); do
    echo "Push attempt ${attempt}/${max_attempts} to ${remote}/${branch}"
    if ! git pull --rebase "$remote" "$branch"; then
        echo "Pull/rebase failed; resolve the conflict before retrying." >&2
        exit 1
    fi

    if git push "$remote" "HEAD:${branch}"; then
        exit 0
    fi

    if ((attempt < max_attempts)); then
        delay=$((2 ** attempt))
        echo "Push rejected; retrying in ${delay}s." >&2
        sleep "$delay"
    fi
done

echo "Push failed after ${max_attempts} attempts." >&2
exit 1
