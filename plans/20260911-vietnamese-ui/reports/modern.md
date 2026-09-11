# Modern WebUI Vietnamese localization

Status: DONE

- Updated `webui/templates/index.html` with static Jinja translations, shared language selector/runtime, and explicit JavaScript translations for dialogs, buttons, status labels, pagination, date controls, import/change-email flows, and configuration rendering.
- Added `webui/locales/modern-vi.json` with 181 modern-specific Vietnamese entries. Common entries intentionally come from the legacy/shared catalogs merged by the runtime.
- Preserved Chinese grouping keys, configuration values, selectors, placeholder-empty sentinels, and persisted email-pool audit notes. Renamed existing local `t` bindings so they do not shadow the translation helper.
- Escaped translated attribute text, localized configuration accessibility labels and recommendation metadata, and translated API errors/toasts at presentation boundaries. Raw logs and account data remain untouched.

Validation: Acorn parses the complete final JavaScript. Representative Chinese traffic-renderer output matches the original implementation; original placeholder sentinel behavior is unchanged. Catalog JSON is valid, has no Chinese output text, and covers all modern-only display strings. Controller is running merged integration tests and browser review.

Existing placeholder overview cards were translated without adding new behavior. Existing server/runtime configuration help remains supplied by the shared configuration catalog.
