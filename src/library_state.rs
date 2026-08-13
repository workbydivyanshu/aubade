use std::sync::Mutex;
use once_cell::sync::OnceCell;
use crate::library::Library;

pub struct LibraryState;

impl LibraryState {
    pub fn global() -> &'static Mutex<Library> {
        static CACHE: OnceCell<Mutex<Library>> = OnceCell::new();

        CACHE.get_or_init(|| {
            let c = Library::new();
            Mutex::new(c)
        })
    }
}
