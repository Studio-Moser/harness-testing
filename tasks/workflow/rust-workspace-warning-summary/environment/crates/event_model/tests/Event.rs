use event_model::Event;

#[test]
fn constructors_preserve_messages() {
    assert_eq!(Event::info("ready").message(), "ready");
    assert_eq!(Event::warning("slow").message(), "slow");
    assert_eq!(Event::error("failed").message(), "failed");
}
