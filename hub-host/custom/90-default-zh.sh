#!/bin/sh
# Appended to runtime-config.js, which the web app loads before i18next starts.
# Sets the UI language to Simplified Chinese once per browser; the language
# switcher in the UI keeps working afterwards.
set -eu
cat >> /usr/share/nginx/html/runtime-config.js <<'JS'
;(function () {
  try {
    if (localStorage.getItem('skillhub.defaultLang') !== 'zh-CN') {
      localStorage.setItem('i18nextLng', 'zh-CN');
      localStorage.setItem('skillhub.defaultLang', 'zh-CN');
    }
  } catch (e) { /* storage disabled: fall back to the browser language */ }
})();
JS
