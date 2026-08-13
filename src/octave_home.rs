use std::path::Path;

use adw::subclass::prelude::*;
use gtk::{glib, prelude::*, CompositeTemplate};
use lofty::{prelude::TaggedFileExt, probe::Probe};

use crate::audio::CoverCache;
use crate::library::Library;

mod imp {
    use super::*;

    #[derive(Debug, Default, CompositeTemplate)]
    #[template(resource = "/io/github/workbydivyanshu/Aubade/octave-home.ui")]
    pub struct OctaveHome {
        #[template_child]
        pub greeting_label: TemplateChild<gtk::Label>,
        #[template_child]
        pub recently_added_box: TemplateChild<gtk::Box>,
        #[template_child]
        pub most_played_box: TemplateChild<gtk::Box>,
    }

    #[glib::object_subclass]
    impl ObjectSubclass for OctaveHome {
        const NAME: &'static str = "AubadeOctaveHome";
        type Type = super::OctaveHome;
        type ParentType = gtk::Widget;

        fn class_init(klass: &mut Self::Class) {
            Self::bind_template(klass);

            klass.set_layout_manager_type::<gtk::BinLayout>();
            klass.set_css_name("octavehome");
            klass.set_accessible_role(gtk::AccessibleRole::Group);
        }

        fn instance_init(obj: &glib::subclass::InitializingObject<Self>) {
            obj.init_template();
        }
    }

    impl ObjectImpl for OctaveHome {
        fn dispose(&self) {
            while let Some(child) = self.obj().first_child() {
                child.unparent();
            }
        }
    }

    impl WidgetImpl for OctaveHome {}
}

glib::wrapper! {
    pub struct OctaveHome(ObjectSubclass<imp::OctaveHome>)
        @extends gtk::Widget,
        @implements gtk::Accessible, gtk::Buildable, gtk::ConstraintTarget;
}

impl Default for OctaveHome {
    fn default() -> Self {
        glib::Object::new::<Self>()
    }
}

impl OctaveHome {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn populate(&self, library: &Library) {
        let greeting = match glib::DateTime::now_local().map(|date_time| date_time.hour()) {
            Ok(hour) if hour < 12 => "Good morning",
            Ok(hour) if hour < 18 => "Good afternoon",
            _ => "Good evening",
        };
        self.imp().greeting_label.set_label(greeting);

        clear_box(&self.imp().recently_added_box);
        for album_index in library.recently_added_albums(12) {
            if let Some(album) = library.album(album_index) {
                let cover_path = library
                    .album_tracks(album_index)
                    .first()
                    .map(|track| track.path.as_path());
                self.imp()
                    .recently_added_box
                    .append(&album_card(&album.title, &album.artist, cover_path));
            }
        }

        clear_box(&self.imp().most_played_box);
        for track_index in library.most_played(12) {
            if let Some(track) = library.track(track_index) {
                self.imp()
                    .most_played_box
                    .append(&album_card(&track.title, &track.artist, Some(&track.path)));
            }
        }
    }
}

fn clear_box(box_widget: &gtk::Box) {
    while let Some(child) = box_widget.first_child() {
        box_widget.remove(&child);
    }
}

fn album_card(title: &str, artist: &str, cover_path: Option<&Path>) -> gtk::Box {
    let card = gtk::Box::builder()
        .orientation(gtk::Orientation::Vertical)
        .spacing(8)
        .width_request(160)
        .build();
    card.add_css_class("octave-card");

    let cover = gtk::Image::builder()
        .icon_name("folder-music-symbolic")
        .pixel_size(160)
        .width_request(160)
        .height_request(160)
        .build();
    if let Some(texture) = cover_texture(cover_path) {
        cover.set_paintable(Some(&texture));
    }
    cover.add_css_class("dim-label");
    card.append(&cover);

    let title_label = gtk::Label::builder()
        .label(title)
        .ellipsize(gtk::pango::EllipsizeMode::End)
        .xalign(0.0)
        .build();
    title_label.add_css_class("octave-body");
    card.append(&title_label);

    let artist_label = gtk::Label::builder()
        .label(artist)
        .ellipsize(gtk::pango::EllipsizeMode::End)
        .xalign(0.0)
        .build();
    artist_label.add_css_class("octave-muted");
    card.append(&artist_label);

    card
}

fn cover_texture(path: Option<&Path>) -> Option<gtk::gdk::Texture> {
    let path = path?;
    let probe = Probe::open(path).ok()?;
    let tagged = probe.guess_file_type().ok()?.read().ok()?;
    let tag = tagged.primary_tag().or_else(|| tagged.tags().first())?;
    let mut cache = CoverCache::global().lock().ok()?;
    cache.cover_art(path, tag).map(|(cover, _)| cover.texture().clone())
}
