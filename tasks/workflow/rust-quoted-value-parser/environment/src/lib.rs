pub fn parse_line(line: &str) -> Option<(&str, &str)> {
    let (key, raw_value) = line.split_once('=')?;
    let value = raw_value.trim_matches('"').split('=').next()?;
    Some((key, value))
}
