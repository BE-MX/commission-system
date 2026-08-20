# Localization and timing

## Resolve geography before language

Require a sourced ISO country, city/region when the country has multiple timezones, and a country-compatible IANA timezone. A country alone is insufficient for the United States, Canada, Australia, Brazil, Mexico, Russia, Indonesia, and other multi-zone markets. Do not infer location from an email top-level domain alone.

Select the business language in this order:

1. the recipient's own professional page or prior correspondence;
2. the company's contact, team, or local-market pages;
3. a clearly identified local office's primary published language;
4. the country's dominant business language only when it is unambiguous.

For multilingual markets such as Canada, Belgium, Switzerland, Luxembourg, Singapore, India, South Africa, or a company serving a different-language market, do not guess. State the evidence or request a human choice. English is acceptable only when the evidence supports English for that recipient or market; it is not a universal fallback.

## Write natively

Compose directly in the selected language and follow its business conventions:

- use the locally normal salutation, name order, honorific, punctuation, capitalization, and level of formality;
- prefer short idiomatic sentences and concrete verbs over literal translations of Chinese sales phrases;
- preserve product names and approved technical terms, but adapt sentence structure and CTA politeness;
- avoid inflated adjectives, ceremonial openings, canned transitions, excessive em dashes, stacked rhetorical questions, and phrases that merely announce relevance;
- do not imitate slang, regional dialect, or intimacy without recipient-specific evidence;
- read the final message aloud mentally: each sentence should sound like something a competent local salesperson would naturally send.

Do a back-meaning check in Chinese for factual fidelity, not a word-for-word back-translation. If naturalness in the selected language is uncertain, mark `NOT READY TO SEND` and require a native-speaker review.

## Compute the first workday window

Use `outreach-queue schedule` while drafting and `outreach-queue preview` only after a send request; do not calculate timestamps manually. Supply:

- `--country` as ISO 3166-1 alpha-2;
- `--timezone` as a country-compatible IANA timezone;
- optional `--state` when a subdivision is known and affects holidays;
- `--office-start` from sourced company hours, or `09:00` as a disclosed default;
- `--language` as the evidenced BCP 47 language tag;
- `--language-source` as `recipient`, `company`, or `country`;
- `--language-basis` as a short description of the evidence used.

The scheduler chooses the next occurrence five minutes after office opening, skips the country's weekend and public/bank holidays, and records both local and UTC time. If confirmation happens after that day's opening window, it selects the next eligible workday. If the computer is asleep and misses the window by more than 30 minutes, the dispatcher rolls the message to the next eligible opening rather than sending late.

Treat a public-holiday library as a scheduling guard, not legal advice. When location, subdivision, local working week, company hours, or a special working day is uncertain, stop and ask. Never silently schedule using the sender's timezone.
