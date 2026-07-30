# Lab note: scanner IP 203.0.113.10

> 类型: intel-lab-note
> tags: scanner, demo, ioc
> 主题slug: scanner-203

## Summary

Internal lab notes mark `203.0.113.10` as a **suspicious scanner** often paired with
`evil.example.com` beaconing in tabletop exercises.

## Related indicators

| Indicator | Type | Note |
|-----------|------|------|
| `203.0.113.10` | ipv4 | TEST-NET-3 demo scanner |
| `evil.example.com` | domain | Often resolved after the scan |
| `aabbccddeeff00112233445566778899` | md5 | Sample hash seen on disk in Alert 01 |

## Assessment guidance

Prefer `enrich_ioc` for structured stub cards, then cite this note (or vendor corpus
under `sources/seed/intel/vendor/`) when drafting a one-page brief. Do **not** claim
automatic blocking or quarantine.

## Source

Demo fixture for the intel scenario RAG path (standing seed).
