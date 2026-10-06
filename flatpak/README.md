# Aubade — Flatpak packaging

Flatpak packaging for the native Aubade app in `../`.

## Files

| File | Role |
|------|------|
| `dev.aubade.Aubade.yml` | Flatpak manifest |
| `launcher.sh` | Installed as `/app/bin/aubade`, the `command:` entry point |
| `dev.aubade.Aubade.desktop` | Desktop entry (`AudioVideo;Audio;Music;Player`) |
| `dev.aubade.Aubade.metainfo.xml` | AppStream metadata |
| `icons/{128x128,256x256,512x512}/` | Downscales of `../aubade/assets/logo.png` |

## Build and install

```sh
flatpak install flathub org.gnome.Sdk//51 org.gnome.Platform//51
flatpak-builder --user --install --force-clean build-dir dev.aubade.Aubade.yml
flatpak run dev.aubade.Aubade
```

## Without flatpak

`../install.sh` reuses the desktop file, icons and AppStream metadata from this
directory for a plain user-scope install: no flatpak, no root, and it launches
the app straight out of the source tree.

```sh
../install.sh              # idempotent
../install.sh --dry-run    # print what it would write
../install.sh --uninstall
```

It writes `$XDG_DATA_HOME/{applications,icons/hicolor,metainfo}`,
`$XDG_BIN_HOME/aubade`, validates the desktop file with
`desktop-file-validate` and the metadata with `appstreamcli` when available,
and refreshes the icon/desktop caches. The desktop entry it installs is the one
below with `Exec=` pointed at the launcher shim, since `aubade` is not on
`PATH` outside the sandbox.

## How the pieces map to the runtime

**Python + GTK4 + libadwaita + GStreamer** come from `org.gnome.Platform//51`
rather than being built here. The runtime already provides `python3.14` with
PyGObject (`gi`, `pycairo`) in `/usr/lib/python3.14/site-packages`, the
`Gtk-4.0` / `Adw-1` / `Gst-1.0` typelibs, and GStreamer 1.28 with `playbin`,
`libav`, `flac`, `opus`, `vorbis`, `wavpack` and `pipewiresink`. Only the two
extras the app imports get installed:

- `mutagen==1.48.1` — tag reading in `library.py`
- `Pillow==12.3.0` — thumbnail generation in `art.py`

Both are pinned `sha256` sources unpacked into
`/app/lib/python3.14/site-packages`, which is not on the default `sys.path`, so
`launcher.sh` prepends it (plus the app tree) to `PYTHONPATH` before running
`python3 -m aubade` — the same call `run.sh` makes outside the sandbox.

The wheels are manifest sources rather than a `pip3 install` step because
flatpak-builder build sandboxes have no network access; flatpak-builder fetches
them on the host. Pillow ships compiled wheels, so it has one module per
architecture (`only-arches`), and the wheel tag tracks the runtime's Python
minor (`cp314` here) — bump both URLs and their `sha256`s together when
upgrading.

Verified inside the built sandbox: `python3.14.7`, GTK `4.24`,
GStreamer `1.28.6`, all 12 app modules import, `playbin` / `pipewiresink` /
`autoaudiosink` / `decodebin` all resolve, a `.m4a` from `~/Music` plays back
with the position advancing, and `lrclib.net` returns synced lyrics.

## Sandbox permissions

| Permission | Why |
|------------|-----|
| `--filesystem=xdg-music` | `library.py` scans `~/Music` on first launch |
| `--filesystem=xdg-download` | Common location for music on some setups |
| `--own-name=org.mpris.MediaPlayer2.aubade` | `mpris.py` publishes MPRIS2 on the session bus |
| `--talk-name=org.mpris.MediaPlayer2` | Control other players if Aubade becomes the active one |
| `--share=network` | `lyrics.py` falls back to `lrclib.net` and `api.lyrics.ovh` |
| `--socket=pulseaudio` + `--filesystem=xdg-run/pipewire-0` | `playbin` resolves to `autoaudiosink`; the Pulse socket is what `pipewiresink` falls back to, the native `pipewire-0` socket is the real-time path on hosts running PipeWire directly |
| `--socket=wayland`, `--socket=fallback-x11`, `--share=ipc`, `--device=dri` | GTK4 display and rendering |

Picking a different folder uses `Gtk.FileDialog`, which goes through the XDG
document portal, so it needs no extra permission. To grant a fixed path
instead, add e.g. `--filesystem=/srv/music`.

Cache and stats stay in the sandbox (`~/.var/app/dev.aubade.Aubade/`), not the
host `~/.cache/aubade`.

MPRIS was confirmed on the session bus as `org.mpris.MediaPlayer2.aubade` with
live track metadata and artwork. `mpris.py:189` advertises `DesktopEntry` as
`dev.aubade.Aubade`, which is the same string as this app's desktop file,
`Icon=`, `StartupWMClass=` and the `application_id` in `aubade/__init__.py`,
so GNOME's window/icon matching lines up.

## If the runtime moves on

`runtime-version` and the `lib/python3.14/site-packages` path are coupled — they
appear in the manifest's `site-packages` destinations and in `launcher.sh`'s
`lib/python3.*/site-packages` glob. Bumping the GNOME branch may mean updating
both, and a new Python minor also invalidates the `cp314` Pillow wheels.
`flatpak-builder-lint` warns when a newer runtime branch exists, which is the
signal to do this.
