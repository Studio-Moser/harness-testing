use event_model::Event;
use summary::summarize;

pub fn render_summary(events: &[Event]) -> String {
    let result = summarize(events);
    format!(r#"{{"event_count":{}}}"#, result.event_count)
}
