use event_model::Event;

fn main() {
    let events = std::env::args().skip(1).map(|level| match level.as_str() {
        "warning" => Event::warning("warning"),
        "error" => Event::error("error"),
        _ => Event::info("info"),
    });
    println!("{}", summary_cli::render_summary(&events.collect::<Vec<_>>()));
}
