/* Translate presentation strings, never API keys or user-entered values. */
(() => {
  'use strict';
  const catalog = JSON.parse(document.getElementById('ui-translations').textContent);
  const has = (key) => Object.prototype.hasOwnProperty.call(catalog, key);
  const escapeRegex = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const patterns = Object.entries(catalog).filter(([key]) => /\{\w+\}/.test(key)).map(([source, translation]) => {
    const names = [];
    let offset = 0;
    let pattern = '^';
    for (const match of source.matchAll(/\{(\w+)\}/g)) {
      pattern += escapeRegex(source.slice(offset, match.index)) + '([\\s\\S]*?)';
      names.push(match[1]);
      offset = match.index + match[0].length;
    }
    pattern += escapeRegex(source.slice(offset)) + '$';
    return {regex: new RegExp(pattern), names, translation, specificity: source.replace(/\{\w+\}/g, '').length};
  }).sort((a, b) => b.specificity - a.specificity);
  const interpolate = (value, vars) => value.replace(/\{(\w+)\}/g, (match, name) =>
    Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : match);

  window.t = (source, vars = {}) => {
    const text = String(source == null ? '' : source);
    if (has(text)) return interpolate(catalog[text], vars);
    // API messages may already have their variables interpolated by Python.
    for (const entry of patterns) {
      const match = text.match(entry.regex);
      if (match) {
        const values = Object.fromEntries(entry.names.map((name, i) => [name, match[i + 1]]));
        return interpolate(entry.translation, values);
      }
    }
    return interpolate(text, vars);
  };
  window.setUiLanguage = (language) => {
    if (!['vi', 'zh-CN'].includes(language)) return;
    const url = new URL(window.location.href);
    url.searchParams.set('lang', language);
    window.location.assign(url.href);
  };
})();
