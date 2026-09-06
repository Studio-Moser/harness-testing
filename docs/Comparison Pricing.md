# Comparison Pricing

Comparison costs use one frozen standard-token rate table from `Versions.toml` for all contenders and retained baselines. These are normalized API-equivalent estimates, not provider invoices or incremental subscription spending. Original trial estimates and their pricing identities remain in the comparison evidence.

Sources checked September 5, 2026:

| Model | Ordinary input | Cache read | Cache write | Output |
| --- | ---: | ---: | ---: | ---: |
| [GPT-6 Astra](https://developers.openai.com/api/docs/models/gpt-6-astra) | $10 | $1 | $12.50 | $50 |
| [GPT-5.6 Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra) | $2 | $0.20 | $2.50 | $12 |
| [Claude Sonnet 4.6](https://platform.claude.com/docs/en/models/sonnet-4-6/overview) | $3 | $0.30 | $3.75 | $15 |

Additional routing models use [GPT-5.6 Sol](https://developers.openai.com/api/docs/models/gpt-5.6-sol) rates 4 / 0.40 / 5 / 20 and [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna) rates 0.20 / 0.02 / 0.25 / 1.20, in the table's column order. [Anthropic's pricing table](https://platform.claude.com/docs/en/about-claude/pricing) supplies Sonnet 5 (2 / 0.20 / 2.50 / 10), Opus 5 (5 / 0.50 / 6.25 / 25), and Fable 5 (10 / 1 / 12.50 / 50). These exact model identities are distinct from future versions and aliases.

Rates are USD per million tokens. Claude cache writes use the five-minute rate. This comparison excludes context-length premiums, longer cache TTL premiums, Fast/Batch/Flex modifiers, tool charges, taxes, and subscription pricing. It answers standardized token cost under these rates. It must not be labeled actual spend. Unknown model rates or incomplete usage produce unavailable cost; never borrow another model's rate.

When adding a model, verify its exact official pricing, record the source/date here and add all four rates. Effort variants share token rates. A pricing update reprices retained token evidence for a new comparison without mutating the original report. For invoice-equivalent accounting, retain request-level context size, service tier, cache TTL and tool charges before extending this policy.
