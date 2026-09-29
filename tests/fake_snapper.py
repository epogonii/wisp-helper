# SPDX-License-Identifier: GPL-2.0-or-later

"""Stands in for snapper in the D-Bus tests.

The tests copy it next to state.json, which holds the configs, and read back
calls.json to see what the helper ran.
"""

import json
import sys
import time
from pathlib import Path

HERE = Path(sys.argv[0]).parent
STATE = HERE / 'state.json'
CALLS = HERE / 'calls.json'


def fail(message):
    print(message, file=sys.stderr)
    sys.exit(1)


def main(args):
    with CALLS.open('a') as file:
        print(json.dumps(args), file=file)
    state = json.loads(STATE.read_text())
    time.sleep(state.get('sleep', 0))
    configs = state['configs']
    jsonout = args[0] == '--jsonout'
    if jsonout:
        args = args[1:]
    config = 'root'
    if args[0] == '-c':
        config, args = args[1], args[2:]
    command, *rest = args
    if command in state.get('fail', {}):
        fail(state['fail'][command])

    if command == 'list-configs' and jsonout:
        rows = [
            {'config': name, 'subvolume': values['SUBVOLUME']} for name, values in configs.items()
        ]
        print(json.dumps({'configs': rows}))
    elif config not in configs:
        fail('Unknown config.')
    elif command == 'get-config' and jsonout:
        print(json.dumps(configs[config]))
    elif command == 'set-config':
        configs[config].update(value.split('=', 1) for value in rest)
        STATE.write_text(json.dumps(state))
    else:
        fail(f'unexpected call: {args}')


if __name__ == '__main__':
    main(sys.argv[1:])
