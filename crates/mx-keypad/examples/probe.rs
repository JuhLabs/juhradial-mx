use mx_keypad::{discover, parse_input, Input, KeySet, KeyWindow, Keypad};
use std::io;
use std::time::{Duration, Instant};

fn exercise(keypad: &mut Keypad, seconds: u64) -> io::Result<()> {
    keypad.init()?;
    let colors: [&[u8]; 3] = [
        include_bytes!("../tests/fixtures/red.jpg"),
        include_bytes!("../tests/fixtures/green.jpg"),
        include_bytes!("../tests/fixtures/blue.jpg"),
    ];
    for key in 1..=9 {
        keypad.write_image(KeyWindow::new(key).unwrap(), colors[(key as usize - 1) % 3])?;
    }
    println!("Nine plates ready: red, green, blue columns. Listening for {seconds} seconds.");
    let mut previous = KeySet::default();
    let mut pages = Vec::new();
    let deadline = Instant::now() + Duration::from_secs(seconds);
    while Instant::now() < deadline {
        let Some(data) = keypad.read_report(Duration::from_millis(100))? else { continue };
        match parse_input(&data) {
            Some(Input::Keys(keys)) => {
                let diff = keys.diff(previous);
                for key in diff.up { println!("key {key} up"); }
                for key in diff.down { println!("key {key} down"); }
                previous = keys;
            }
            Some(Input::Pages(next)) => {
                for button in &next {
                    if !pages.contains(button) { println!("page {button:?} down"); }
                }
                for button in &pages {
                    if !next.contains(button) { println!("page {button:?} up"); }
                }
                pages = next;
            }
            None => {}
        }
    }
    Ok(())
}

fn main() -> io::Result<()> {
    let seconds = std::env::args().nth(1).unwrap_or_else(|| "30".into()).parse::<u64>()
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidInput, "Usage: probe [seconds]"))?;
    let info = discover()?.into_iter().next()
        .ok_or_else(|| io::Error::new(io::ErrorKind::NotFound, "No MX Keypad found"))?;
    println!("Opening {} ({})", info.path.display(), info.name);
    let mut keypad = Keypad::open(&info.path)?;
    let result = exercise(&mut keypad, seconds);
    let reset = keypad.reset_to_logo();
    if reset.is_ok() { println!("Reset to logo"); }
    result.and(reset)
}
