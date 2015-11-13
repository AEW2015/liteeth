from copy import deepcopy

from liteeth.common import *


def split_bytes(v, n, endianness="big"):
    r = []
    r_bytes = v.to_bytes(n, byteorder=endianness)
    for byte in r_bytes:
        r.append(int(byte))
    return r


def merge_bytes(b, endianness="big"):
    return int.from_bytes(bytes(b), endianness)


def get_field_data(field, datas):
    v = merge_bytes(datas[field.byte:field.byte+math.ceil(field.width/8)])
    return (v >> field.offset) & (2**field.width-1)


class Packet(list):
    def __init__(self, init=[]):
        self.ongoing = False
        self.done = False
        for data in init:
            self.append(data)


class EtherboneWrite:
    def __init__(self, data):
        self.data = data

    def __repr__(self):
        return "WR32 0x{:08x}".format(self.data)


class EtherboneRead:
    def __init__(self, addr):
        self.addr = addr

    def __repr__(self):
        return "RD32 @ 0x{:08x}".format(self.addr)


class EtherboneWrites(Packet):
    def __init__(self, init=[], base_addr=0, datas=[]):
        Packet.__init__(self, init)
        self.base_addr = base_addr
        self.writes = []
        self.encoded = init != []
        for data in datas:
            self.add(EtherboneWrite(data))

    def add(self, write):
        self.writes.append(write)

    def get_datas(self):
        datas = []
        for write in self.writes:
            datas.append(write.data)
        return datas

    def encode(self):
        if self.encoded:
            raise ValueError
        for byte in split_bytes(self.base_addr, 4):
            self.append(byte)
        for write in self.writes:
            for byte in split_bytes(write.data, 4):
                self.append(byte)
        self.encoded = True

    def decode(self):
        if not self.encoded:
            raise ValueError
        base_addr = []
        for i in range(4):
            base_addr.append(self.pop(0))
        self.base_addr = merge_bytes(base_addr)
        self.writes = []
        while len(self) != 0:
            write = []
            for i in range(4):
                write.append(self.pop(0))
            self.writes.append(EtherboneWrite(merge_bytes(write)))
        self.encoded = False

    def __repr__(self):
        r = "Writes\n"
        r += "--------\n"
        r += "BaseAddr @ 0x{:08x}\n".format(self.base_addr)
        for write in self.writes:
            r += write.__repr__() + "\n"
        return r


class EtherboneReads(Packet):
    def __init__(self, init=[], base_ret_addr=0, addrs=[]):
        Packet.__init__(self, init)
        self.base_ret_addr = base_ret_addr
        self.reads = []
        self.encoded = init != []
        for addr in addrs:
            self.add(EtherboneRead(addr))

    def add(self, read):
        self.reads.append(read)

    def get_addrs(self):
        addrs = []
        for read in self.reads:
            addrs.append(read.addr)
        return addrs

    def encode(self):
        if self.encoded:
            raise ValueError
        for byte in split_bytes(self.base_ret_addr, 4):
            self.append(byte)
        for read in self.reads:
            for byte in split_bytes(read.addr, 4):
                self.append(byte)
        self.encoded = True

    def decode(self):
        if not self.encoded:
            raise ValueError
        base_ret_addr = []
        for i in range(4):
            base_ret_addr.append(self.pop(0))
        self.base_ret_addr = merge_bytes(base_ret_addr)
        self.reads = []
        while len(self) != 0:
            read = []
            for i in range(4):
                read.append(self.pop(0))
            self.reads.append(EtherboneRead(merge_bytes(read)))
        self.encoded = False

    def __repr__(self):
        r = "Reads\n"
        r += "--------\n"
        r += "BaseRetAddr @ 0x{:08x}\n".format(self.base_ret_addr)
        for read in self.reads:
            r += read.__repr__() + "\n"
        return r


class EtherboneRecord(Packet):
    def __init__(self, init=[]):
        Packet.__init__(self, init)
        self.writes = None
        self.reads = None
        self.encoded = init != []

    def get_writes(self):
        if self.wcount == 0:
            return None
        else:
            writes = []
            for i in range((self.wcount+1)*4):
                writes.append(self.pop(0))
            return EtherboneWrites(writes)

    def get_reads(self):
        if self.rcount == 0:
            return None
        else:
            reads = []
            for i in range((self.rcount+1)*4):
                reads.append(self.pop(0))
            return EtherboneReads(reads)

    def decode(self):
        if not self.encoded:
            raise ValueError
        header = []
        for byte in self[:etherbone_record_header.length]:
            header.append(self.pop(0))
        for k, v in sorted(etherbone_record_header.fields.items()):
            setattr(self, k, get_field_data(v, header))
        self.writes = self.get_writes()
        if self.writes is not None:
            self.writes.decode()
        self.reads = self.get_reads()
        if self.reads is not None:
            self.reads.decode()
        self.encoded = False

    def set_writes(self, writes):
        self.wcount = len(writes.writes)
        writes.encode()
        for byte in writes:
            self.append(byte)

    def set_reads(self, reads):
        self.rcount = len(reads.reads)
        reads.encode()
        for byte in reads:
            self.append(byte)

    def encode(self):
        if self.encoded:
            raise ValueError
        if self.writes is not None:
            self.set_writes(self.writes)
        if self.reads is not None:
            self.set_reads(self.reads)
        header = 0
        for k, v in sorted(etherbone_record_header.fields.items()):
            value = merge_bytes(split_bytes(getattr(self, k),
                                            math.ceil(v.width/8)),
                                            "little")
            header += (value << v.offset+(v.byte*8))
        for d in split_bytes(header, etherbone_record_header.length):
            self.insert(0, d)
        self.encoded = True

    def __repr__(self, n=0):
        r = "Record {}\n".format(n)
        r += "--------\n"
        if self.encoded:
            for d in self:
                r += "{:02x}".format(d)
        else:
            for k in sorted(etherbone_record_header.fields.keys()):
                r += k + " : 0x{:0x}\n".format(getattr(self, k))
            if self.wcount != 0:
                r += self.writes.__repr__()
            if self.rcount != 0:
                r += self.reads.__repr__()
        return r


class EtherbonePacket(Packet):
    def __init__(self, init=[]):
        Packet.__init__(self, init)
        self.encoded = init != []
        self.records = []

        self.magic = etherbone_magic
        self.version = etherbone_version
        self.addr_size = 32//8
        self.port_size = 32//8
        self.nr = 0
        self.pr = 0
        self.pf = 0

    def get_records(self):
        records = []
        done = False
        payload = self
        while len(payload) != 0:
            record = EtherboneRecord(payload)
            record.decode()
            records.append(deepcopy(record))
            payload = record
        return records

    def decode(self):
        if not self.encoded:
            raise ValueError
        header = []
        for byte in self[:etherbone_packet_header.length]:
            header.append(self.pop(0))
        for k, v in sorted(etherbone_packet_header.fields.items()):
            setattr(self, k, get_field_data(v, header))
        self.records = self.get_records()
        self.encoded = False

    def set_records(self, records):
        for record in records:
            record.encode()
            for byte in record:
                self.append(byte)

    def encode(self):
        if self.encoded:
            raise ValueError
        self.set_records(self.records)
        header = 0
        for k, v in sorted(etherbone_packet_header.fields.items()):
            value = merge_bytes(split_bytes(getattr(self, k), math.ceil(v.width/8)), "little")
            header += (value << v.offset+(v.byte*8))
        for d in split_bytes(header, etherbone_packet_header.length):
            self.insert(0, d)
        self.encoded = True

    def __repr__(self):
        r = "Packet\n"
        r += "--------\n"
        if self.encoded:
            for d in self:
                r += "{:02x}".format(d)
        else:
            for k in sorted(etherbone_packet_header.fields.keys()):
                r += k + " : 0x{:0x}\n".format(getattr(self, k))
            for i, record in enumerate(self.records):
                r += record.__repr__(i)
        return r
