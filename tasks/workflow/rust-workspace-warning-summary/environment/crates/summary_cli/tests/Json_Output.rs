use std::process::Command;

#[test]
fn json_output_includes_warning_count() {
    let output = Command::new(env!("CARGO_BIN_EXE_summary_cli"))
        .args(["info", "warning", "warning", "error"])
        .output()
        .expect("summary_cli should run");

    assert!(output.status.success());
    assert_eq!(
        String::from_utf8(output.stdout).expect("stdout should be UTF-8"),
        "{\"event_count\":4,\"warning_count\":2}\n",
    );
}
