# Deploy a new PXE VM with Ansible

This playbook builds a **new, dedicated** Ubuntu 24.04 LTS Server or Debian 12+ systemd VM. The role also accepts Ubuntu 22.04+. It does not support arbitrary distributions. It prepares Linux and Windows installer candidates using dnsmasq, HTTP-capable iPXE, nginx, read-only NFS and SMB, and wimboot. The existing VirtualBox `pxe` VM is historical source material; this inventory does not target it, and no new deployment has been performed.

Read the project [agent instructions](../agent.md) and [PXE runbook](../skills.md) for media compatibility and client acceptance requirements. Server configuration checks do not establish that an installer works.

## 1. Prepare the new VM and installation media

Give the VM two NICs and enough disk space for its OS, boot assets and any locally copied ISOs. Keep NIC 1 on NAT or your management network for SSH and package/mirror access. Put NIC 2 and disposable client VMs on a dedicated VirtualBox internal network, for example `pxe-new-lab`. Discover the actual Linux names with `ip -br address`; defaults are management `enp0s3` and clients `enp0s8`.

The running old PXE VM must not offer DHCP on this new client network. Use a different internal network from the old VM, or disconnect the old server's client adapter through a separately authorized maintenance action. A physical deployment requires a dedicated switch without a LAN uplink or competing DHCP. Set the inventory isolation flag only after verifying this topology.

Default client addressing is server `192.168.77.1/24`, leases `.100`–`.200`. The role provides DNS and IPv4 forwarding/NAT through the management NIC by default so the Debian network installer can reach its mirror. Choose a different subnet if it conflicts with management routes. Ubuntu defaults to a separate netplan file for the client NIC; existing management netplan is retained. Debian defaults to `pxe_manage_network: false`: configure a persistent `192.168.77.1/24` address on the secondary NIC before running the playbook. Ubuntu can also use externally configured networking with this setting.

Choose one media-source mode in the inventory:

| Mode | Preparation | Inventory settings |
| --- | --- | --- |
| `directory` | Copy your selected ISOs into `/srv/pxe/iso` on the new VM first. Source images are loop-mounted read-only; the source directory itself is not automatically mounted read-only. | `pxe_iso_mode: directory` |
| `vboxsf` | Add the host ISO folder, such as `/home/raheel/Desktop/ISO`, as a read-only VirtualBox shared folder named `ISOs`. Install and verify working Guest Additions and the `vboxsf` kernel module separately. | `pxe_iso_mode: vboxsf`, `pxe_iso_source: ISOs` |
| `nfs` | Provide a reachable NFS export containing the ISOs; make it read-only on the source server. | `pxe_iso_mode: nfs`, `pxe_iso_source: "192.0.2.10:/exports/isos"` |

The role mounts shared media read-only and persists source/ISO mounts. It does not provision VirtualBox Guest Additions or configure the source NFS server. A shared folder name is not a host filesystem path. NFS used to obtain the ISO collection is separate from this server's NFS exports used by Ubuntu clients.

`pxe_media` is the **complete selected installer list**, not an additive override. Defaults select six particular Ubuntu/Windows ISO filenames. Remove entries for media you do not have, or replace the list with your actual filenames. Missing selected files intentionally fail deployment rather than publish broken entries. Example under your inventory host:

```yaml
pxe_media:
  - id: ubuntu24-server
    label: Ubuntu 24.04 Server
    iso: ubuntu-24.04.2-live-server-amd64.iso
    kind: ubuntu
    validated: false
    extra_args: ''
  - id: win10-22h2
    label: Windows 10 22H2 x64
    iso: Win10_22H2_English_x64v1.iso
    kind: windows
    validated: false
```

Use Ubuntu live images with matching Casper kernel/initrd and Windows media containing suitable WinPE boot files. ISO filename labels do not establish compatibility or authenticity. The separate Debian 13 network entry uses included netboot assets and a package mirror; it does not need a Debian ISO. Set `pxe_debian_enabled: false` to omit it.

## 2. Configure the inventory and controller

Install `ansible-core` on the controller using your normal package or isolated Python environment, then run from this `ansible` directory:

```bash
ansible-galaxy collection install -r requirements.yml
cp inventory/hosts.example.yml inventory/hosts.yml
```

The only additional collection is `ansible.posix`. Edit `inventory/hosts.yml` with the **new** VM's SSH host, port and user. For VirtualBox NAT port forwarding, use the host address and its forwarded port; do not reuse the old server's `2028` forwarding rule. Example:

```yaml
all:
  children:
    pxe_servers:
      hosts:
        pxe_new:
          ansible_host: 127.0.0.1
          ansible_port: 2029
          ansible_user: your_new_vm_user
          pxe_lab_isolated: true
          pxe_dedicated_vm: true
          pxe_interface: enp0s8
          pxe_uplink: enp0s3
          pxe_iso_mode: vboxsf
          pxe_iso_source: ISOs
```

The two flags acknowledge verified isolation and a dedicated VM. This role takes ownership of the main dnsmasq, nginx and Samba configurations; use a fresh VM rather than one hosting unrelated services. SSH host-key checking remains enabled. Establish and verify the SSH connection first; do not disable checking to bypass a mismatched host key.

Authenticated SMB is the default. When Windows media is selected, enter a password of at least 12 characters through a transient environment variable:

```bash
read -r -s -p 'PXE SMB password: ' PXE_SMB_PASSWORD
printf '\n'
export PXE_SMB_PASSWORD
```

The role sends the password to `smbpasswd` on standard input under `no_log`. Plaintext credentials are not written to inventory, HTTP boot scripts or recovery files; Samba necessarily stores its account verifier on the target. WinPE prompts for the share password interactively. A Vault-protected `pxe_smb_password` is also supported. Avoid passing passwords with `-e` or putting them in shell history. Existing SMB passwords change only when `pxe_smb_rotate_password: true`; supply the existing password when rerunning normally. Explicit `pxe_smb_auth: guest` reproduces the old isolated lab's unauthenticated share and is not the default.

## Focused update of the running PXE server

The separate `update-running.yml` playbook adds local-disk boot and central logging without replacing the current installer menu, network, NFS, or Samba configuration. Use `inventory/existing.example.yml` as a template for an untracked `inventory/existing.yml`; verify its SSH forwarding, address, and interface against the live VM first. It prompts interactively for SSH and privilege escalation credentials. Ansible backs up the original `menu.ipxe` when publishing a change.

```bash
cp inventory/existing.example.yml inventory/existing.yml
ansible-playbook -i inventory/existing.yml update-running.yml --syntax-check
ansible-playbook -i inventory/existing.yml update-running.yml --check --diff --ask-pass --ask-become-pass
ansible-playbook -i inventory/existing.yml update-running.yml --ask-pass --ask-become-pass
```

A client that blanks and restarts after Ubuntu installation still needs a separate boot diagnosis: confirm firmware mode and the installed disk's EFI/GRUB state before claiming repair. The menu change alone cannot prove the client OS boots.

## 3. Check and deploy

```bash
ansible-playbook -i inventory/hosts.yml site.yml --syntax-check
ansible -i inventory/hosts.yml pxe_servers -m ansible.builtin.ping
ansible-playbook -i inventory/hosts.yml site.yml --check --diff --ask-become-pass
ansible-playbook -i inventory/hosts.yml site.yml --ask-become-pass
unset PXE_SMB_PASSWORD
```

Add `--ask-pass` to the SSH commands if the new VM uses password authentication rather than a key. The check run predicts changes; on a fresh VM, skipped mounts, package installation and asset preparation mean it cannot verify the final system. Missing prerequisites during a fresh check run require a real deployment to resolve. Credential tasks use `no_log`, including during `--diff`; keep inventory and debugging output free of secrets.

The role validates daemon configurations, applies its own scoped nftables tables without flushing unrelated tables, and creates persistence units for media and firewall setup. It verifies HTTP menu retrieval, read-only selected media mounts, and a synthetic central logging event. These checks do not boot a client. Existing firewall rules can still block traffic despite the PXE tables; inspect conflicts before adding broader rules.

The default UEFI binary downloads at deployment time from `https://boot.ipxe.org/snponly.efi`. Set `pxe_uefi_url` and `pxe_uefi_checksum: "sha256:<digest>"` to pin a reviewed artifact. `pxe_uefi_loader: ipxe.efi` is supported with a matching URL as an explicit NIC compatibility alternative. BIOS `undionly.kpxe`, wimboot and Debian 13 kernel/initrd are copied from the included recovery assets. [Their manifest](files/recovered/manifest.json) records sizes, SHA-256 values and recovery provenance. These hashes identify recovered files; they do not substitute for vendor authenticity checks. `scripts/import_recovery_assets.py` imports only four allowlisted binaries from a recovery archive, excluding service configurations, credentials and ISOs.

## 4. Central logs and client acceptance

Both lab and production menus include **Boot from local hard disk**. BIOS boots drive `0x80`; UEFI searches disks for the configured `pxe_local_efi_paths` in order (Windows, Ubuntu, Debian, then the standard fallback). Override this list for another installed OS or a preferred dual-boot order. This uses the [iPXE project's local-disk `sanboot` command](https://ipxe.org/cmd/sanboot) and performs no disk writes. If there is no matching bootloader or booting fails, the client returns to the PXE menu with an error. `Return to firmware` remains a separate choice, and the menu timeout selects local disk by default. Set `pxe_menu_default: exit` to make the timeout return to firmware. Test local boot with an already-installed disposable BIOS and UEFI client; an empty test disk should return to the menu. The request for `/boot/localboot.ipxe` records the selection in nginx's central log, but cannot prove that the client's OS booted.

All configured PXE daemon logging is collected in **`/var/log/pxe.log`**: DHCP/TFTP/DNS, nginx access/error, Samba syslog, NFS daemons, PXE helper units, and relevant systemd/kernel messages. Journald forwards service output to rsyslog. The collector retains normal system logging as well. Logs rotate daily with 14 archives, compression, and `0640 syslog:adm` permissions so Ubuntu's unprivileged rsyslog writer can append after creation and rotation. The role ensures the `syslog` system account exists. Service log levels and the collector's selectors determine emitted records; this is not full client kernel tracing or a packet capture.

On the new server:

```bash
sudo tail -f /var/log/pxe.log
sudo systemctl --no-pager status dnsmasq nginx smbd nfs-server pxe-media pxe-firewall rsyslog
sudo findmnt /srv/pxe/iso
sudo cat /var/lib/pxe/inventory.json
```

The default menu is `pxe_menu_mode: lab`; unvalidated candidates are visibly marked `[TEST]`. Its timeout attempts local-disk boot. Test disposable BIOS and x86_64 UEFI clients separately with Secure Boot disabled. For each candidate, verify a DHCP lease, correct TFTP loader, HTTP menu/assets and installer startup. Ubuntu must discover its NFS installation source and reach partitioning; Debian must reach its configured mirror; Windows must initialize networking, authenticate to the SMB source, detect the disposable disk and reach disk selection. Stop before committing disk changes. Then perform an authorized server restart and repeat mount/service/client checks to prove persistence.

Historical recovery configuration had incomplete paths. This deployment uses read-only NFS for Ubuntu Casper, a Debian network installer matched to its mirror suite, and a corrected WinPE shell launcher with runtime SMB authentication. Those corrections still require testing on each new server. Debian DVD as an unsigned local mirror, XP, Longhorn, FreeBSD and OPNsense remain unsupported menu candidates; VirtIO ISO is driver media and IMG/VMDK files are disk images. Do not infer their bootability from inventory presence.

After recording successful client results on the new server, set the tested `pxe_media` entries' `validated: true` and `pxe_debian_validated: true` only for Debian if tested. Switch `pxe_menu_mode: production` and rerun. Production exposes only flagged entries. These booleans record operator evidence; Ansible cannot certify them or express separate BIOS/UEFI results. Keep detailed firmware-specific results externally and leave an entry hidden until its intended client modes pass.

## 5. Backup and rollback

Before deployment, take an authorized snapshot of the **new** VM and record its NIC topology, management address and original service states. After input checks and before installation/configuration changes, the role creates `/var/backups/pxe-before-ansible.tar.gz` once, containing relevant existing `/etc` paths, protected as root-only `0600`. It is a configuration baseline, not a VM or full service-state backup. Templates also back up overwritten main daemon configurations and selected PXE drop-ins on the target. Retain these backups with the original source ISOs. Mount, package, service, account, sysctl and firewall changes are not undone merely by restoring a daemon configuration.

If DHCP is observed outside the isolated lab, stop dnsmasq on the new VM immediately and disconnect its lab NIC. For complete rollback on a fresh VM, restore the predeployment snapshot in an authorized maintenance window. For selective rollback, stop the PXE services, inspect the baseline archive with `sudo tar -tzf /var/backups/pxe-before-ansible.tar.gz`, and restore the required saved configurations while preserving management networking. Remove newly added PXE files separately: restoring an archive does not delete them. Remove only the role's PXE units/netplan/sysctl/mount entries and its own nftables tables, then verify management SSH and original service states. Never flush the entire firewall or operate on the running old PXE VM as part of this deployment.
