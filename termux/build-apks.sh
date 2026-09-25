#!/usr/bin/env bash
# Build the three Termux APKs with the same private fork signing identity.
# No APK or signing secret is stored in this public repository.
set -euo pipefail

APP_REF=cef72ea6190b1cfea04ab3fd6a5d37d046ad01ba
API_REF=5491d9c5dbf0d06ec5d0b98b38792350bb447d38
BOOT_REF=a8493bd6ba016bc370af34aa65fcbe065cc00ced
SIGNER=ec1ab3f5e4d261a4c6c5e2979b4af4f8d0071a951761575a2929ce59dcf1c0c1

usage() {
  cat <<'EOF'
Usage: termux/build-apks.sh check [--app APK --api APK --boot APK]
       termux/build-apks.sh build [--output DIR]

`check` only reads APKs. `build` checks out the pinned source commits into a
private Mac cache, builds release APKs, signs Boot with ~/keys/termux-fork.jks,
and refuses any APK whose package name or signing certificate differs.
Override Android/JDK locations with ANDROID_HOME, ANDROID_BUILD_TOOLS, JAVA_HOME.
EOF
}
die() { printf '[build-apks] ERROR: %s\n' "$*" >&2; exit 1; }
log() { printf '[build-apks] %s\n' "$*" >&2; }

[ $# -ge 1 ] || { usage; exit 2; }
mode=$1; shift
case "$mode" in check|build) ;; *) usage >&2; exit 2;; esac
output=${XDG_CACHE_HOME:-$HOME/.cache}/dotfiles-termux/apks
app='' api='' boot=''
while [ $# -gt 0 ]; do
  case "$1" in
    --output) [ $# -ge 2 ] || die '--output needs a path'; output=$2; shift 2;;
    --app) [ $# -ge 2 ] || die '--app needs a path'; app=$2; shift 2;;
    --api) [ $# -ge 2 ] || die '--api needs a path'; api=$2; shift 2;;
    --boot) [ $# -ge 2 ] || die '--boot needs a path'; boot=$2; shift 2;;
    -h|--help) usage; exit 0;;
    *) die "unknown option: $1";;
  esac
done
if [ "$mode" = build ] && { [ -n "$app" ] || [ -n "$api" ] || [ -n "$boot" ]; }; then
  die 'custom APK paths are check-only'
fi
app=${app:-$output/termux-app.apk}
api=${api:-$output/termux-api.apk}
boot=${boot:-$output/termux-boot.apk}

export ANDROID_HOME=${ANDROID_HOME:-$HOME/Android}
export JAVA_HOME=${JAVA_HOME:-/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home}
[ -x "$JAVA_HOME/bin/java" ] || die "JDK 17 missing at $JAVA_HOME"
export PATH="$JAVA_HOME/bin:$PATH"
bt=${ANDROID_BUILD_TOOLS:-$ANDROID_HOME/build-tools/35.0.0}
for tool in apksigner aapt zipalign; do [ -x "$bt/$tool" ] || die "missing $bt/$tool"; done

check_apk() {
  local path=$1 package=$2 want_version=$3 cert actual version
  [ -r "$path" ] || die "missing APK: $path"
  cert=$("$bt/apksigner" verify --print-certs "$path" | awk -F ': ' '/Signer #1 certificate SHA-256 digest/{print $2}')
  [ "$cert" = "$SIGNER" ] || die "$path has a different signing certificate"
  actual=$("$bt/aapt" dump badging "$path" | awk -F "'" '/^package:/{print $2; exit}')
  version=$("$bt/aapt" dump badging "$path" | awk -F "'" '/^package:/{print $4; exit}')
  [ "$actual" = "$package" ] || die "$path is $actual, expected $package"
  [ "$version" = "$want_version" ] || die "$package versionCode is $version, expected pinned $want_version"
}
check_all() {
  check_apk "$app" com.termux 1008
  check_apk "$api" com.termux.api 1003
  check_apk "$boot" com.termux.boot 1000
  printf 'verified app=%s api=%s boot=%s signer=%s\n' "$app" "$api" "$boot" "$SIGNER"
}
if [ "$mode" = check ]; then check_all; exit 0; fi

for tool in git op; do command -v "$tool" >/dev/null || die "missing $tool"; done
[ -r "$HOME/keys/termux-fork.jks" ] || die 'missing ~/keys/termux-fork.jks'
[ -f "$ANDROID_HOME/platforms/android-34/android.jar" ] || die 'install Android SDK platform 34'
[ -f "$ANDROID_HOME/platforms/android-35/android.jar" ] || die 'install Android SDK platform 35 for Termux:API'
[ -f "$ANDROID_HOME/platforms/android-36/android.jar" ] || die 'install Android SDK platform 36'
mkdir -p "$output" "$output/sources"
chmod 700 "$output" "$output/sources"

source_at() {
  local name=$1 url=$2 ref=$3 dir="$output/sources/$1"
  if [ ! -d "$dir/.git" ]; then
    [ ! -e "$dir" ] || die "$dir exists but is not a git checkout"
    git clone --quiet --filter=blob:none "$url" "$dir"
  fi
  git -C "$dir" fetch --quiet --depth 1 origin "$ref"
  git -C "$dir" checkout --quiet --detach "$ref"
  [ "$(git -C "$dir" rev-parse HEAD)" = "$ref" ] || die "$name checkout is not pinned to $ref"
  [ -z "$(git -C "$dir" status --porcelain --untracked-files=all)" ] \
    || die "$name checkout has staged, tracked, or untracked source changes"
  printf '%s\n' "$dir"
}

# Builds may be repeated; keep sources, but only publish a complete verified set.
tmp=$(mktemp -d "$output/.building.XXXXXX")
cleanup() {
  local rc=$?
  unset signing_password
  if [ "$rc" -eq 0 ]; then
    rm -rf "$tmp"
  else
    printf '[build-apks] build logs retained in %s (mode 0700)\n' "$tmp" >&2
  fi
}
trap cleanup EXIT
app_src=$(source_at app https://github.com/cartwmic/termux-app.git "$APP_REF")
api_src=$(source_at api https://github.com/cartwmic/termux-api.git "$API_REF")
boot_src=$(source_at boot https://github.com/termux/termux-boot.git "$BOOT_REF")
signing_password=$(op read 'op://developer/Termux Fork Signing Key/password')
[ -n "$signing_password" ] || die '1Password returned an empty signing password'

build_release() {
  local src=$1 label=$2 path
  log "building $label at $(git -C "$src" rev-parse --short HEAD)"
  # The fork wires downloadBootstraps only to Java compilation, while the NDK
  # may compile first. Run this checksum-verified task before assembleRelease.
  if [ "$label" = app ] && ! "$src/gradlew" -p "$src" :app:downloadBootstraps \
      --quiet --console=plain >"$tmp/app-bootstrap.log" 2>&1; then
    die "fork bootstrap download failed; inspect $tmp/app-bootstrap.log"
  fi
  if ! TERMUX_KEYSTORE="$HOME/keys/termux-fork.jks" TERMUX_KEYSTORE_PASSWORD="$signing_password" \
      "$src/gradlew" -p "$src" :app:assembleRelease --quiet --console=plain >"$tmp/$label.log" 2>&1; then
    die "$label build failed; inspect $tmp/$label.log before retrying"
  fi
  set -- "$src"/app/build/outputs/apk/release/*.apk
  [ $# -eq 1 ] && [ -f "$1" ] || die "expected exactly one $label release APK"
  printf '%s\n' "$1"
}
app_built=$(build_release "$app_src" app)
api_built=$(build_release "$api_src" api)
# Upstream Boot release is unsigned; never build/install its public-test-key debug APK.
log "building Boot at $(git -C "$boot_src" rev-parse --short HEAD)"
if ! "$boot_src/gradlew" -p "$boot_src" :app:assembleRelease --quiet --console=plain >"$tmp/boot.log" 2>&1; then
  die "Boot build failed; inspect $tmp/boot.log before retrying"
fi
set -- "$boot_src"/app/build/outputs/apk/release/*.apk
[ $# -eq 1 ] && [ -f "$1" ] || die 'expected exactly one Boot release APK'
if "$bt/apksigner" verify "$1" >/dev/null 2>&1; then die 'Boot release unexpectedly pre-signed'; fi
"$bt/zipalign" -p -f 4 "$1" "$tmp/boot-aligned.apk" >/dev/null
TERMUX_KEYSTORE_PASSWORD="$signing_password" "$bt/apksigner" sign \
  --ks "$HOME/keys/termux-fork.jks" --ks-key-alias termux \
  --ks-pass env:TERMUX_KEYSTORE_PASSWORD --key-pass env:TERMUX_KEYSTORE_PASSWORD \
  --out "$tmp/termux-boot.apk" "$tmp/boot-aligned.apk"
unset signing_password
cp "$app_built" "$tmp/termux-app.apk"
cp "$api_built" "$tmp/termux-api.apk"
app="$tmp/termux-app.apk" api="$tmp/termux-api.apk" boot="$tmp/termux-boot.apk"
check_all
mv "$app" "$output/termux-app.apk"
mv "$api" "$output/termux-api.apk"
mv "$boot" "$output/termux-boot.apk"
log "signed APKs ready in $output"
