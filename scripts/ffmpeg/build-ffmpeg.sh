#!/usr/bin/env bash
# Build the K-DOG distribution FFmpeg (GPL 2+, libx264 + zlib only) with its
# corresponding source bundle. Run from an MSYS2 UCRT64 shell; see README.md.
set -euo pipefail

FFMPEG_VERSION=9.0.2
FFMPEG_ARCHIVE=ffmpeg-$FFMPEG_VERSION.tar.xz
FFMPEG_URL=https://ffmpeg.org/releases/$FFMPEG_ARCHIVE
FFMPEG_SHA256=8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e
X264_COMMIT=b35605ace3ddf7c1a5d67a2eb553f034aef41d55
X264_ARCHIVE=x264-$X264_COMMIT.tar.bz2
X264_URL=https://code.videolan.org/videolan/x264/-/archive/$X264_COMMIT/$X264_ARCHIVE
X264_SHA256=6eeb82934e69fd51e043bd8c5b0d152839638d1ce7aa4eea65a3fedcf83ff224
ZLIB_VERSION=1.3.2
ZLIB_ARCHIVE=zlib-$ZLIB_VERSION.tar.xz
ZLIB_URL=https://github.com/madler/zlib/releases/download/v$ZLIB_VERSION/$ZLIB_ARCHIVE
ZLIB_SHA256=d7a0654783a4da529d1bb793b7ad9c3318020af77667bcae35f95d0e42a792f3

if [ "${MSYSTEM:-}" != UCRT64 ]; then
  echo "Run this script from an MSYS2 UCRT64 shell." >&2
  exit 1
fi
SCRIPT=$(cd "$(dirname "$0")" && pwd)/$(basename "$0")
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
CACHE=$ROOT/releases/.cache
# KDOG_FFMPEG_SOURCES may point at a previous build's source/ folder for an offline rebuild.
SOURCES=${KDOG_FFMPEG_SOURCES:-$CACHE/ffmpeg-src}
OUT=${KDOG_FFMPEG_OUT:-$CACHE/ffmpeg-$FFMPEG_VERSION-kdog}
# Build steps cd into each source tree, so every prefix must be absolute.
mkdir -p "$SOURCES" "$(dirname "$OUT")"
SOURCES=$(cd "$SOURCES" && pwd)
OUT=$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")
WORK=$OUT.work
DEPS=$WORK/deps
JOBS=${KDOG_FFMPEG_JOBS:-4}  # each O3 compiler process can need ~1 GB of commit memory
case "$WORK$OUT" in *" "*) echo "FFmpeg configure does not support spaces in build paths." >&2; exit 1;; esac

fetch() {  # archive url sha256
  if [ ! -f "$SOURCES/$1" ]; then
    curl -fsSL --retry 3 -o "$SOURCES/$1.part" "$2"
    mv "$SOURCES/$1.part" "$SOURCES/$1"
  fi
  if ! echo "$3 *$SOURCES/$1" | sha256sum -c --quiet -; then
    # code.videolan.org can answer scripted downloads with a bot-check page instead of the archive.
    echo "$SOURCES/$1 does not match the pinned SHA-256. Delete it, then download $2" >&2
    echo "in a browser or copy it from a previous build's source/ folder, and rerun." >&2
    exit 1
  fi
}

join_lines() {  # comma-separate stdin lines
  awk 'NR > 1 { print previous "," } { previous = $0 } END { if (NR) print previous }'
}

json_string() {
  local value=${1//\\/\\\\}
  printf '"%s"' "${value//\"/\\\"}"
}

fetch "$FFMPEG_ARCHIVE" "$FFMPEG_URL" "$FFMPEG_SHA256"
fetch "$X264_ARCHIVE" "$X264_URL" "$X264_SHA256"
fetch "$ZLIB_ARCHIVE" "$ZLIB_URL" "$ZLIB_SHA256"

rm -rf "$WORK" "$OUT.tmp"
mkdir -p "$WORK" "$DEPS" "$OUT.tmp/bin" "$OUT.tmp/source" "$OUT.tmp/licenses"
tar -xJf "$SOURCES/$ZLIB_ARCHIVE" -C "$WORK"
tar -xjf "$SOURCES/$X264_ARCHIVE" -C "$WORK"
tar -xJf "$SOURCES/$FFMPEG_ARCHIVE" -C "$WORK"

# Only our pinned static dependencies are visible; MSYS2's own x264/zlib packages are ignored.
export PKG_CONFIG_LIBDIR=$DEPS/lib/pkgconfig
unset PKG_CONFIG_PATH

ZLIB_BUILD="make -f win32/Makefile.gcc -j$JOBS install BINARY_PATH=$DEPS/bin INCLUDE_PATH=$DEPS/include LIBRARY_PATH=$DEPS/lib SHARED_MODE=0"
(cd "$WORK/zlib-$ZLIB_VERSION" && $ZLIB_BUILD)

X264_CONFIGURE="./configure --prefix=$DEPS --enable-static --disable-cli --disable-opencl"
(cd "$WORK/x264-$X264_COMMIT" && $X264_CONFIGURE && make -j"$JOBS" && make install)
# zlib's makefile ignores failed copies; never let FFmpeg fall back to MSYS2's own libraries.
for file in lib/libz.a lib/libx264.a include/zlib.h include/x264.h lib/pkgconfig/zlib.pc lib/pkgconfig/x264.pc; do
  [ -f "$DEPS/$file" ] || { echo "Pinned dependency was not installed: $DEPS/$file" >&2; exit 1; }
done

FFMPEG_CONFIGURE=(./configure --prefix="$WORK/install"
  --enable-gpl --enable-libx264 --enable-zlib --disable-autodetect --enable-w32threads
  --disable-ffplay --disable-doc
  --pkg-config-flags=--static
  --extra-cflags="-I$DEPS/include" --extra-ldflags="-L$DEPS/lib -static")
(cd "$WORK/ffmpeg-$FFMPEG_VERSION" && "${FFMPEG_CONFIGURE[@]}" && make -j"$JOBS" && make install)
FFMPEG_COMMAND=$(printf '%q ' "${FFMPEG_CONFIGURE[@]}")
FFMPEG_COMMAND=${FFMPEG_COMMAND% }

cp "$WORK/install/bin/ffmpeg.exe" "$WORK/install/bin/ffprobe.exe" "$OUT.tmp/bin/"
# Static linking leaves only Windows DLLs: System32 files or the UCRT API-set names.
SYSTEM32=$(cygpath -u "${SYSTEMROOT:-C:\Windows}")/System32
for tool in ffmpeg ffprobe; do
  objdump -p "$OUT.tmp/bin/$tool.exe" | sed -n 's/.*DLL Name: //p' | while read -r dll; do
    case "$dll" in api-ms-win-crt-*) continue;; esac
    if [ ! -f "$SYSTEM32/$dll" ]; then
      echo "$tool.exe depends on non-system DLL $dll." >&2
      exit 1
    fi
  done
done

cp "$SOURCES/$FFMPEG_ARCHIVE" "$SOURCES/$X264_ARCHIVE" "$SOURCES/$ZLIB_ARCHIVE" "$OUT.tmp/source/"
cp "$SCRIPT" "$OUT.tmp/source/build-ffmpeg.sh"
{
  echo "# Run inside each extracted source folder, in this order (build-ffmpeg.sh does this)."
  echo "# MSYS2 UCRT64 tools: pacman -S make diffutils mingw-w64-ucrt-x86_64-{gcc,binutils,pkgconf,nasm}"
  echo "# DEPS is a private prefix; PKG_CONFIG_LIBDIR=\$DEPS/lib/pkgconfig."
  echo "zlib-$ZLIB_VERSION:   $ZLIB_BUILD"
  echo "x264-$X264_COMMIT:   $X264_CONFIGURE && make && make install"
  echo "ffmpeg-$FFMPEG_VERSION:   $FFMPEG_COMMAND && make && make install"
} > "$OUT.tmp/source/configure-commands.txt"

FF=$WORK/ffmpeg-$FFMPEG_VERSION
cp "$FF/COPYING.GPLv2" "$FF/COPYING.LGPLv2.1" "$FF/LICENSE.md" "$OUT.tmp/licenses/"
cp "$WORK/x264-$X264_COMMIT/COPYING" "$OUT.tmp/licenses/x264-COPYING"
cp "$WORK/zlib-$ZLIB_VERSION/LICENSE" "$OUT.tmp/licenses/zlib-LICENSE"
# Statically linked compiler runtime: mingw-w64 CRT and winpthreads, libgcc (GCC Runtime Library Exception).
for package in crt winpthreads libgcc; do
  cp -r "/ucrt64/share/licenses/$package" "$OUT.tmp/licenses/mingw-w64-$package"
done

{
  echo "{"
  echo "  \"format\": \"kdog-ffmpeg-build-1\","
  echo "  \"ffmpeg\": \"$FFMPEG_VERSION\", \"x264\": \"$X264_COMMIT\", \"zlib\": \"$ZLIB_VERSION\","
  echo "  \"license\": \"GPL-2.0-or-later\","
  echo "  \"built_at\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\","
  echo "  \"compiler\": $(json_string "$(gcc --version | head -n 1)"),"
  echo "  \"toolchain\": ["
  pacman -Q | grep -E '^(mingw-w64-ucrt-x86_64-(gcc|binutils|crt|headers|winpthreads|libwinpthread|nasm|pkgconf)|make|nasm) ' \
    | sed 's/.*/    "&"/' | join_lines
  echo "  ],"
  echo "  \"configure\": {"
  echo "    \"zlib\": $(json_string "$ZLIB_BUILD"),"
  echo "    \"x264\": $(json_string "$X264_CONFIGURE"),"
  echo "    \"ffmpeg\": $(json_string "$FFMPEG_COMMAND")"
  echo "  },"
  echo "  \"sources\": {"
  echo "    \"$FFMPEG_ARCHIVE\": \"$FFMPEG_SHA256\","
  echo "    \"$X264_ARCHIVE\": \"$X264_SHA256\","
  echo "    \"$ZLIB_ARCHIVE\": \"$ZLIB_SHA256\""
  echo "  },"
  echo "  \"files\": {"
  (cd "$OUT.tmp" && find bin source licenses -type f | LC_ALL=C sort | while read -r file; do
    echo "    $(json_string "$file"): \"$(sha256sum "$file" | cut -d' ' -f1)\""
  done | join_lines)
  echo "  }"
  echo "}"
} > "$OUT.tmp/build.json"

rm -rf "$OUT"
mv "$OUT.tmp" "$OUT"
rm -rf "$WORK"
echo "Built $OUT"
"$OUT/bin/ffmpeg.exe" -hide_banner -buildconf
