# Legacy WebUI and login localization

Status: DONE

Updated `index_legacy.html` and `login.html` with explicit presentation-only `t`/`tr` calls, shared language controls, and localized dynamic dialogs, pagination, status labels, tooltips, configuration displays, and feedback. Added 597 Vietnamese catalog entries in `legacy-vi.json`, shared with the modern interface where source wording overlaps.

Internal configuration group/section identifiers, option values, placeholder recognition, stored notes, logs, account data, and credentials remain unchanged. Existing local `t` variables that conflicted with translation calls were renamed. API and raw-fetch errors are translated before display; translated static dynamic attributes are escaped.

Validation: both Jinja templates compile; isolated Flask Vietnamese renders contain no visible Chinese apart from the 中文 language switch; all explicit translation keys and section metadata are covered by merged catalogs; legacy JavaScript passes `node --check`; scoped `git diff --check` passes. Browser interaction verification remains with the controller's integrated validation.
