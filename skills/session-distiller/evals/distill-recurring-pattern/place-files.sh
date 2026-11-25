#!/usr/bin/env bash
set -eu
cp -R "$(dirname "$0")/files/." .
python3 setup_env.py
