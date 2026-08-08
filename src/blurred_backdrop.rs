// SPDX-FileCopyrightText: 2026
// SPDX-License-Identifier: GPL-3.0-or-later

use std::cell::{Cell, RefCell};

use adw::subclass::prelude::*;
use gtk::{gdk, glib, graphene, prelude::*};
use log::debug;

/// Blur radius in widget coordinates. Apple Music's backdrop is heavily
/// diffused; anything under about 40 still reads as "a photo".
const BLUR_RADIUS: f64 = 64.0;

mod imp {
    use super::*;

    #[derive(Debug, Default)]
    pub struct BlurredBackdrop {
        pub texture: RefCell<Option<gdk::Texture>>,

        // Frame instrumentation, so blur cost is measured rather than guessed.
        pub frames: Cell<u32>,
        pub window_start: RefCell<Option<std::time::Instant>>,
    }

    #[glib::object_subclass]
    impl ObjectSubclass for BlurredBackdrop {
        const NAME: &'static str = "AubadeBlurredBackdrop";
        type Type = super::BlurredBackdrop;
        type ParentType = gtk::Widget;
    }

    impl ObjectImpl for BlurredBackdrop {}

    impl WidgetImpl for BlurredBackdrop {
        fn snapshot(&self, snapshot: &gtk::Snapshot) {
            let started = std::time::Instant::now();

            if let Some(texture) = self.texture.borrow().as_ref() {
                let widget = self.obj();
                let width = widget.width() as f32;
                let height = widget.height() as f32;

                if width <= 0.0 || height <= 0.0 {
                    return;
                }

                // Scale the cover to *cover* the widget, preserving aspect,
                // then centre the overflow. A blurred backdrop must never
                // letterbox.
                let ratio = texture.intrinsic_aspect_ratio() as f32;
                let (w, h) = if ratio > width / height {
                    (height * ratio, height)
                } else {
                    (width, width / ratio)
                };
                let x = (width - w) / 2.0;
                let y = (height - h) / 2.0;

                snapshot.push_blur(BLUR_RADIUS);
                snapshot.append_texture(texture, &graphene::Rect::new(x, y, w, h));
                snapshot.pop();
            }

            let elapsed = started.elapsed();
            let frames = self.frames.get() + 1;
            self.frames.set(frames);

            let mut start = self.window_start.borrow_mut();
            let window_start = start.get_or_insert_with(std::time::Instant::now);
            if frames == 1 || frames % 10 == 0 {
                let secs = window_start.elapsed().as_secs_f64();
                debug!(
                    "backdrop: {} frames in {:.2}s = {:.1} fps, last snapshot {:.2} ms",
                    frames,
                    secs,
                    frames as f64 / secs,
                    elapsed.as_secs_f64() * 1000.0,
                );
            }
        }
    }
}

glib::wrapper! {
    pub struct BlurredBackdrop(ObjectSubclass<imp::BlurredBackdrop>)
        @extends gtk::Widget,
        @implements gtk::Accessible, gtk::Buildable, gtk::ConstraintTarget;
}

impl Default for BlurredBackdrop {
    fn default() -> Self {
        glib::Object::new::<Self>()
    }
}

impl BlurredBackdrop {
    pub fn set_texture(&self, texture: Option<gdk::Texture>) {
        self.imp().texture.replace(texture);
        self.queue_draw();
    }
}
