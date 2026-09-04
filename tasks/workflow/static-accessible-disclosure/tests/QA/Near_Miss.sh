#!/usr/bin/env bash
set -euo pipefail

cd /app
perl -0pi -e "s/panel.hidden = !panel.hidden/const expanded = !panel.hidden\n    panel.hidden = expanded\n    trigger.setAttribute('aria-expanded', String(!expanded))/" src/Disclosure.js
