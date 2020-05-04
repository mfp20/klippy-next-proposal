#!/bin/bash

pkill -f /home/user/klippy3-env/bin/python

CFG="printer.cfg"
GCODE=""

if [ "$1" == "simple" ];then
	CFG="printer.simple.cfg"
elif [ "$1" == "gcode" ];then
	GCODE=" -i test/klippy/move.gcode"
fi


/home/user/klippy3-env/bin/python klippy/klippy.py -c ${CFG} -L -v ${GCODE}

