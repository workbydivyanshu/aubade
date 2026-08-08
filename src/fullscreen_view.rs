// SPDX-FileCopyrightText: 2026
// SPDX-License-Identifier: GPL-3.0-or-later

use adw::subclass::prelude::*;
use gtk::{gdk, glib, prelude::*, CompositeTemplate};

use crate::{blurred_backdrop::BlurredBackdrop, lyrics_view::LyricsView};

mod imp {
    use super::*;

    #[derive(Debug, Default, CompositeTemplate)]
    #[template(resource = "/io/github/workbydivyanshu/Aubade/fullscreen-view.ui")]
    pub struct FullScreenView {
        #[template_child]
        pub backdrop: TemplateChild<BlurredBackdrop>,
        #[template_child]
        pub lyrics_view: TemplateChild<LyricsView>,
        #[template_child]
        pub cover_thumb: TemplateChild<gtk::Image>,
        #[template_child]
        pub title_label: TemplateChild<gtk::Label>,
        #[template_child]
        pub artist_label: TemplateChild<gtk::Label>,
        #[template_child]
        pub fullscreen_play_button: TemplateChild<gtk::Button>,
    }

    #[glib::object_subclass]
    impl ObjectSubclass for FullScreenView {
        const NAME: &'static str = "AubadeFullScreenView";
        type Type = super::FullScreenView;
        type ParentType = gtk::Widget;

        fn class_init(klass: &mut Self::Class) {
            Self::bind_template(klass);

            klass.set_layout_manager_type::<gtk::BinLayout>();
            klass.set_css_name("fullscreenview");
            klass.set_accessible_role(gtk::AccessibleRole::Group);
        }

        fn instance_init(obj: &glib::subclass::InitializingObject<Self>) {
            BlurredBackdrop::static_type();
            LyricsView::static_type();
            obj.init_template();
        }
    }

    impl ObjectImpl for FullScreenView {
        fn dispose(&self) {
            while let Some(child) = self.obj().first_child() {
                child.unparent();
            }
        }
    }

    impl WidgetImpl for FullScreenView {}
}

glib::wrapper! {
    pub struct FullScreenView(ObjectSubclass<imp::FullScreenView>)
        @extends gtk::Widget,
        @implements gtk::Accessible, gtk::Buildable, gtk::ConstraintTarget;
}

impl Default for FullScreenView {
    fn default() -> Self {
        glib::Object::new::<Self>()
    }
}

impl FullScreenView {
    /// The shared lyrics widget. The window drives this and the panel view
    /// from the same handlers, so the two cannot drift out of sync.
    pub fn lyrics_view(&self) -> LyricsView {
        self.imp().lyrics_view.get()
    }

    pub fn set_cover(&self, cover: Option<gdk::Texture>) {
        let imp = self.imp();

        match &cover {
            Some(texture) => imp.cover_thumb.set_paintable(Some(texture)),
            None => imp.cover_thumb.set_paintable(gdk::Paintable::NONE),
        }

        imp.backdrop.set_texture(cover);
    }

    /// Mirrors the play/pause icon so the full-screen transport reflects
    /// playback state, like the main controls do.
    pub fn set_playing(&self, playing: bool) {
        let icon = if playing {
            "media-playback-pause-symbolic"
        } else {
            "media-playback-start-symbolic"
        };
        self.imp().fullscreen_play_button.set_icon_name(icon);
    }

    pub fn set_details(&self, title: &str, artist: &str) {
        self.imp().title_label.set_label(title);
        self.imp().artist_label.set_label(artist);
    }
}
