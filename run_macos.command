#!/bin/bash
cd -- "$(dirname -- "$0")" || exit 1
export PYTHONUTF8=1
run_exit=1
found_python=false
for candidate in python3.11 python3.12 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info[:2] in ((3,11),(3,12)) else 1)' >/dev/null 2>&1; then
        found_python=true
        "$candidate" run_all.py "$@"
        run_exit=$?
        break
    fi
done
if [ "$found_python" = false ]; then
    echo 'Please install Python 3.11 or 3.12 from https://www.python.org/downloads/'
fi
if [ "$#" -eq 0 ]; then
    read -r -p 'Press Enter to close...' ignored_input
fi
exit "$run_exit"
