#!/usr/bin/env python3
"""Preserve a running iPXE menu while adding local boot and its timeout default."""
import argparse
from pathlib import Path
import re

BEGIN = '# BEGIN ANSIBLE PXE LOCALBOOT'
END = '# END ANSIBLE PXE LOCALBOOT'


def patch(text, address, default, timeout):
    if not text.startswith('#!ipxe') or not re.search(r'^:menu\s*$', text, re.M):
        raise ValueError('Expected an iPXE script with a :menu label')
    if not re.search(r'^:failed\s*$', text, re.M):
        raise ValueError('Expected an existing :failed handler; refusing to alter unknown layout')
    text = re.sub(r'(?ms)^' + re.escape(BEGIN) + r'\n.*?^' + re.escape(END) + r'\n?', '', text)
    if re.search(r'^:localboot\s*$', text, re.M):
        raise ValueError('Unmanaged :localboot label exists; inspect it before replacement')
    lines = text.splitlines()
    menus = [i for i, line in enumerate(lines) if line.startswith('menu ')]
    choices = [i for i, line in enumerate(lines) if line.startswith('choose ')]
    if len(menus) != 1 or len(choices) != 1:
        raise ValueError('Expected one menu and one choose command')
    # Remove only the localboot item this helper owns; preserve every installer.
    lines = [line for line in lines if not re.match(r'^item\s+localboot\s', line)]
    menu_index = next(i for i, line in enumerate(lines) if line.startswith('menu '))
    lines.insert(menu_index + 1, 'item localboot Boot from local hard disk')
    index = next(i for i, line in enumerate(lines) if line.startswith('choose '))
    choice = re.sub(r'\s+--default\s+\S+', '', lines[index])
    choice = re.sub(r'\s+--timeout\s+\S+', '', choice)
    lines[index] = choice.replace('choose ', f'choose --default {default} --timeout {timeout} ', 1)
    block = '\n'.join([
        BEGIN, ':localboot',
        f'chain http://{address}/boot/localboot.ipxe || goto failed',
        'goto menu', END,
    ])
    return '\n'.join(lines).rstrip() + '\n\n' + block + '\n'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--address', required=True)
    parser.add_argument('--default', choices=['localboot', 'exit'], default='localboot')
    parser.add_argument('--timeout', type=int, default=30000)
    args = parser.parse_args()
    args.destination.write_text(patch(args.source.read_text(), args.address, args.default, args.timeout))
