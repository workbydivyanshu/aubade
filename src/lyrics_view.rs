// SPDX-FileCopyrightText: 2026
// SPDX-License-Identifier: GPL-3.0-or-later

use std::cell::{Cell, RefCell};

use adw::subclass::prelude::*;
use glib::subclass::Signal;
use gtk::{glib, prelude::*, CompositeTemplate};
use once_cell::sync::Lazy;

use crate::lyrics::Lyrics;

/// Dimmest a line may become. Lines never vanish entirely, or the lyrics read
/// as truncated rather than faded.
const MIN_LYRIC_OPACITY: f64 = 0.25;

/// Opacity for a line `distance` rows away from the active one.
pub fn opacity_for_distance(distance: usize) -> f64 {
    if distance == 0 {
        return 1.0;
    }
    let faded = 1.0 - (distance as f64 * 0.18);
    faded.max(MIN_LYRIC_OPACITY)
}

mod imp {
    use super::*;

    #[derive(Debug, Default, CompositeTemplate)]
    #[template(resource = "/io/github/workbydivyanshu/Aubade/lyrics-view.ui")]
    pub struct LyricsView {
        #[template_child]
        pub scrolled_window: TemplateChild<gtk::ScrolledWindow>,
        #[template_child]
        pub lines_box: TemplateChild<gtk::Box>,

        pub lyrics: RefCell<Option<Lyrics>>,
        pub labels: RefCell<Vec<gtk::Label>>,
        pub active: Cell<Option<usize>>,
    }

    #[glib::object_subclass]
    impl ObjectSubclass for LyricsView {
        const NAME: &'static str = "AubadeLyricsView";
        type Type = super::LyricsView;
        type ParentType = gtk::Widget;

        fn class_init(klass: &mut Self::Class) {
            Self::bind_template(klass);

            klass.set_layout_manager_type::<gtk::BinLayout>();
            klass.set_css_name("lyricsview");
            klass.set_accessible_role(gtk::AccessibleRole::Group);
        }

        fn instance_init(obj: &glib::subclass::InitializingObject<Self>) {
            obj.init_template();
        }
    }

    impl ObjectImpl for LyricsView {
        fn signals() -> &'static [Signal] {
            static SIGNALS: Lazy<Vec<Signal>> = Lazy::new(|| {
                vec![Signal::builder("line-activated")
                    .param_types([u64::static_type()])
                    .build()]
            });

            SIGNALS.as_ref()
        }

        fn dispose(&self) {
            while let Some(child) = self.obj().first_child() {
                child.unparent();
            }
        }
    }

    impl WidgetImpl for LyricsView {}
}

glib::wrapper! {
    pub struct LyricsView(ObjectSubclass<imp::LyricsView>)
        @extends gtk::Widget,
        @implements gtk::Accessible, gtk::Buildable, gtk::ConstraintTarget;
}

impl Default for LyricsView {
    fn default() -> Self {
        glib::Object::new::<Self>()
    }
}

impl LyricsView {
    pub fn new() -> Self {
        Self::default()
    }

    /// Replaces the displayed lyrics, rebuilding the label list.
    pub fn set_lyrics(&self, lyrics: Option<Lyrics>) {
        let imp = self.imp();

        for label in imp.labels.borrow().iter() {
            imp.lines_box.remove(label);
        }
        imp.labels.borrow_mut().clear();
        imp.active.set(None);

        let synced = lyrics.as_ref().map(|l| l.synced).unwrap_or(false);

        if let Some(lyrics) = &lyrics {
            let mut labels = imp.labels.borrow_mut();
            for line in &lyrics.lines {
                let label = gtk::Label::builder()
                    .label(&line.text)
                    .wrap(true)
                    .justify(gtk::Justification::Center)
                    .max_width_chars(36)
                    .build();
                label.add_css_class("lyric-line");

                // Clicking a line seeks to it. Only meaningful when the lyrics
                // carry timestamps; unsynced lines all sit at zero.
                if synced {
                    let time_ms = line.time_ms;
                    let gesture = gtk::GestureClick::new();
                    gesture.connect_released(glib::clone!(
                        #[weak(rename_to = view)]
                        self,
                        move |_, _, _, _| {
                            view.emit_by_name::<()>("line-activated", &[&time_ms]);
                        }
                    ));
                    label.add_controller(gesture);
                    label.set_cursor_from_name(Some("pointer"));
                }

                imp.lines_box.append(&label);
                labels.push(label);
            }
        }

        imp.lyrics.replace(lyrics);
        self.scroll_to_top();
    }

    /// Updates the highlighted line for the current playback position.
    pub fn set_position_ms(&self, position_ms: u64) {
        let imp = self.imp();

        let active = match &*imp.lyrics.borrow() {
            Some(lyrics) => lyrics.active_line_at(position_ms),
            None => None,
        };

        // Unsynced lyrics have no active line, so leave them as laid out
        // rather than fading everything to the inactive style.
        if active.is_none() && imp.active.get().is_none() {
            return;
        }

        if active == imp.active.get() {
            return;
        }

        {
            let labels = imp.labels.borrow();
            if let Some(previous) = imp.active.get() {
                if let Some(label) = labels.get(previous) {
                    label.remove_css_class("lyric-active");
                }
            }
            if let Some(current) = active {
                if let Some(label) = labels.get(current) {
                    label.add_css_class("lyric-active");
                }

                // Fade with distance from the active line, so the lyrics read
                // as moving rather than merely highlighting.
                for (index, label) in labels.iter().enumerate() {
                    let distance = index.abs_diff(current);
                    label.set_opacity(opacity_for_distance(distance));
                }
            } else {
                for label in labels.iter() {
                    label.set_opacity(1.0);
                }
            }
        }

        imp.active.set(active);

        if let Some(current) = active {
            self.scroll_to(current);
        }
    }

    fn scroll_to_top(&self) {
        let adjustment = self.imp().scrolled_window.vadjustment();
        adjustment.set_value(adjustment.lower());
    }

    fn scroll_to(&self, index: usize) {
        let imp = self.imp();
        let labels = imp.labels.borrow();

        let label = match labels.get(index) {
            Some(l) => l,
            None => return,
        };

        // Before the first allocation there is nothing to scroll to.
        if label.height() == 0 {
            return;
        }

        let box_widget = imp.lines_box.get();
        let origin = gtk::graphene::Point::new(0.0, 0.0);
        let offset = match label.compute_point(&box_widget, &origin) {
            Some(point) => f64::from(point.y()),
            None => return,
        };

        let adjustment = imp.scrolled_window.vadjustment();
        let target = offset + f64::from(label.height()) / 2.0 - adjustment.page_size() / 2.0;
        let max = (adjustment.upper() - adjustment.page_size()).max(adjustment.lower());

        adjustment.set_value(target.clamp(adjustment.lower(), max));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn active_line_is_fully_opaque() {
        assert_eq!(opacity_for_distance(0), 1.0);
    }

    #[test]
    fn opacity_never_increases_with_distance() {
        let mut previous = opacity_for_distance(0);
        for distance in 1..20 {
            let current = opacity_for_distance(distance);
            assert!(
                current <= previous,
                "distance {} was brighter than {}",
                distance,
                distance - 1
            );
            previous = current;
        }
    }

    #[test]
    fn nearby_lines_are_visibly_dimmer_than_the_active_one() {
        // Falloff must be real before the floor is reached, or neighbouring
        // lines are indistinguishable from the active one.
        assert!(opacity_for_distance(1) < opacity_for_distance(0));
        assert!(opacity_for_distance(2) < opacity_for_distance(1));
        assert!(opacity_for_distance(3) < opacity_for_distance(2));
    }

    #[test]
    fn distant_lines_stay_visible() {
        // Lines must never vanish entirely, or the lyrics look truncated
        // rather than faded.
        for distance in 0..100 {
            assert!(opacity_for_distance(distance) >= 0.25);
        }
    }
}
