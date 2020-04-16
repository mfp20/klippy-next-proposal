#!/bin/bash

pkill -f /home/user/klippy-env/bin/python
rm klippy.log

CFG="printer.cfg"
GCODE=""

if [ "$1" == "simple" ];then
	CFG="simple.printer.cfg"
elif [ "$1" == "gcode" ];then
	GCODE=" -i test/klippy/move.gcode"
fi


/home/user/klippy-env/bin/python klippy/klippy.py ${CFG} -l klippy.log -v ${GCODE} &

sleep 0.1

tail -f klippy.log

