#!/usr/bin/env bash
# Restore the demo data (4 profiles, 1 household) from seed/ into data/.
set -euo pipefail
cd "$(dirname "$0")"
rm -rf data && cp -r seed data
echo "Demo data restored: $(ls data/profiles | wc -l) profiles."
