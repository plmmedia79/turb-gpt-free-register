# Vietnamese and Chinese WebUI

Status: complete.

- Modern UI: dedicated agent owns template and translation catalog.
- Legacy UI and login: dedicated agent owns templates and catalog.
- Configuration and API message copy: dedicated agent owns catalogs.
- Main coordinator: shared locale selection, runtime, integration, tests and browser verification.

Acceptance: Vietnamese reads naturally; Chinese remains selectable; choice persists through login/reload; both UI versions localize static content, dynamic controls, dialogs, configuration help and errors. Data, credentials, protocol values and raw diagnostic logs retain their original content. No registration is needed for UI validation.

Validation: rendered template JavaScript syntax, locale persistence and fallback tests, existing auth tests, browser walkthrough of pages/modals in both languages, config catalog coverage and independent review.

Completed validation: 31 WebUI tests passed. Browser verified both language choices, login, all five tabs in modern/legacy, all 14 legacy configuration groups, import modal and date picker. Independent review verified 158 interpolated-message roundtrips; all findings fixed. WebUI running locally on port 5087. No account registration was performed as part of localization validation.
