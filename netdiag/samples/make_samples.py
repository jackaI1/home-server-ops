"""Write the stored sample captures used by the unit tests.

The captures are built with Scapy so they are the same on every run. Each one
has a known answer, which the tests check:

* slow-transfer.pcap: one backup flow that sends 3 segments twice and moves
  about 11 kbit/s, one fast flow that moves about 2 Mbit/s with no
  retransmissions, and one DNS lookup that takes 450 ms.
* clean-transfer.pcap: two healthy flows and DNS answers in 5 to 15 ms.

Every field that Scapy would otherwise randomise (IP identification, DNS and
TCP sequence numbers) is set explicitly, so rerunning the script gives the same
bytes.

Run it from the repository root only when the samples need to change:

    python -m pip install scapy==2.6.1
    python netdiag/samples/make_samples.py
"""

from __future__ import annotations

from pathlib import Path

from scapy.all import DNS, DNSQR, DNSRR, IP, TCP, UDP, Ether, Raw, wrpcap

HERE = Path(__file__).resolve().parent
CLIENT = "192.168.1.20"
SERVER = "192.168.1.10"
DNS_SERVER = "192.168.1.1"
BASE_TIME = 1_767_000_000.0  # fixed epoch so the files never change


MACS = {CLIENT: "02:00:00:00:00:20", SERVER: "02:00:00:00:00:10", DNS_SERVER: "02:00:00:00:00:01"}


def _eth(src, dst):
    # Fixed MAC addresses keep Scapy from trying to look them up on this machine.
    return Ether(src=MACS[src], dst=MACS[dst])


def _pkt(t, src, sport, dst, dport, seq, ack, flags, payload=b""):
    return (
        t,
        _eth(src, dst) / IP(src=src, dst=dst, id=1)
        / TCP(sport=sport, dport=dport, seq=seq, ack=ack, flags=flags) / Raw(load=payload),
    )


def tcp_flow(start, sport, dport, segments, interval, size, retrans_at=(), server_acks=True):
    """Return packets for one TCP connection that sends `segments` data segments.

    `retrans_at` lists segment indexes that the client sends a second time
    0.4 s after the first copy, which Wireshark reports as retransmissions.
    """
    out = []
    isn = 1000 + sport
    out.append(_pkt(start, CLIENT, sport, SERVER, dport, isn, 0, "S"))
    out.append(_pkt(start + 0.001, SERVER, dport, CLIENT, sport, 5000, isn + 1, "SA"))
    out.append(_pkt(start + 0.002, CLIENT, sport, SERVER, dport, isn + 1, 5001, "A"))
    seq = isn + 1
    t = start + 0.01
    for i in range(segments):
        payload = bytes([65 + i % 26]) * size
        out.append(_pkt(t, CLIENT, sport, SERVER, dport, seq, 5001, "PA", payload))
        if i in retrans_at:
            out.append(_pkt(t + 0.4, CLIENT, sport, SERVER, dport, seq, 5001, "PA", payload))
        if server_acks and i % 2 == 1:
            out.append(_pkt(t + 0.003, SERVER, dport, CLIENT, sport, 5001, seq + size, "A"))
        seq += size
        t += interval
    out.append(_pkt(t, CLIENT, sport, SERVER, dport, seq, 5001, "FA"))
    return out


def dns_lookup(t, txid, name, delay):
    query = _eth(CLIENT, DNS_SERVER) / IP(src=CLIENT, dst=DNS_SERVER, id=2) / UDP(sport=40000 + txid, dport=53) / DNS(
        id=txid, rd=1, qd=DNSQR(qname=name)
    )
    response = _eth(DNS_SERVER, CLIENT) / IP(src=DNS_SERVER, dst=CLIENT, id=3) / UDP(sport=53, dport=40000 + txid) / DNS(
        id=txid, qr=1, rd=1, ra=1, qd=DNSQR(qname=name), an=DNSRR(rrname=name, ttl=300, rdata="192.168.1.10")
    )
    return [(t, query), (t + delay, response)]


def _write(path: Path, items):
    items.sort(key=lambda item: item[0])
    packets = []
    for t, pkt in items:
        pkt.time = t
        packets.append(pkt)
    wrpcap(str(path), packets)


def slow_transfer() -> list:
    items = []
    # Backup over SSH: 30 segments of 1000 bytes, one every 0.7 s, three resent.
    items += tcp_flow(BASE_TIME + 0.0, 50001, 22, 30, 0.7, 1000, retrans_at=(4, 11, 20))
    # Sync over HTTPS: 200 segments of 1000 bytes, one every 4 ms, no loss.
    items += tcp_flow(BASE_TIME + 1.0, 50002, 8443, 200, 0.004, 1000)
    items += dns_lookup(BASE_TIME + 0.5, 101, "backup.home.arpa", 0.45)
    items += dns_lookup(BASE_TIME + 1.2, 102, "sync.home.arpa", 0.01)
    return items


def clean_transfer() -> list:
    items = []
    items += tcp_flow(BASE_TIME + 0.0, 51001, 8443, 120, 0.004, 1000)
    items += tcp_flow(BASE_TIME + 0.5, 51002, 22, 40, 0.01, 200)
    items += dns_lookup(BASE_TIME + 0.1, 201, "sync.home.arpa", 0.005)
    items += dns_lookup(BASE_TIME + 0.6, 202, "backup.home.arpa", 0.015)
    return items


def main() -> None:
    _write(HERE / "slow-transfer.pcap", slow_transfer())
    _write(HERE / "clean-transfer.pcap", clean_transfer())
    print("wrote", HERE / "slow-transfer.pcap", "and", HERE / "clean-transfer.pcap")


if __name__ == "__main__":
    main()
