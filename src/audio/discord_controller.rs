// SPDX-FileCopyrightText: 2026
// SPDX-License-Identifier: GPL-3.0-or-later

use std::{cell::RefCell, rc::Rc};

use discord_rich_presence::{
    activity::{Activity, ActivityType, Assets, StatusDisplayType, Timestamps},
    DiscordIpc, DiscordIpcClient,
};
use log::{debug, warn};

use crate::audio::{Controller, PlaybackState, RepeatMode, Song};

/// The Discord application whose name appears after "Listening to" in the
/// status. Public by design: anyone who sees the status can read it.
const DISCORD_APPLICATION_ID: &str = "1537033037735264266";

/// Key of an image uploaded to the Discord application's Rich Presence assets.
/// Local cover art cannot be used: Discord fetches images itself and has no
/// access to files on this machine.
const LARGE_IMAGE_KEY: &str = "aubade";

#[derive(Default)]
struct DiscordState {
    title: String,
    artist: String,
    album: String,
    duration_secs: u64,
    playing: bool,
    /// Unix seconds at which the current song started, so Discord can show a
    /// live elapsed time without us sending updates.
    started_at: i64,
}

#[derive(Default)]
struct Inner {
    client: RefCell<Option<DiscordIpcClient>>,
    state: RefCell<DiscordState>,
    enabled: RefCell<bool>,
}

/// Cheap to clone: the player keeps a handle to toggle it while also holding
/// it in the controller list, the same way the waveform generator works.
#[derive(Clone, Default)]
pub struct DiscordController {
    inner: Rc<Inner>,
}

impl DiscordController {
    pub fn new() -> Self {
        Self::default()
    }

    /// Turns presence on or off. Disabling clears any status already shown and
    /// drops the connection, so nothing is broadcast afterwards.
    pub fn set_enabled(&self, enabled: bool) {
        if *self.inner.enabled.borrow() == enabled {
            return;
        }
        self.inner.enabled.replace(enabled);

        if enabled {
            debug!("Discord presence enabled");
            self.publish();
        } else {
            debug!("Discord presence disabled");
            self.disconnect();
        }
    }

    fn disconnect(&self) {
        if let Some(mut client) = self.inner.client.borrow_mut().take() {
            let _ = client.clear_activity();
            let _ = client.close();
        }
    }

    /// Connects on first use. Discord not running is the ordinary case, not an
    /// error worth reporting to the user.
    fn ensure_connected(&self) -> bool {
        if self.inner.client.borrow().is_some() {
            return true;
        }

        let mut client = DiscordIpcClient::new(DISCORD_APPLICATION_ID);
        match client.connect() {
            Ok(()) => {
                debug!("Connected to Discord");
                self.inner.client.replace(Some(client));
                true
            }
            Err(e) => {
                debug!("Discord is not reachable: {e}");
                false
            }
        }
    }

    /// Pushes the current song to Discord.
    ///
    /// Deliberately not called from `set_position`: Discord rate-limits
    /// presence updates, and the position ticks several times a second. The
    /// start timestamp lets Discord run the clock on its own.
    fn publish(&self) {
        if !*self.inner.enabled.borrow() {
            return;
        }
        if !self.ensure_connected() {
            return;
        }

        let state = self.inner.state.borrow();
        if state.title.is_empty() {
            return;
        }

        let mut guard = self.inner.client.borrow_mut();
        let client = match guard.as_mut() {
            Some(c) => c,
            None => return,
        };

        let assets = Assets::new()
            .large_image(LARGE_IMAGE_KEY)
            .large_text(state.album.as_str());

        let mut activity = Activity::new()
            // Music is "Listening to", not "Playing". Without this Discord
            // defaults to the game-style Playing verb.
            .activity_type(ActivityType::Listening)
            // Show the track name in the member list rather than the app name.
            .status_display_type(StatusDisplayType::Details)
            .details(state.title.as_str())
            .state(state.artist.as_str())
            .assets(assets);

        // Only show a running clock while actually playing; a paused song with
        // a ticking timer reads as wrong.
        if state.playing && state.duration_secs > 0 {
            activity = activity.timestamps(
                Timestamps::new()
                    .start(state.started_at)
                    .end(state.started_at + state.duration_secs as i64),
            );
        }

        let failed = client.set_activity(activity).err();

        // Release the borrow before touching the cell again, or replacing it
        // panics with BorrowMutError.
        drop(guard);

        if let Some(e) = failed {
            warn!("Unable to update Discord presence: {e}");
            // The connection is probably gone; drop it so the next update
            // reconnects rather than failing forever.
            self.inner.client.replace(None);
        }
    }

    fn now_secs() -> i64 {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs() as i64)
            .unwrap_or(0)
    }
}

impl Controller for DiscordController {
    fn set_playback_state(&self, state: &PlaybackState) {
        let playing = matches!(state, PlaybackState::Playing);

        {
            let mut current = self.inner.state.borrow_mut();
            if current.playing == playing {
                return;
            }
            current.playing = playing;
        }

        if matches!(state, PlaybackState::Stopped) {
            self.disconnect();
            return;
        }

        self.publish();
    }

    fn set_song(&self, song: &Song) {
        {
            let mut state = self.inner.state.borrow_mut();
            state.title = song.title();
            state.artist = song.artist();
            state.album = song.album();
            state.duration_secs = song.duration();
            state.started_at = Self::now_secs();
        }

        self.publish();
    }

    fn set_position(&self, _position: u64, _notify: bool) {
        // Intentionally empty. See `publish`.
    }

    fn set_repeat_mode(&self, _repeat: RepeatMode) {}
}

impl Drop for Inner {
    fn drop(&mut self) {
        if let Some(mut client) = self.client.borrow_mut().take() {
            let _ = client.clear_activity();
            let _ = client.close();
        }
    }
}
