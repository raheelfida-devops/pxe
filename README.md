# PXE deployment

Ansible for dedicated Ubuntu/Debian PXE servers serving Linux and Windows
installation media, with local hard-disk boot and central `/var/log/pxe.log` logging.

- [Deployment instructions](ansible/README.md)
- [Agent guidance](agent.md)
- [Manual procedures and media compatibility](skills.md)
- [New server playbook](ansible/site.yml)
- [Focused running-server update](ansible/update-running.yml)

For a new VM, start with the [password-based Ansible example](ansible/README.md#example-run-from-a-controller-with-an-ssh-username-and-password). It shows a sample `pxeadmin` SSH user, where to enter SSH/sudo passwords, inventory setup, and the `ansible-playbook` commands. Windows share credentials use a separate prompt.

The focused update preserves existing installer menu entries and adds local-disk
boot as the timeout default. It is prepared locally; no running server update or
Ubuntu client repair has been verified from this workspace.

Read the deployment instructions before choosing an inventory. Do not run the
fresh-server role against an existing installation to make a menu-only change.
BIOS and UEFI installation/local boot need separate client testing. ISO files and
VM disks are not included; the small recovery asset bundle records its provenance
and hashes in `ansible/files/recovered/manifest.json`.
