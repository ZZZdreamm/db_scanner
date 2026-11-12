#!/usr/bin/env bash
# Push the current main to the PUBLIC repository without the private paths below.
# The private repository (remote "origin") keeps everything; the public one (remote "public")
# gets one commit per publish, with the same tree minus PRIVATE_PATHS.
set -euo pipefail
cd "$(dirname "$0")/.."
PRIVATE_PATHS=(lab)

[ -z "$(git status --porcelain)" ] || { echo "Commit or stash your changes first."; exit 1; }
git fetch -q public main
tmp_index=$(mktemp); trap 'rm -f "$tmp_index"' EXIT
export GIT_INDEX_FILE=$tmp_index
git read-tree HEAD
git rm -r -q --cached --ignore-unmatch -- "${PRIVATE_PATHS[@]}"
tree=$(git write-tree)
unset GIT_INDEX_FILE

if [ "$tree" = "$(git rev-parse public/main^{tree})" ]; then echo "Public repository is up to date."; exit 0; fi
echo "Files that will change in the public repository:"
git diff --stat public/main "$tree"
for p in "${PRIVATE_PATHS[@]}"; do
  ! git ls-tree -r --name-only "$tree" | grep -q "^$p/" || { echo "BUG: $p would be published"; exit 1; }
done
if [ -t 0 ]; then read -r -p "Push to $(git remote get-url public)? [y/N] " a; [[ "$a" =~ ^[yYtT] ]] || exit 1; fi
msg=$(git log -1 --format=%B HEAD)
commit=$(git commit-tree "$tree" -p public/main -m "$msg")
git push -q public "$commit:refs/heads/main"
echo "Published $commit"
