DNS Manager
---

DNS Manager is a Python command-line tool for managing DNS records across multiple vendors. It can load DNS
configurations from a local file and update the DNS records on the name server.

## Install

This program requires Python 3. Install this program by running:

```
pip install https://github.com/fangwentong/dns-manager/archive/master.zip
```

## Usage

```
dns-manager <command> [/path/to/dns/config]
```

### Commands

- `status` - show current DNS status
- `update` - load DNS config from a local file and flush local config to the name server

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

### DNS Configuration File

DNS Manager requires a DNS configuration file in YAML format. An example of the file format is provided in
the [dns_sample.yml](conf/dns_sample.yml) file.

### Supported DNS vendors

The following DNS vendors are supported:

- Namecheap
- Alibaba Cloud (Aliyun)
- Cloudflare

## License

This program is licensed under the MIT License. Please see the [LICENSE](LICENSE) file for details.