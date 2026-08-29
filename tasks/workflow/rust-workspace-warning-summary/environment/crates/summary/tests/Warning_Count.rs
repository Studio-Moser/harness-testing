use event_model::Event;
use summary::summarize;

#[test]
fn counts_warning_events() {
    let events = [
        Event::info("ready"),
        Event::warning("slow"),
        Event::warning("retrying"),
        Event::error("failed"),
    ];

    let result = summarize(&events);

    assert_eq!(result.event_count, 4);
    assert_eq!(result.warning_count, 2);
}
