// Things Tim does not want to read from a coding agent. Each counter is matched
// case-insensitively against the assistant's user-visible messages. Edit freely; the
// Behavior table re-scores every retained transcript on the next build.
export const ANNOYANCE_COUNTERS = Object.freeze([
  {
    key: "sycophancy",
    label: "Sycophantic openers",
    phrases: [
      "great question", "excellent question", "good question", "great point", "good catch",
      "you're absolutely right", "you are absolutely right", "you're right", "absolutely!",
      "certainly!", "of course!", "happy to help", "i'd be happy to", "i would be happy to"
    ]
  },
  {
    key: "apologies",
    label: "Apologies",
    phrases: ["i apologize", "apologies", "sorry for", "my mistake", "my apologies"]
  },
  {
    key: "hedging",
    label: "Hedging",
    phrases: [
      "it seems", "it appears", "i think", "i believe", "probably", "might be", "may be worth",
      "should be fine", "hopefully", "it's possible that", "it is possible that"
    ]
  },
  {
    key: "closing_offers",
    label: "Closing offers",
    phrases: [
      "let me know if", "feel free to", "would you like me to", "want me to", "shall i",
      "if you'd like", "if you would like", "happy to", "just say the word", "don't hesitate"
    ]
  },
  {
    key: "meta_summaries",
    label: "Unasked summaries",
    phrases: ["in summary", "to summarize", "summary:", "recap:", "here's what i did", "here is what i did", "what i changed:", "what changed:"]
  },
  {
    key: "filler",
    label: "Filler",
    phrases: [
      "it's worth noting", "it is worth noting", "worth mentioning", "note that", "importantly",
      "as you can see", "as mentioned", "essentially", "basically", "simply", "just", "actually"
    ]
  },
  {
    key: "self_praise",
    label: "Self-praise",
    phrases: ["robust", "comprehensive", "seamless", "elegant", "clean and", "production-ready", "best practice", "best practices"]
  }
]);

// Punctuation habits counted per assistant message.
export const ANNOYANCE_PUNCTUATION = Object.freeze([
  {key: "em_dashes", label: "Em dashes", pattern: /—/g},
  {key: "exclamations", label: "Exclamation marks", pattern: /!/g},
  {key: "emoji", label: "Emoji", pattern: /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/gu}
]);
