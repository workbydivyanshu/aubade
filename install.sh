#!/bin/sh
# Install Aubade for the current user, without flatpak.
#
# The app keeps running from this source tree (there is no staged install
# prefix); what gets installed is the desktop integration:
#
#   $XDG_DATA_HOME/applications/dev.aubade.Aubade.desktop
#   $XDG_DATA_HOME/icons/hicolor/{128x128,256x256,512x512}/apps/dev.aubade.Aubade.png
#   $XDG_DATA_HOME/metainfo/dev.aubade.Aubade.metainfo.xml
#   $XDG_BIN_HOME/aubade          launcher shim (the desktop Exec target)
#
# Re-running overwrites the same files, so install is idempotent, and
# --uninstall removes exactly those paths.
#
# Usage: install.sh [--uninstall] [--dry-run] [--app-dir DIR] [--help]
#
# Environment: HOME (required), XDG_DATA_HOME, XDG_BIN_HOME, TMPDIR.

set -eu

APP_ID='dev.aubade.Aubade'
ICON_SIZES='128 256 512'

usage() {
	cat <<'EOF'
Usage: install.sh [options]

  --uninstall      remove the desktop entry, icons, AppStream metadata and
                   the launcher shim installed by this script
  --dry-run, -n    print what would happen, write nothing
  --app-dir DIR    app tree to launch (default: directory holding this script)
  --help, -h       this text

Environment: HOME (required), XDG_DATA_HOME, XDG_BIN_HOME, TMPDIR.
EOF
}

# --- options ----------------------------------------------------------------

mode='install'
dry_run=0

for arg do
	case "$arg" in
	--uninstall) mode='uninstall' ;;
	--install) mode='install' ;;
	--dry-run | -n) dry_run=1 ;;
	--app-dir) shift; app_dir=${1:?--app-dir needs an argument} ;;
	--app-dir=*) app_dir=${arg#--app-dir=} ;;
	--help | -h)
		usage
		exit 0
		;;
	*)
		printf 'install.sh: unknown option: %s\n' "$arg" >&2
		usage >&2
		exit 2
		;;
	esac
	shift
done

# --- paths ------------------------------------------------------------------

: "${HOME:?HOME is not set}"

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
[ -n "${app_dir:-}" ] || app_dir=$script_dir

src_desktop="$script_dir/flatpak/$APP_ID.desktop"
src_metainfo="$script_dir/flatpak/$APP_ID.metainfo.xml"
src_logo="$app_dir/aubade/assets/logo.png"

data_home=${XDG_DATA_HOME:-$HOME/.local/share}
bin_home=${XDG_BIN_HOME:-$HOME/.local/bin}

apps_dir="$data_home/applications"
icons_dir="$data_home/icons/hicolor"
meta_dir="$data_home/metainfo"

dest_desktop="$apps_dir/$APP_ID.desktop"
dest_metainfo="$meta_dir/$APP_ID.metainfo.xml"
launcher="$bin_home/aubade"

# Aubade imports gi/Gst, which live in the system python, not a venv.
if [ -x /usr/bin/python3 ]; then
	python_bin=/usr/bin/python3
else
	python_bin=$(command -v python3 2>/dev/null || printf '/usr/bin/python3')
fi

# --- helpers ----------------------------------------------------------------

msg() { printf '%s\n' "$*"; }

need_file() {
	if [ ! -f "$1" ]; then
		printf 'install.sh: missing required file: %s\n' "$1" >&2
		exit 1
	fi
}

check_app_tree() {
	if [ ! -d "$app_dir/aubade" ] || [ ! -f "$app_dir/aubade/__main__.py" ]; then
		printf 'install.sh: %s does not look like the Aubade app tree\n' "$app_dir" >&2
		exit 1
	fi
}

install_file() { # src dst mode
	if [ "$dry_run" -eq 1 ]; then
		printf '  install %s <- %s (mode %s)\n' "$2" "$1" "$3"
		return 0
	fi
	mkdir -p "$(dirname -- "$2")"
	cp -f -- "$1" "$2"
	chmod "$3" -- "$2"
}

remove_file() { # path
	if [ ! -e "$1" ] && [ ! -L "$1" ]; then
		return 0
	fi
	if [ "$dry_run" -eq 1 ]; then
		printf '  rm -f %s\n' "$1"
		return 0
	fi
	rm -f -- "$1"
	msg "removed $1"
}

update_caches() {
	if [ "$dry_run" -eq 1 ]; then
		printf '  gtk-update-icon-cache -t -f %s\n' "$icons_dir"
		printf '  update-desktop-database %s\n' "$apps_dir"
		return 0
	fi
	if command -v gtk-update-icon-cache >/dev/null 2>&1 && [ -d "$icons_dir" ]; then
		gtk-update-icon-cache -q -t -f "$icons_dir" >/dev/null 2>&1 ||
			msg "gtk-update-icon-cache: failed (menu entries still work)"
	fi
	if command -v update-desktop-database >/dev/null 2>&1 && [ -d "$apps_dir" ]; then
		update-desktop-database -q "$apps_dir" >/dev/null 2>&1 || true
	fi
}

validate_desktop() { # file, hard-fail
	if ! command -v desktop-file-validate >/dev/null 2>&1; then
		msg 'desktop-file-validate not found, skipping desktop validation'
		return 0
	fi
	if desktop-file-validate "$1"; then
		msg "desktop-file-validate $1: ok"
	else
		printf 'install.sh: %s failed desktop-file-validate\n' "$1" >&2
		exit 1
	fi
}

validate_metainfo() { # file, warn only
	if ! command -v appstreamcli >/dev/null 2>&1; then
		msg 'appstreamcli not found, skipping AppStream validation'
		return 0
	fi
	# Known-benign for this app id: cid-contains-uppercase-letter and, until
	# there is a public repo, url-homepage-missing.
	if appstreamcli validate --pedantic "$1"; then
		msg "appstreamcli validate $1: ok"
	else
		msg "appstreamcli validate $1: warnings only (see above), continuing"
	fi
}

# --- icon sources -----------------------------------------------------------

tmpdir=$(mktemp -d "${TMPDIR:-/tmp}/aubade-install.XXXXXX")
trap 'rm -rf "$tmpdir"' EXIT INT TERM

# Rescale aubade/assets/logo.png down to $1 px, used only when the prebuilt
# hicolor icons are missing. Returns non-zero when Pillow is unavailable.
scale_logo() { # size
	"$python_bin" - "$src_logo" "$tmpdir/$1x$1" "$1" <<-'PY' >/dev/null 2>&1 || return 1
	import os
	import sys

	from PIL import Image

	src, out, size = sys.argv[1], sys.argv[2], int(sys.argv[3])
	im = Image.open(src).convert("RGBA")
	im.thumbnail((size, size), Image.LANCZOS)
	os.makedirs(out, exist_ok=True)
	im.save(os.path.join(out, "dev.aubade.Aubade.png"))
	PY
}

icon_source() { # size
	prebuilt="$script_dir/flatpak/icons/$1x$1/$APP_ID.png"
	if [ -f "$prebuilt" ]; then
		printf '%s\n' "$prebuilt"
		return 0
	fi
	if [ ! -f "$src_logo" ]; then
		return 1
	fi
	if scale_logo "$1"; then
		printf '%s\n' "$tmpdir/$1x$1/$APP_ID.png"
		return 0
	fi
	# Last resort: ship the 1024px master at every size.
	printf '%s\n' "$src_logo"
}

# --- install ----------------------------------------------------------------

do_install() {
	check_app_tree
	need_file "$src_desktop"

	msg "Installing $APP_ID for $(id -un 2>/dev/null || printf '%s' "uid $UID")"
	msg "  app tree : $app_dir"
	msg "  data dir : $data_home"
	msg "  bin dir  : $bin_home"
	msg ''

	validate_desktop "$src_desktop"
	if [ -f "$src_metainfo" ]; then
		validate_metainfo "$src_metainfo"
	else
		msg "note: $src_metainfo missing, skipping AppStream metadata"
	fi

	# Desktop entry: the shipped file with Exec pointed at the shim. Escape
	# sed metacharacters in the path before substituting. Built and validated
	# before anything is written, so a bad rewrite leaves no partial install.
	staged_desktop="$tmpdir/$APP_ID.desktop"
	if [ "$dry_run" -eq 1 ]; then
		printf '  install %s <- %s (Exec rewritten)\n' "$dest_desktop" "$src_desktop"
	else
		esc=$(printf '%s' "$launcher" | sed 's/[\\&|]/\\&/g')
		sed "s|^Exec=.*|Exec=\"$esc\"|" "$src_desktop" > "$staged_desktop"
		validate_desktop "$staged_desktop"
	fi

	# Launcher shim: the desktop entry needs an absolute Exec target, and
	# `aubade` is not on PATH outside the flatpak sandbox.
	if [ "$dry_run" -eq 1 ]; then
		printf '  write %s (shim: cd %s; exec %s -m aubade)\n' \
			"$launcher" "$app_dir" "$python_bin"
	else
		mkdir -p "$bin_home"
		{
			printf '%s\n' '#!/bin/sh'
			printf '%s\n' \
				"# Aubade launcher, generated by install.sh. Run from: $app_dir"
			printf '%s\n' "cd '$app_dir'"
			printf '%s\n' "exec $python_bin -m aubade \"\$@\""
		} > "$launcher"
		chmod 755 -- "$launcher"
	fi
	msg "launcher  $launcher"
	msg "desktop   $dest_desktop"

	if [ "$dry_run" -eq 0 ]; then
		install_file "$staged_desktop" "$dest_desktop" 644
	fi

	if [ -f "$src_metainfo" ]; then
		install_file "$src_metainfo" "$dest_metainfo" 644
		msg "appstream $dest_metainfo"
	fi

	for size in $ICON_SIZES; do
		dest_icon="$icons_dir/${size}x${size}/apps/$APP_ID.png"
		if ! src_icon=$(icon_source "$size"); then
			printf 'install.sh: no icon found for %sx%s\n' "$size" "$size" >&2
			continue
		fi
		install_file "$src_icon" "$dest_icon" 644
		msg "icon      $dest_icon"
	done

	update_caches

	msg ''
	msg 'Done. Launch it from the app menu, or run:'
	msg "  $launcher"
}

# --- uninstall --------------------------------------------------------------

do_uninstall() {
	msg "Uninstalling $APP_ID from $data_home and $bin_home"

	remove_file "$launcher"
	remove_file "$dest_desktop"
	remove_file "$dest_metainfo"
	for size in $ICON_SIZES; do
		remove_file "$icons_dir/${size}x${size}/apps/$APP_ID.png"
		if [ "$dry_run" -eq 0 ] && [ -d "$icons_dir/${size}x${size}/apps" ]; then
			# Only prunes directories that are empty afterwards.
			rmdir "$icons_dir/${size}x${size}/apps" 2>/dev/null || true
			rmdir "$icons_dir/${size}x${size}" 2>/dev/null || true
		fi
	done

	update_caches

	msg "Done. Nothing of Aubade's is left in the user XDG dirs."
}

case "$mode" in
install) do_install ;;
uninstall) do_uninstall ;;
esac
