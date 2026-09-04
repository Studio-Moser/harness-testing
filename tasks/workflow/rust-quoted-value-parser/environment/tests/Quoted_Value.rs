use config_line::parse_line;

#[test]
fn unquoted_value_parses() {
    assert_eq!(parse_line("mode=fast"), Some(("mode", "fast")));
}

#[test]
fn quoted_value_preserves_embedded_equals() {
    assert_eq!(parse_line(r#"token="a=b""#), Some(("token", "a=b")));
}
