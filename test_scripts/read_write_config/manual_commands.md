## Manual config steps (after flashing and AP setup)

1. Export existing partition table
```esptool --port /dev/ttyACM4 read_flash 0x8000 0x1000 partition_table_ACM4.bin
```
2. Convert partition table bin to readable .csv file
```python /opt/esp-idf/components/partition_table/gen_esp32part.py partition_table_ACM4.bin > partitions_ACM4.csv
```
3. Review the patition table to find the SPIFFS config memory location/address
```more partitions.csv
```
4. Export the config file from memory location
```esptool --port /dev/ttyACM4 --baud 921600 read-flash 0x310000 0xE0000 config_dump_ACM4.bin
```
5. Extract json data from .bin SPIFFS file
```mkdir config_ACM4 && mkspiffs -u config_ACM4 config_dump_ACM4.bin
```
6. Review config and make necessary adjustments
```cd config_json && nano config.json
```
7. Create config.bin for import from new config.json in folder
```cd .. && mkspiffs -c config_json/ -p 256 -b 8192 -s 0xe0000 config.bin
```
8. Write config.bin to miner
```esptool.py --port /dev/ttyACM2 --baud 921600 write_flash 0x310000 config.bin
```
9. Confirm config loaded correctly, monitor tty
```echo /dev/ttyADMC0 > validation