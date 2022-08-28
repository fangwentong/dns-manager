DNS Manager
---

A command line tool to help you manage dns records

## Install

```
pip install https://github.com/fangwentong/dns-manager/archive/master.zip
```

## Usage

Write your config file (refer to [dns_sample.yml](conf/dns_sample.yml)), pass the file path to the command.

```
$ dns-manager

Usage:
    dns-manager <command> [/path/to/dns/config]

Commands:
    status    show current dns status
    update    load dns config from local, flush local config to name server


$ dns-manager status dns_sample.yml

status now [A] @.example.com -> 93.184.216.34
status now [A] www.example.com -> 93.184.216.34
status now [A] plus.example.com -> nil
```
