
## Future Enhancements

- Push notifications ("your recycling is tomorrow")
- Health-based routing: automatically fall back to UKBCD scraper when HACS scraper is failing
- Cache warming: nightly re-scrape of high-traffic UPRNs
- Runtime fallback logic: if primary scraper errors, try alternate source before returning 503
