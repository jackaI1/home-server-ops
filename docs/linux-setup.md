# Linux setup with Ansible

This sets up the home server from a clean Ubuntu 24.04 install. Ansible runs the
steps from a laptop over SSH, so the same playbook can be run again after a
reinstall. The playbook lives in `ansible/`.

## What it does

- **base**: installs the packages I use, turns on automatic security updates and
  sets larger TCP buffers, so big backups over the LAN are not held back.
- **ssh**: turns off password logins and root logins, and allows only the admin
  account. sshd checks the new file before it is put in place, so a typo cannot
  lock you out.
- **netdiag**: installs `tcpdump` and `tshark` (the command-line half of
  Wireshark), copies the `netdiag` tools to `/opt/netdiag` and makes a `netdiag`
  command. Captures are kept in a folder that only root can read, because they
  show which machines talk to which.

## Before you run it

1. Install Ubuntu Server 24.04 and create an admin account with your SSH key.
2. Check that you can log in with the key, because the playbook turns off
   password logins.
3. Copy the inventory example and put in your server's address:

   ```sh
   cd ansible
   cp inventory/hosts.example.yml inventory/hosts.yml
   ```

## Run it

```sh
python3 -m pip install -r requirements-dev.txt
ansible-playbook -i inventory/hosts.yml site.yml --check --diff   # show the changes first
ansible-playbook -i inventory/hosts.yml site.yml
```

Run only one part with `--tags ssh`, `--tags netdiag` or `--tags base`.

## How it is tested

`molecule test` in `ansible/` starts a clean Ubuntu 24.04 container, runs the
roles, runs them a second time to check nothing changes (idempotence), then
checks the result. The checks include a clean stored capture passing
`netdiag analyze` and the slow stored capture being flagged. GitHub Actions
runs this on every pull request that changes `ansible/` or `netdiag/`.

Ansible cannot manage systemd or sshd inside a container, so the restart tasks
are skipped there. Everything else runs as it does on the server.
