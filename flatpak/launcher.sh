#!/bin/sh
# Flatpak entry point for Aubade.
#
# The runtime's python3 (with PyGObject) is /usr/bin/python3. pip installed the
# dependencies into $FLATPAK_DEST/lib/python3.*/site-packages, which is not on
# the default sys.path, so the app tree and the dependency tree are added to
# PYTHONPATH before handing over to `python3 -m aubade` (the same call as the
# project-local run.sh).
set -eu

appdir="${FLATPAK_DEST:-/app}"

paths="$appdir/share/aubade"
for dir in "$appdir"/lib/python3.*/site-packages; do
	if [ -d "$dir" ]; then
		paths="$paths:$dir"
	fi
done

PYTHONPATH="$paths${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH

cd "$appdir/share/aubade"
exec python3 -m aubade "$@"
