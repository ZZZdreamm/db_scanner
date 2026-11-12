#!/usr/bin/env bash
# eol-scan: instalacja, testy, pierwszy skan i publikacja kalkulatora na GitHub Pages.
#
#   ./start.sh          wszystko po kolei (o każdy krok z efektem ubocznym pyta)
#   ./start.sh install  tylko środowisko i instalacja
#   ./start.sh test     testy
#   ./start.sh scan     skan Twojego konta AWS (tylko odczyt)
#   ./start.sh deploy   repozytorium na GitHubie + kalkulator na GitHub Pages
#   ./start.sh preview  podgląd kalkulatora lokalnie (http://localhost:8000)

set -euo pipefail
cd "$(dirname "$0")"

B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; N=$'\033[0m'
step() { printf "\n${B}== %s${N}\n" "$*"; }
ok()   { printf "  ${G}✔${N} %s\n" "$*"; }
warn() { printf "  ${Y}!${N} %s\n" "$*"; }
fail() { printf "  ${R}✘${N} %s\n" "$*"; exit 1; }
ask()  { local a; [ -t 0 ] || return 1; read -r -p "  $1 [t/N] " a; [[ "$a" =~ ^[tTyY] ]]; }

VENV=.venv
PY="$VENV/bin/python"

install() {
  step "1. Python i środowisko"
  command -v python3 >/dev/null || fail "Brak python3. Zainstaluj Python 3.9 lub nowszy."
  python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' \
    || fail "Potrzebny Python 3.9+, masz $(python3 --version)."
  ok "$(python3 --version)"
  if [ ! -x "$PY" ]; then
    python3 -m venv "$VENV" || fail "Nie udało się utworzyć $VENV (na Debianie/Ubuntu: sudo apt install python3-venv)."
    ok "utworzono środowisko $VENV"
  fi
  "$PY" -m pip install -q --upgrade pip
  "$PY" -m pip install -q -e '.[pg,test]'
  ok "zainstalowano eol-scan $("$VENV/bin/eol-scan" --version | awk '{print $2}')"
}

run_tests() {
  step "2. Testy (symulowane AWS, bez konta)"
  AWS_DEFAULT_REGION=eu-central-1 AWS_ACCESS_KEY_ID=testing AWS_SECRET_ACCESS_KEY=testing \
    "$PY" -m pytest -q && ok "testy przechodzą"
}

scan() {
  step "3. Skan Twojego konta AWS (tylko odczyt)"
  local who
  if ! who=$("$PY" - <<'EOF' 2>/dev/null
import boto3
s = boto3.Session()
i = s.client("sts").get_caller_identity()
print(f"{i['Account']} ({i['Arn'].split('/')[-1]}), region domyślny: {s.region_name or 'brak'}")
EOF
  ); then
    warn "Nie widzę uprawnień AWS. Skonfiguruj je (aws configure albo aws sso login) i uruchom: ./start.sh scan"
    warn "Wystarczą uprawnienia: rds:DescribeDBInstances i ec2:DescribeRegions."
    return 0
  fi
  ok "konto $who"
  ask "Przeskanować wszystkie regiony tego konta?" || { warn "pominięto. Ręcznie: $VENV/bin/eol-scan --all-regions"; return 0; }
  "$VENV/bin/eol-scan" --all-regions
  "$VENV/bin/eol-scan" --all-regions --format html -o report.html 2>/dev/null
  ok "raport HTML zapisany w report.html (nie trafia do repozytorium)"
  if command -v open >/dev/null; then open report.html; elif command -v xdg-open >/dev/null; then xdg-open report.html >/dev/null 2>&1 || true; fi
  echo "  Postgres od środka: $VENV/bin/eol-scan --pg-dsn \"host=... dbname=... user=...\" --format html -o report.html"
}

deploy() {
  step "4. GitHub: repozytorium i kalkulator na GitHub Pages"
  command -v git >/dev/null || fail "Brak git."
  if ! command -v gh >/dev/null || ! gh auth status >/dev/null 2>&1; then
    warn "Do automatycznej publikacji potrzebny jest GitHub CLI (https://cli.github.com), zalogowany: gh auth login"
    cat <<'EOF'
  Albo ręcznie:
    1. Utwórz na github.com puste, publiczne repozytorium, np. eol-scan.
    2. git init -b main && git add -A && git commit -m "Initial commit"
       git remote add origin https://github.com/<login>/eol-scan.git && git push -u origin main
    3. W repozytorium: Settings → Pages → Source: GitHub Actions.
    4. Actions → "Deploy calculator to GitHub Pages" → Run workflow.
    Kalkulator będzie pod https://<login>.github.io/eol-scan/
EOF
    return 0
  fi
  local login name repo
  login=$(gh api user -q .login)
  ok "zalogowany do GitHuba jako $login"

  if git remote get-url origin >/dev/null 2>&1; then
    repo=$(gh repo view --json nameWithOwner -q .nameWithOwner)
    ok "repozytorium już istnieje: $repo"
    if [ -n "$(git status --porcelain)" ] && ask "Zatwierdzić i wypchnąć bieżące zmiany?"; then
      git add -A && git commit -q -m "Update" && git push -q && ok "wypchnięto zmiany"
    fi
  else
    name=eol-scan
    [ -t 0 ] && read -r -p "  Nazwa repozytorium [$name]: " n && name=${n:-$name}
    echo "  Utworzę PUBLICZNE repozytorium $login/$name (GitHub Pages za darmo wymaga publicznego)."
    ask "Kontynuować?" || { warn "pominięto"; return 0; }
    [ -d .git ] || git init -q -b main
    git add -A
    git commit -q -m "eol-scan: Extended Support scanner and calculator" || true
    gh repo create "$name" --public --source=. --remote=origin --push \
      --description "Find Amazon RDS and Aurora databases that cost extra in Extended Support"
    repo="$login/$name"
    ok "utworzono https://github.com/$repo"
  fi

  if gh api "repos/$repo/pages" >/dev/null 2>&1; then
    gh api -X PUT "repos/$repo/pages" -f build_type=workflow >/dev/null 2>&1 || true
  else
    gh api -X POST "repos/$repo/pages" -f build_type=workflow >/dev/null \
      || { warn "Nie udało się włączyć Pages. Zrób to ręcznie: Settings → Pages → Source: GitHub Actions"; }
  fi
  ok "GitHub Pages ustawione na GitHub Actions"
  gh workflow run pages.yml -R "$repo" >/dev/null 2>&1 && ok "uruchomiono publikację kalkulatora" \
    || warn "Uruchom ręcznie: Actions → Deploy calculator to GitHub Pages → Run workflow"
  local owner=${repo%%/*} rname=${repo##*/}
  echo
  echo "  Kalkulator za 1-2 minuty: ${B}https://$(echo "$owner" | tr '[:upper:]' '[:lower:]').github.io/$rname/${N}"
  echo "  Postęp: gh run watch -R $repo   albo zakładka Actions na GitHubie"
}

preview() {
  step "Podgląd kalkulatora: http://localhost:8000 (Ctrl+C kończy)"
  cd site && python3 -m http.server 8000
}

next_steps() {
  step "Co dalej"
  cat <<'EOF'
  1. Przeskanuj prawdziwe konto (choćby testowe) i sprawdź, czy kwoty zgadzają się
     z pozycją "ExtendedSupport" w AWS Cost Explorer. To Twój najlepszy dowód w rozmowach.
  2. Zweryfikuj stawki dla swoich regionów na stronie cennika RDS i popraw
     src/eol_scan/data.py oraz tablicę REGIONS w site/index.html, jeśli coś się różni.
  3. Opublikuj: ./start.sh deploy, a potem post z linkiem do kalkulatora
     (r/aws, r/PostgreSQL, LinkedIn) i wiadomości do Platform/DBA leadów.
  4. Dalszy rozwój najwygodniej w Claude Code w tym folderze (CLAUDE.md opisuje projekt).
EOF
}

case "${1:-all}" in
  install) install ;;
  test)    [ -x "$PY" ] || install; run_tests ;;
  scan)    [ -x "$PY" ] || install; scan ;;
  deploy)  deploy ;;
  preview) preview ;;
  all)     install; run_tests; scan; deploy; next_steps ;;
  *)       sed -n '2,9p' "$0"; exit 1 ;;
esac
