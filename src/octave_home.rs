use adw::subclass::prelude::*;
use gtk::{glib, prelude::*, CompositeTemplate};

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
                self.imp()
                    .recently_added_box
                    .append(&album_card(&album.title, &album.artist));
            }
        }

        clear_box(&self.imp().most_played_box);
        for track_index in library.most_played(12) {
            if let Some(track) = library.track(track_index) {
                self.imp()
                    .most_played_box
                    .append(&album_card(&track.title, &track.artist));
            }
        }
    }
}

fn clear_box(box_widget: &gtk::Box) {
    while let Some(child) = box_widget.first_child() {
        box_widget.remove(&child);
    }
}

fn album_card(title: &str, artist: &str) -> gtk::Box {
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
