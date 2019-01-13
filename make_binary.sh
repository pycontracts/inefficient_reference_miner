#!/bin/bash
cython miner.pyx -3 --embed
gcc -Os -I /usr/include/python3.6m -o miner miner.c -lpython3.6m -lpthread -lm -lutil -ldl -static -lz -lexpat
strip miner
