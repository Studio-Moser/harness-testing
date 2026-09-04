use event_model::Event;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Summary {
    pub event_count: usize,
}

pub fn summarize(events: &[Event]) -> Summary {
    Summary {
        event_count: events.len(),
    }
}
