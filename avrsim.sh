#!/bin/bash

if [ $# -lt 1 ]; then
	echo "syntax: $0 tty_num"
	exit 1
fi

PYTHONPATH=~/simulavr/src/python/ ./scripts/avrsim.py -m atmega644 -s 20000000 -p /tmp/simulavr$1 -b 250000 out/klipper.elf -t PORTA.PORT,PORTC.PORT
