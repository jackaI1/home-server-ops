# Runbook: why is a backup or sync slow?

Use this when a backup or LifeOS sync takes much longer than usual. The goal is to
find out which part is slow (the network path, DNS, or one connection) before
changing anything. Each step says what to look at and what the result means.

Run commands on the home server unless a step says otherwise. Captures contain
the addresses of every machine you talked to, so keep them out of Git.

## 1. Write down the symptom

Note the job, the start and end times, the size of the transfer and how long it
should take. Check the job's own log first. If it reports a specific error, fix
that first; this runbook is for transfers that finish but are slow.

## 2. Check the interface for errors

```sh
ip -s link show eth0
ethtool eth0 | grep -E 'Speed|Duplex'
```

- Growing `errors`, `dropped` or `overrun` counters mean the cable, port or
  driver is losing frames. Replace the cable or try another switch port.
- `Duplex: Half` on a gigabit link means a duplex mismatch. Set both ends to auto.

## 3. Capture the job

```sh
sudo python3 -m netdiag run --iface eth0 --out ~/captures/backup-$(date +%F) \
  --filter "tcp or udp port 53" -- /usr/local/bin/backup.sh
```

`run` records with tcpdump while the job runs, then writes `report.md` into the
same folder. Use `--iface` for the interface that talks to the NAS or the cloud
target. Add `--dns-ms`, `--slow-kbps` or `--retrans-limit` to change the limits.
A capture of one job is usually a few megabytes. Delete it when you are done.

If you only want to analyse a capture you already have:

```sh
python3 -m netdiag analyze ~/captures/backup-2026-11-10/capture.pcap --report report.md
```

## 4. Read the findings

| Finding in the report | What it usually means | Next step |
| --- | --- | --- |
| Data segments were sent again (above 1%) | Packets are being lost or dropped on the path | Go to step 5 |
| A flow resent a large share of its segments | One connection is losing most of its packets | Check the cable and switch port of the device at the other end |
| DNS answers took longer than 200 ms | The resolver is slow, or the lookup goes to a far server | Go to step 6 |
| A flow averaged less than 1 Mbit/s with no resends | The window is small, or one side is busy (CPU, disk) | Go to step 7 |
| No findings | The network was not the bottleneck during the job | Check the disk and the job's own settings |

## 5. Retransmissions

Open `capture.pcap` in Wireshark (or `tshark`) and filter with
`tcp.analysis.retransmission`. If the retransmissions come in bursts, check
Wi-Fi signal and link speed. If they are spread evenly, check the cable and the
switch port (step 2).

## 6. Slow DNS

```sh
dig +stats backup.example.internal | grep 'Query time'
```

Run it a few times. A slow answer on the local resolver usually means the
upstream server is slow. Compare with the router's address to find which one.

## 7. Slow flow with no resends

Look at the advertised window in Wireshark (`tcp.window_size`). A window that
stays small means the receiver is not reading fast enough. Check disk
utilisation with `iostat -x 1 5` during the job, and CPU with `top`. If both are
idle, check the route with `mtr --report <target>`.

## 8. Compare and record

Capture the same job on a quiet night. Two folders that differ in one finding
point to the cause faster than a single capture. Write the cause and the fix in
your notes, and delete the captures once you have them.

## Check the drill still works

On a Linux machine with sudo, the fault drill injects 5% loss and checks that the
report catches it:

```sh
bash netdiag/drill/netem_drill.sh
```

It prints `PASS` when the report flags the loss and the baseline run is clean.
It runs in CI on every pull request that changes `netdiag/`.
