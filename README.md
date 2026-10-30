# TrueNAS Integration — kitusuo fork

> **This is a maintained fork of [tomaae/homeassistant-truenas](https://github.com/tomaae/homeassistant-truenas)**,
> run on its own: no upstream pull requests. It adds a test suite against a recorded TrueNAS SCALE 25.10, CI, and
> hardened dependency management. Install it in HACS as a custom repository (`kitusuo/homeassistant-truenas`,
> category *Integration*).
>
> **Development** (uv, Python 3.14): `make sync`, then `make check` — formatting (black), the tests with a 90 %
> coverage gate, and `pip-audit`. Dependencies move only through `make lock` / `make upgrade`, which never take a
> release younger than 7 days; Dependabot follows the same cooldown. Every GitHub Action is pinned by commit SHA.
> The test fixture `tests/fixtures/truenas_25_10.json` is a real recording, reduced to the fields the integration
> reads and scrubbed of names, serials, addresses and secrets.

[![check](https://github.com/kitusuo/homeassistant-truenas/actions/workflows/check.yml/badge.svg)](https://github.com/kitusuo/homeassistant-truenas/actions/workflows/check.yml)
[![validate](https://github.com/kitusuo/homeassistant-truenas/actions/workflows/hacs.yml/badge.svg)](https://github.com/kitusuo/homeassistant-truenas/actions/workflows/hacs.yml)
[![HACS: custom repository](https://img.shields.io/badge/HACS-custom%20repository-41BDF5.svg?style=plastic)](https://hacs.xyz/docs/faq/custom_repositories/)

![English](https://raw.githubusercontent.com/tomaae/homeassistant-truenas/master/docs/assets/images/flags/us.png)
![Portuguese](https://raw.githubusercontent.com/tomaae/homeassistant-truenas/master/docs/assets/images/flags/pt.png)

![Truenas Logo](https://raw.githubusercontent.com/tomaae/homeassistant-truenas/master/docs/assets/images/ui/header.png)

Monitor and control your TrueNAS CORE/SCALE device from Home Assistant.
 * Monitor System (Cpu, Load, Memory, Temperature, Network, ARC/L2ARC, Uptime)
 * Monitor Disks
 * Monitor Pools (including boot-pool)
 * Monitor Datasets
 * Monitor Replication Tasks
 * Monitor Snapshot Tasks
 * Control and Monitor Services
 * Control and Monitor Virtual Machines
 * Control and Monitor Jails (TrueNAS CORE only)
 * Control and Monitor Cloudsync
 * Create a Dataset Snapshot
 * Update Sensor
 * Reboot and Shutdown TrueNAS system
 

# Features
## Pools
Monitor status for each TrueNAS pool.

![Pools Health](https://raw.githubusercontent.com/tomaae/homeassistant-truenas/master/docs/assets/images/ui/pool_healthy.png)
![Pools Free Space](https://raw.githubusercontent.com/tomaae/homeassistant-truenas/master/docs/assets/images/ui/pool_free.png)

## Datasets
Monitor usage and attributes for each TrueNAS dataset.

![Datasets](https://raw.githubusercontent.com/tomaae/homeassistant-truenas/master/docs/assets/images/ui/dataset.png)

## Disks
Monitor temperature and attributes for each TrueNAS disk.

![Disks](https://raw.githubusercontent.com/tomaae/homeassistant-truenas/master/docs/assets/images/ui/disk.png)

## Virtual Machines
Control and monitor status and attributes for each TrueNAS Virtual Machines.
Virtual Machines control is available through services.

![Virtual Machines](https://raw.githubusercontent.com/tomaae/homeassistant-truenas/master/docs/assets/images/ui/vm.png)

## Jails
*TrueNAS CORE only*

Control and monitor status and attributes for each TrueNAS jail.
Jail control is available through services.

![Jails](https://raw.githubusercontent.com/tomaae/homeassistant-truenas/master/docs/assets/images/ui/jail.png)

## Cloudsync
Control and monitor status and attributes for each TrueNAS cloudsync task.
Jail control is available through services.

![Cloudsync](https://raw.githubusercontent.com/tomaae/homeassistant-truenas/master/docs/assets/images/ui/cloudsync.png)

## Replication Tasks
Monitor status and attributes for each TrueNAS replication task.

![Replication Tasks](https://raw.githubusercontent.com/tomaae/homeassistant-truenas/master/docs/assets/images/ui/replication.png)

## Snapshot Tasks
Monitor status and attributes for each TrueNAS snapshot task.

![Snapshot Tasks](https://raw.githubusercontent.com/tomaae/homeassistant-truenas/master/docs/assets/images/ui/snapshottask.png)

## Dataset Snapshot
Create a Dataset Snapshot using Homeassistant service.
Snapshot name will be automatically generated using datetime iso format with microseconds and "custom" prefix. 

![Snapshot UI](https://raw.githubusercontent.com/tomaae/homeassistant-truenas/master/docs/assets/images/ui/snapshot_ui.png)
![Snapshot YAML](https://raw.githubusercontent.com/tomaae/homeassistant-truenas/master/docs/assets/images/ui/snapshot_yaml.png)

## Services
Control and monitor status and attributes for each TrueNAS service.
Service control is available through services.

![Services](https://raw.githubusercontent.com/tomaae/homeassistant-truenas/master/docs/assets/images/ui/service.png)

## Reboot and Shutdown
Reboot or Shutdown a TrueNAS system.
Service control is available through services.
Target system uptime sensor.

![image](https://user-images.githubusercontent.com/36953052/221521930-f8f789e6-deec-4cc2-b11e-740caa056e44.png)

# Install integration
This fork is installed through [HACS](https://hacs.xyz/) as a **custom repository** (the "TrueNAS" entry in the HACS
default list is the original project):

1. HACS → ⋮ → *Custom repositories* → repository `https://github.com/kitusuo/homeassistant-truenas`, type
   *Integration* → *Add*.
2. Open "TrueNAS" in HACS → *Download*, then restart Home Assistant.

Replacing the original: remove the original's repository in HACS first; the integration domain (`truenas`) and its
config entries stay, so nothing needs to be set up again.

Minimum requirements:
* TrueNAS Core 12.0 or TrueNAS Scale (Any version) — tested against TrueNAS SCALE 25.10
* Home Assistant 2026.10.0 (`hacs.json`): device parents are given by registry id (`via_device_id`), which older
  releases do not have — tested against 2026.10

## Using TrueNAS development branch
If you are using development branch for TrueNAS, some features may stop working.

## Setup integration
1. Create an API key for Home Assistant on your TrueNAS system.

![Setup step 1](https://raw.githubusercontent.com/tomaae/homeassistant-truenas/master/docs/assets/images/ui/setup_1.png)
![Setup step 2](https://raw.githubusercontent.com/tomaae/homeassistant-truenas/master/docs/assets/images/ui/setup_2.png)
![Setup step 3](https://raw.githubusercontent.com/tomaae/homeassistant-truenas/master/docs/assets/images/ui/setup_3.png)

2. Setup this integration for your TrueNAS device in Home Assistant via `Configuration -> Integrations -> Add -> TrueNAS`.
You can add this integration several times for different devices.

NOTES: 
- If you dont see "TrueNAS" integration, clear your browser cache.

![Add Integration](https://raw.githubusercontent.com/tomaae/homeassistant-truenas/master/docs/assets/images/ui/setup_integration.png)
* "Name of the integration" - Friendly name for this router
* "Host" - Use hostname or IP
* "API key" - TrueNAS API key for Home Assistant 

# Development

## Translation
The translations come from the original project, which runs them on
[Lokalise](https://app.lokalise.com/public/9252786762290237258f09.36273104/).

## Enabling debug
To enable debug for TrueNAS integration, add following to your configuration.yaml:
```
logger:
  default: info
  logs:
    custom_components.truenas: debug
```
