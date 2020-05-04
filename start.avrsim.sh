#!/bin/bash

# cleanup previus run (if any)
pkill -f "python3 ~/tre/scripts/avrsim.py"
rm avrsim*.vcd

# amount to spawn
END=1
if [ $# -gt 0 ]; then
	if [ "$1" == "clean" ]; then
		exit 0
	fi
	END=$1
fi

# spawn new
TAILS=""
for i in $(seq 1 $END); do
	PYTHONPATH=~/simulavr/src/python/ ~/tre/scripts/avrsim.py \
		-m atmega644 -s 20000000 \
		-p /tmp/simulavr${i} -b 250000 \
		-t PORTA.PORT,PORTB.PORT,PORTC.PORT -f avrsim${i}.vcd \
		~/klipper/out/klipper.elf &
	TAILS="${TAILS} -f avrsim${i}.vcd"
done

sleep 1

tail ${TAILS}

