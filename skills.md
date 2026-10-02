# PXE setup runbook

## How to use this runbook

Read [agent.md](agent.md) first. Commands below are implementation examples to run on the Linux PXE guest unless marked **host** or **WinPE**. They have not been run against the guest in this documentation task. Substitute the discovered client interface and inspect existing configuration before writing files. Do not paste the entire document into a shell.

For repeatable deployment to a new Ubuntu/Debian VM, use [ansible/README.md](ansible/README.md). That implementation incorporates later session corrections: NFS-mounted Ubuntu live roots with NFSv3 TCP/UDP available, pinned Debian netboot assets, the corrected WinPE launcher, scoped NAT, and central `/var/log/pxe.log` with rotation. The HTTP ISO examples below are alternate manual procedures; they are not the Ansible deployment's Ubuntu transport. An incomplete unsigned Debian DVD mirror remains disabled.

This runbook applies the skill-creator guidance: keep task-specific constraints, expose conditional procedures by OS, and validate observable boot behavior. It is a project reference, not an installed Codex skill. Relevant execution roles are network-engineer, Linux administrator, Windows deployment specialist, and reviewer.

Defaults: interactive installs; x86 BIOS and x86_64 UEFI; Secure Boot disabled. Source media stays read-only. An ISO filename is an inventory label, not proof of release, architecture, authenticity, or PXE compatibility.

## 1. Discover, back up, and isolate

Use the discovery commands in `agent.md`. Record the guest OS, adapters, address assignments, existing DHCP services, mount ownership, service configuration, storage, and the actual account used for management.

Before modifying existing files, make a dated backup outside the served directories. Copy the relevant existing `/etc/dnsmasq.conf`, `/etc/dnsmasq.d`, nginx, Samba, network configuration, and mount configuration with ownership preserved; note missing paths rather than creating fake baseline files. Save `nft list ruleset` and service enablement status. Capture `VBoxManage showvminfo` on the **host**. Do not flush firewall rules or overwrite all of `/etc/fstab`.

For VM-only tests, place the server's second adapter and test clients on a dedicated internal network such as `pxe-lab`; keep management on NAT. Apply adapter changes only when the VM state and maintenance window permit them. For physical testing, use a dedicated switch without a LAN uplink. The saved bridged adapter is not evidence of isolation.

Example address plan:

| Item | Default |
| --- | --- |
| Client network | `192.168.77.0/24` |
| Server client interface | Discover via `ip -br link`; examples below use `enp0s8` |
| Server IP | `192.168.77.1/24` |
| DHCP pool | `192.168.77.100`–`192.168.77.200` |
| Client gateway/DNS | None unless separately implemented |
| Management | Existing NAT adapter and host SSH port `2028` |

Configure the static address with the guest's existing network manager; keep its management default route intact. Check for competing offers using `sudo tcpdump -ni enp0s8 -vv 'udp port 67 or udp port 68'` while a disposable client requests a lease. An empty capture alone does not prove isolation; verify adapter/cable topology too.

Debian netboot needs a reachable package mirror. With no client gateway, either provide a local verified mirror or explicitly implement guest forwarding/NAT and DNS using the existing firewall framework. A minimal DHCP-only lab has no client Internet access. Do not advertise the NAT adapter's VirtualBox gateway directly to clients.

## 2. Install services and prepare storage

On a Debian/Ubuntu guest, after checking package availability and existing services:

```bash
sudo apt-get update
sudo apt-get install dnsmasq nginx samba smbclient curl ca-certificates \
  xorriso wimtools tcpdump
sudo install -d -m 0755 /srv/pxe/iso /srv/pxe/boot /srv/pxe/tftp /srv/pxe/windows
```

Ensure VirtualBox Guest Additions supplies `vboxsf`. If the existing mount is absent, mount the already-configured `ISOs` share read-only:

```bash
sudo mount -t vboxsf -o ro ISOs /srv/pxe/iso
findmnt -no SOURCE,FSTYPE,OPTIONS /srv/pxe/iso
ls -lh /srv/pxe/iso
```

For persistence, add a single suitable entry to the existing fstab only after validating Guest Additions and mount ordering:

```fstab
ISOs /srv/pxe/iso vboxsf ro,nofail,x-systemd.automount 0 0
```

Check nginx and Samba workers can read the intended files; adjust the guest mount's numeric ownership/mode options where necessary instead of making source media writable. During an authorized restart test, trigger the automount by reading the directory and verify `ro`. Hash media with `sha256sum`; compare against vendor checksums/signatures where available. A self-generated hash records identity only.

## 3. Configure firmware loaders and DHCP

Use official HTTP-capable iPXE binaries; do not assume a distribution's bundled binary includes HTTP. Download to staging, inspect size/type, record source/version/hash, then publish:

```bash
curl -fL --retry 3 https://boot.ipxe.org/undionly.kpxe -o /tmp/pxe-undionly.kpxe
curl -fL --retry 3 https://boot.ipxe.org/snponly.efi -o /tmp/pxe-snponly.efi
file /tmp/pxe-undionly.kpxe /tmp/pxe-snponly.efi
sha256sum /tmp/pxe-undionly.kpxe /tmp/pxe-snponly.efi
sudo install -m 0644 /tmp/pxe-undionly.kpxe /srv/pxe/tftp/undionly.kpxe
sudo install -m 0644 /tmp/pxe-snponly.efi /srv/pxe/tftp/snponly.efi
```

`snponly.efi` here targets x86_64 UEFI. If it fails on a particular NIC, test official `ipxe.efi` as a separate fallback and record the result. IA32 UEFI and ARM are outside the initial firmware target.

Example `/etc/dnsmasq.d/pxe-lab.conf`, after removing conflicting PXE directives from the existing configuration:

```ini
port=0
interface=enp0s8
bind-dynamic
dhcp-range=192.168.77.100,192.168.77.200,255.255.255.0,12h
dhcp-option=3
dhcp-option=6
enable-tftp
tftp-root=/srv/pxe/tftp
log-dhcp

# Architecture option 93: BIOS 0, EFI BC 7, EFI x86-64 9.
dhcp-match=set:bios,option:client-arch,0
dhcp-match=set:efi64,option:client-arch,7
dhcp-match=set:efi64,option:client-arch,9
# iPXE feature option 175, HTTP feature 19: avoid chainloading forever.
dhcp-match=set:ipxe-http,175,19
dhcp-boot=tag:!ipxe-http,tag:bios,undionly.kpxe,,192.168.77.1
dhcp-boot=tag:!ipxe-http,tag:efi64,snponly.efi,,192.168.77.1
dhcp-boot=tag:ipxe-http,http://192.168.77.1/boot/menu.ipxe
```

Inspect all effective dnsmasq configuration for other interfaces/ranges. On a guest also serving unrelated DNS/DHCP, adapt this to a separate scoped instance rather than setting its global `port=0`. Validate before restarting:

```bash
sudo dnsmasq --test
```

Use the existing firewall manager to allow DHCP only on the lab interface, including initial UDP 68→67 broadcasts with source `0.0.0.0` and server replies. Do not require a client-subnet source address for initial DHCP discovery. Restrict TFTP UDP 69 and its related transfer traffic, HTTP TCP 80, and SMB TCP 445 to the lab interface/client subnet. Preserve established management traffic. TFTP uses dynamically selected transfer ports: verify conntrack/helper behavior or explicitly scoped transfer allowances rather than opening only UDP 69 and assuming success. Do not expose SMB or the PXE DHCP service on the management interface.

Reference: [iPXE chainloading](https://ipxe.org/howto/chainloading), [dnsmasq manual](https://thekelleys.org.uk/dnsmasq/docs/dnsmasq-man.html).

## 4. Serve assets and stage the menu

Example nginx server block in `/etc/nginx/sites-available/pxe-lab`; reconcile with existing listeners before enabling it:

```nginx
server {
    listen 192.168.77.1:80;
    server_name _;
    location /boot/ { alias /srv/pxe/boot/; autoindex off; }
    location /iso/  { alias /srv/pxe/iso/;  autoindex off; }
}
```

Validate `sudo nginx -t`. Enable the block with the guest's established nginx layout. Confirm the lab address exists before startup and arrange network readiness for restart persistence. Use stable IDs without spaces for boot directories; URL-encode spaces in ISO URLs. Do not publish extracted Windows source trees over HTTP unless that is an intentional requirement.

Start `/srv/pxe/boot/menu.ipxe` with only a harmless exit choice. Add OS entries after private testing via iPXE's `chain http://192.168.77.1/boot/<id>/boot.ipxe` command:

```ipxe
#!ipxe
set base http://192.168.77.1/boot
:menu
menu PXE installation lab
item exit Return to firmware
# Add tested entries here, e.g.: item ubuntu-server Ubuntu Server 24.04.2
choose --default exit --timeout 10000 selected || goto exit
goto ${selected}
:exit
exit
# For each published ID add a corresponding label:
# :ubuntu-server
# chain ${base}/ubuntu-server/boot.ipxe || goto failed
# goto menu
:failed
echo Boot failed; check DHCP, asset URLs, and installer source.
prompt Press a key to return || goto menu
goto menu
```

Restart services only after their syntax checks pass. Confirm listeners and retrieve menu/assets from a client on the lab network, not just localhost. First verify a disposable BIOS client and UEFI client reach this menu before adding installers.

## 5. Linux media procedures

### Ubuntu Server 24.04.2

Extract matching kernel/initrd without changing the ISO:

```bash
sudo install -d /srv/pxe/boot/ubuntu-server
sudo xorriso -osirrox on -indev /srv/pxe/iso/ubuntu-24.04.2-live-server-amd64.iso \
  -extract /casper/vmlinuz /srv/pxe/boot/ubuntu-server/vmlinuz \
  -extract /casper/initrd /srv/pxe/boot/ubuntu-server/initrd
```

Write `/srv/pxe/boot/ubuntu-server/boot.ipxe`:

```ipxe
#!ipxe
set assets http://192.168.77.1/boot/ubuntu-server
kernel ${assets}/vmlinuz initrd=initrd root=/dev/ram0 ramdisk_size=1500000 ip=dhcp cloud-config-url=/dev/null url=http://192.168.77.1/iso/ubuntu-24.04.2-live-server-amd64.iso ---
initrd ${assets}/initrd initrd
boot
```

No `autoinstall` flag is added. Budget client RAM for the downloaded ISO plus the live installer; begin with 8 GiB for server tests and increase if measured usage requires it. Record ISO retrieval in nginx logs and confirm source detection inside the installer.

Reference: [Ubuntu Server netboot documentation](https://ubuntu.com/server/docs/how-to/installation/how-to-netboot-the-server-installer-on-amd64/).

### Ubuntu Desktop 24.04.4 and 26.04

For each ISO create its own ID and extract its own `/casper/vmlinuz` and `/casper/initrd` as above. Inspect `/boot/grub/grub.cfg`, `/casper/install-sources.yaml`, and the included Casper initramfs/scripts before choosing live-layer arguments. Never mix assets from releases.

Use a private test script following the server structure, with `boot=casper ip=dhcp` and the corresponding local ISO URL. Treat this as a candidate, not a proven desktop stanza. For 26.04, derive any required `layerfs-path` from that image's boot configuration; do not guess a SquashFS filename or copy a 24.04 argument blindly. Start desktop clients with at least 16 GiB RAM when fetching a roughly 6 GiB ISO. If HTTP fetching or layer assembly is unsupported, leave the entry blocked and use vendor-documented network-root preparation as a separate implementation task. Require the desktop installer to detect its source, not merely display a live session.

### Debian 13 DVD and netinst

These are Debian Installer images, not Debian Live images. Do not add Ubuntu `url=` or Debian Live `fetch=` and expect the CD initrd to mount an HTTP ISO.

The default PXE path uses a matching amd64 Debian **netboot** kernel/initrd and a reachable package mirror. Determine the actual release from image metadata (`/.disk/info`), then choose and record a matching installer build; verify its published hashes. Do not assume a file named `13.7.0` exists on the current public mirror.

After verified assets are placed in `/srv/pxe/boot/debian13`, use:

```ipxe
#!ipxe
set assets http://192.168.77.1/boot/debian13
kernel ${assets}/linux initrd=initrd.gz ip=dhcp ---
initrd ${assets}/initrd.gz initrd.gz
boot
```

Label this honestly as `Debian 13 network installer (mirror required)`; it does not consume the local DVD/netinst ISO. For local-media installation, use a matching `hd-media` kernel/initrd with the ISO already present on an unchanged client partition or separate removable media, or build a verified local package mirror from the media. Retain a separate compatibility row for both original ISOs and mark pure HTTP ISO consumption blocked until a media-access method is implemented and tested. Do not silently substitute a mirror-based result for ISO-based acceptance.

References: [Debian network boot preparation](https://www.debian.org/releases/stable/amd64/ch04s05.en.html), [Debian hd-media versus netboot](https://www.debian.org/releases/stable/amd64/ch04s04.en.html).

## 6. Windows media, WinPE, and installation source

### Windows 10 22H2, older Windows 10, and Windows 7 x64

Prepare each image independently with IDs `win10-22h2`, `win10-2019`, and `win7-x64`. Mount the ISO read-only so UDF media is handled correctly; an ISO9660-only extraction can miss Windows files. Example for 22H2:

```bash
sudo install -d /mnt/pxe-winiso /srv/pxe/windows/win10-22h2 /srv/pxe/boot/win10-22h2
sudo mount -o loop,ro /srv/pxe/iso/Win10_22H2_English_x64v1.iso /mnt/pxe-winiso
sudo cp -a /mnt/pxe-winiso/. /srv/pxe/windows/win10-22h2/
sudo umount /mnt/pxe-winiso
```

Inspect extracted paths and actual filename case. Confirm `setup.exe`, boot files, `sources/boot.wim`, and either `install.wim`, `install.esd`, or all split `install*.swm` parts. Use `wimlib-imagex info` on the boot image to determine architecture and setup image index. The older Windows 10 filename does not establish its architecture. Windows 7 BIOS is the baseline; x64 UEFI is conditional on its media, firmware, drivers, and successful testing.

Copy `boot/BCD`, `boot/boot.sdi`, and `sources/boot.wim` into that image's boot directory using the observed path case. Download an official wimboot release from [ipxe/wimboot](https://github.com/ipxe/wimboot/releases), record its version/hash, and place the binary at `/srv/pxe/boot/wimboot`. Use that release's documented image-index selection if the desired Setup image is not the default; never assume image index 1 launches Setup for every ISO.

Example Windows script, after copying the assets under these canonical names:

```ipxe
#!ipxe
set assets http://192.168.77.1/boot/win10-22h2
kernel http://192.168.77.1/boot/wimboot
initrd ${assets}/BCD BCD
initrd ${assets}/boot.sdi boot.sdi
initrd ${assets}/boot.wim boot.wim
boot
```

Booting WinPE is only the first stage. Provide the complete installation source on a read-only Samba share. Add a dedicated account interactively (`smbpasswd -a pxeinstall`) after creating the corresponding guest OS account without shell login. Do not store its password in an iPXE script or startup batch file.

Example share in the existing Samba configuration:

```ini
[installers]
    path = /srv/pxe/windows
    read only = yes
    guest ok = no
    valid users = pxeinstall
    browseable = no
```

Set directory ownership/read permissions so this account can read extracted media; do not recursively rewrite permissions on the source ISO share. Scope TCP 445 through the lab firewall, and inspect existing global Samba protocol/interface settings. Validate `sudo testparm -s`, then test `smbclient //192.168.77.1/installers -U pxeinstall -c 'ls'` with an interactive password prompt.

In **WinPE**, open a command prompt if necessary and run:

```bat
wpeinit
ipconfig /all
net use Z: \\192.168.77.1\installers /user:pxeinstall *
dir Z:\win10-22h2\sources
Z:\win10-22h2\setup.exe
```

Use the corresponding folder for other Windows versions. If the ISO boot WIM auto-launches an unsuitable Setup path, use a compatible ADK-built WinPE and launch the source manually, or prepare a documented working copy with a shell startup override. Never modify the original ISO. Inject missing signed NIC/storage drivers into a copied WIM using compatible Windows DISM/ADK tooling and retest. WinPE network access does not prove Setup sees the installation disk.

Keep SMB2 or later for the standard share. If legacy media cannot negotiate it, use compatible technician WinPE where possible or record the limitation; do not globally enable SMB1 to rescue one image. For an x86 boot image, do not claim x86_64 UEFI support.

Reference: [iPXE project: network-booting WinPE and launching Windows Setup](https://ipxe.org/howto/winpe). This section follows that workflow; architecture/index selection and old-image compatibility must be checked against the actual media.

### Windows XP SP3 x86 and Longhorn build 3683

Inventory and inspect these images separately. XP media uses legacy text-mode setup and is not a normal `boot.wim`/wimboot installer; the current Windows script is not applicable. Longhorn is a pre-release build whose actual setup layout and driver needs must be examined rather than inferred from its filename.

Initial status: `blocked for standard PXE deployment`. BIOS-only evaluation is permitted on disposable clients. A proven RIS-style XP workflow or a build-specific Longhorn workflow requires separate research, version-compatible tooling, and source-access validation before publication. Leave both out of the working PXE menu. Attaching the ISO to a disposable VM may establish media bootability, but does not establish PXE compatibility. No modern x64 UEFI or Secure Boot support is claimed for these images.

## 7. Other media and compatibility inventory

Inventory observed on the host on 2026-10-02. All current guest boot outcomes are **unverified**. Update status and actual architecture after inspection; a procedure below is not a success claim.

| Source filename | Method or role | Firmware target / current limitation |
| --- | --- | --- |
| `ubuntu-24.04.2-live-server-amd64.iso` | Matching Casper assets + local HTTP ISO | BIOS/x64 UEFI; historical BIOS result only |
| `ubuntu-24.04.4-desktop-amd64.iso` | Matching Casper assets; desktop-specific private test | BIOS/x64 UEFI candidate |
| `ubuntu-26.04-desktop-amd64.iso` | Matching Casper assets and inspected layer settings | BIOS/x64 UEFI candidate |
| `debian-13.7.0-amd64-DVD-1.iso` | Local-media hd-media path or local mirror; netboot is separate | BIOS/x64 UEFI; direct HTTP ISO path blocked |
| `debian-13.7.0-amd64-netinst.iso` | Same distinction; matching network installer may use a mirror | BIOS/x64 UEFI; direct HTTP ISO path blocked |
| `Win10_22H2_English_x64v1.iso` | WinPE/wimboot + full SMB source | BIOS/x64 UEFI candidate |
| `Windows10Pro18Jan19.iso` | Inspect architecture; matching WinPE + SMB source | BIOS; x64 UEFI only for suitable x64 media |
| `en_windows_7_professional_x64_dvd.iso` | Compatible WinPE/wimboot + SMB source | BIOS baseline; x64 UEFI conditional |
| `en_windows_xp_professional_with_service_pack_3_x86_cd_vl_x14-73974.iso` | Requires a separate legacy deployment method | BIOS-only research; blocked |
| `Windows Longhorn build 3683.iso` | Inspect build-specific setup layout | Legacy research; blocked |
| `FreeBSD-15.0-RELEASE-amd64-dvd1.iso` | Requires FreeBSD loader plus compatible network-root/install source | Blocked; ISO is not a Linux kernel/initrd |
| `OPNsense-26.1.6-dvd-amd64.iso` | Requires appliance-specific proven network installer/source method | Blocked; do not assume generic FreeBSD procedure works |
| `virtio-win-0.1.271.iso` | Windows NIC/storage driver source | Supporting media, no installer menu entry |
| `USB_Bizon.img` | Inspect partition table and provenance | Disk image; no generic PXE installer entry |
| `export-ami-20890c2c2e21f0a4t.vmdk` | Virtual disk artifact | Not ISO installation media |

For FreeBSD consult the [FreeBSD diskless networking handbook](https://docs.freebsd.org/en/books/handbook/advanced-networking/#network-diskless) to design loader/network-root dependencies. For OPNsense start with the [vendor installation documentation](https://docs.opnsense.org/manual/install.html). These are research starting points, not assertions that the exact DVD images support direct network boot. Do not use BIOS MEMDISK ISO tricks as a general solution for UEFI or large installer images.

## 8. Validate, diagnose, and restore

Before activation run `dnsmasq --test`, `nginx -t`, and `testparm -s`. Enable/restart only the services introduced or changed after inspecting existing service ownership. Record `systemctl is-active` and `systemctl is-enabled`; these prove service state, not successful provisioning.

For each image/firmware pair, capture a concise result record:

| Field | Evidence |
| --- | --- |
| Media identity | SHA-256, actual metadata, asset origin/version |
| Client | VM or physical model, BIOS/UEFI, Secure Boot state, RAM, NIC/storage |
| Network | Lease, server interface, DHCP boot filename, isolation check |
| Transfers | TFTP loader and nginx requests for script/kernel/initrd/WIM/ISO |
| Installer/source | Installer stage, source accessible, test disk visible |
| Outcome | Prepared/menu reached/installer reached/source verified/blocked; exact failure |

Use empty disposable disks; stop at the installer's disk-selection/partitioning screen. Require BIOS and x64 UEFI for each image that claims both. Record firmware restrictions instead of forcing an invalid matrix. Verify original media remains read-only and no DHCP offers escape the lab. Test mount/service persistence only in an authorized maintenance window; otherwise report it pending.

Useful guest diagnostics:

```bash
sudo journalctl -u dnsmasq -u nginx -u smbd --since '15 minutes ago' --no-pager
sudo tail -n 100 /var/log/nginx/access.log /var/log/nginx/error.log
sudo tcpdump -ni enp0s8 -vv 'udp port 67 or udp port 68 or udp port 69'
curl -fI http://192.168.77.1/boot/menu.ipxe
findmnt /srv/pxe/iso
```

The packet filter above sees DHCP and initial TFTP requests, not every negotiated TFTP transfer port. Expand a capture to the test client's address when diagnosing stalls.

| Symptom | Check next |
| --- | --- |
| No DHCP lease | Adapter/cable isolation, guest interface/address, service bindings, firewall, competing offers |
| Loader repeats | iPXE HTTP feature detection, effective DHCP directives, actual option 67 |
| BIOS works but UEFI stalls | Option 93, x64 loader, NIC driver; separately test `ipxe.efi` |
| TFTP starts then hangs | Transfer-port firewall handling, capture client traffic |
| HTTP 404/403 | nginx alias, URL encoding/case, worker access to vboxsf |
| Ubuntu cannot find live media | Matching kernel/initrd/ISO, release-specific layer flags, full ISO transfer, RAM |
| Debian asks for a CD or mirror fails | Wrong CD initrd versus netboot, unreachable mirror, missing local media/root |
| WinPE boots but no source or disk | `wpeinit`, NIC/storage drivers, WIM index, SMB authentication and full source tree |

Rollback: if DHCP isolation fails, stop the new DHCP service immediately. Restore backed-up files and original service enablement, undo only the firewall rules added for this task, validate restored configurations, and verify management access. Restore adapter settings in a suitable maintenance window. Keep original ISOs and pre-existing VM disks; identify newly generated assets explicitly before removal. Finish with changes, validation, remaining blockers, and rollback location.
