//! `juhradiald --import` reads a zip somebody handed the user. Whatever its
//! entries are called and hold, the import must not panic and must not write
//! outside the configuration directory.
#![no_main]

use std::io::Write;

use libfuzzer_sys::fuzz_target;
use zip::write::SimpleFileOptions;

const MANIFEST: &[u8] = br#"{"app":"juhradial-mx","format":1,"version":"fuzz","created":"","files":[]}"#;

fuzz_target!(|entries: Vec<(String, Vec<u8>)>| {
    let root = tempfile::tempdir().expect("temp dir");
    let config_dir = root.path().join("config");
    let archive = root.path().join("backup.zip");
    {
        let mut zip = zip::ZipWriter::new(std::fs::File::create(&archive).expect("archive"));
        let options = SimpleFileOptions::default();
        zip.start_file(juhradiald::backup::MANIFEST, options).expect("manifest entry");
        zip.write_all(MANIFEST).expect("manifest");
        for (name, data) in entries.iter().take(16) {
            // A name the zip writer itself refuses (a duplicate) is not a test case.
            if name != juhradiald::backup::MANIFEST && zip.start_file(name.as_str(), options).is_ok() {
                zip.write_all(data).expect("entry");
            }
        }
        zip.finish().expect("archive end");
    }

    let _ = juhradiald::backup::import(&config_dir, &archive);

    for entry in std::fs::read_dir(root.path()).expect("list").flatten() {
        let name = entry.file_name();
        assert!(
            name == "config" || name == "backup.zip",
            "the import wrote {name:?} next to the configuration directory"
        );
    }
});
