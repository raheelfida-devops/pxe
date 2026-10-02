# PXE setup agent

## Purpose and entrypoint

Set up and verify a Linux PXE VM to offer interactive Linux and Windows installation over an isolated client network. Use dnsmasq for DHCP/DNS/TFTP, HTTP-capable iPXE for the boot menu, nginx for boot assets, NFS for Ubuntu live media, and Samba plus wimboot for Windows. Read [skills.md](skills.md) before implementation.

For new VMs use the reusable [Ansible deployment](ansible/README.md). It derives configuration from the recovered PXE session without importing the old VM's root filesystem or credentials. Runtime service logs are collected at `/var/log/pxe.log`. Its menu includes a separate local hard-disk boot choice for BIOS and configurable x64 UEFI bootloaders. Do not deploy its inventory to the existing running PXE VM by default.

These are the two explicitly requested project documents. `agent.md` is not Codex's automatically loaded `AGENTS.md`; `skills.md` is a runbook, not an installed skill's `SKILL.md`. Load them explicitly. Writing these documents does not configure or validate the server.

## Local context and discovery

Observed on 2026-10-02: this workspace had no project files. The saved VM definition is `/home/raheel/VirtualBox VMs/pxe/pxe.vbox`; its first adapter uses NAT with host SSH port `2028`, and its second adapter bridges to `enp0s31f6`. The `ISOs` shared folder points read-only to `/home/raheel/Desktop/ISO`. Saved configuration does not establish live VM state or network isolation.

Earlier session notes reported Ubuntu Server reaching its BIOS installer, but UEFI and Windows were unverified. Guest addresses, services, credentials, and mounts must be discovered again. Never describe historical results as current verification.

Start with these read-only commands on the host:

```bash
VBoxManage list vms
VBoxManage list runningvms
VBoxManage showvminfo pxe --machinereadable
ip -br address
ip route
ls -lh /home/raheel/Desktop/ISO
```

Use an authorized SSH account on port `2028`; do not embed passwords in documents, command arguments, scripts, or logs. Inside the guest inspect:

```bash
cat /etc/os-release
ip -br address
ip route
findmnt /srv/pxe/iso
df -h /srv /var
systemctl --no-pager status dnsmasq nginx smbd nftables
sudo ss -lntup
sudo nft list ruleset
```

Inspect existing network, dnsmasq, nginx, Samba, and mount configuration before making a replacement. Preserve unrelated rules and services. Verify the host ISO share is readable and mounted read-only after guest restart.

## Agent responsibilities

The coordinating agent owns discovery, integration, change sequencing, backups, and the final evidence report. When delegation is available, use these specialists for distinct responsibilities:

| Agent | Responsibility | Handoff evidence |
| --- | --- | --- |
| network-engineer | Isolated topology, address plan, DHCP/TFTP, BIOS/UEFI loaders, scoped firewall | Interface mapping, configuration validation, DHCP/transfer logs |
| linux specialist | Ubuntu and Debian boot assets, release matching, installer-source access | Media hashes, boot arguments, installer results per firmware |
| Windows specialist | ISO extraction, WinPE/wimboot, Samba installation sources, drivers | WIM architecture, share access, Windows Setup results |
| reviewer | Review procedures, menu publication, rollback, compatibility claims | Concrete findings and resolved changes |

Workers are not alone in the workspace: assign separate configuration or document sections, do not revert others' edits, and report integration dependencies. Do not let multiple agents change networking or restart the same services concurrently. If delegation is unavailable, perform these responsibilities sequentially.

## Implementation contract

1. Capture baseline configuration, service enablement, VM adapter settings, routes, and firewall rules. Record backup paths and a restoration procedure before editing.
2. Establish isolation. For VM-only testing, use a dedicated VirtualBox internal network for the second adapter and test clients. For physical clients, bridge only to a dedicated wired switch with no uplink or competing DHCP server. Retain NAT for management and server downloads. Do not start a DHCP address allocator on an ordinary LAN.
3. Use the default client subnet `192.168.77.0/24`, server `192.168.77.1`, and lease range `.100`–`.200` only after checking for conflicts. Bind DHCP/TFTP to the discovered guest client interface. Do not advertise a gateway or DNS server unless the guest actually provides it.
4. Preserve source ISOs read-only at `/srv/pxe/iso`. Use `/srv/pxe/boot` for HTTP boot assets, `/srv/pxe/tftp` for loaders, and `/srv/pxe/windows` for extracted Windows source trees. Verify storage before extraction; never alter source images.
5. Install/configure the services and loaders using the runbook. Stage menu entries privately; enable them only after their required assets exist and their installer path has been tested. Keep a return-to-menu path and default to exit rather than installation.
6. Start with Ubuntu Server and Windows 10 22H2, then cover every remaining ISO using its appropriate path or an explicit compatibility limitation. Inventory driver media and disk images without treating them as installer entries.
7. Validate BIOS and x86_64 UEFI separately with Secure Boot disabled, then validate service and mount persistence during an authorized maintenance window. Never shut down or reset an existing VM merely to inspect it.

## Acceptance and reporting

- For each supported image/firmware pair, record a DHCP lease, correct loader, HTTP menu/assets, installer launch, and access to the full installation source. Windows must detect the test disk and reach disk selection; Linux must reach a disk-selection or partitioning stage after source detection.
- Use disposable clients and empty test disks. Stop before committing partitions or installing; unattended disk writes are outside this setup's default scope.
- Distinguish `inventoried`, `assets prepared`, `menu reached`, `installer reached`, `source verified`, and `blocked`. An HTTP 200 or a menu screenshot alone is insufficient.
- Keep XP, Longhorn, FreeBSD, OPNsense, and any failing firmware pair unavailable in the production menu until independently proven. VM success does not establish physical-machine support.
- Report changes, configuration paths, checks performed, image hashes, client firmware/resources, results, blockers, and rollback location. State any unavailable SSH, missing privilege, missing media, or untested restart plainly.

## Rollback

If DHCP is observed outside the isolated client network, stop the newly introduced DHCP service immediately and restore the captured configuration. Restore previous service enablement, network configuration, firewall changes, and boot-menu files from the baseline; verify management SSH remains reachable. Restore VM adapter settings only in an appropriate maintenance window. Remove only new disposable assets that are clearly identified; retain the original ISO collection and pre-existing VM disks.
