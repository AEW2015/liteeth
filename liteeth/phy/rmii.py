from liteeth.common import *

from litex.gen.genlib.cdc import MultiReg
from litex.gen.genlib.misc import WaitTimer
from litex.gen.genlib.io import DDROutput
from litex.gen.genlib.resetsync import AsyncResetSynchronizer

from liteeth.phy.common import *


def converter_description(dw):
    payload_layout = [("data", dw)]
    return EndpointDescription(payload_layout, packetized=True)


class LiteEthPHYRMIITX(Module):
    def __init__(self, pads):
        self.sink = sink = Sink(eth_phy_description(8))

        # # #

        converter = Converter(converter_description(8),
                              converter_description(2))
        self.submodules += converter
        self.comb += [
            converter.sink.stb.eq(sink.stb),
            converter.sink.data.eq(sink.data),
            sink.ack.eq(converter.sink.ack),
            converter.source.ack.eq(1)
        ]
        self.sync += [
            pads.tx_en.eq(converter.source.stb),
            pads.tx_data.eq(converter.source.data)
        ]


class LiteEthPHYRMIIRX(Module):
    def __init__(self, pads):
        self.source = source = Source(eth_phy_description(8))

        # # #

        sop = Signal(reset=1)
        sop_set = Signal()
        sop_clr = Signal()
        self.sync += If(sop_set, sop.eq(1)).Elif(sop_clr, sop.eq(0))

        converter = Converter(converter_description(2),
                              converter_description(8))
        converter = ResetInserter()(converter)
        self.submodules += converter

        converter_sink_stb = Signal()
        converter_sink_sop = Signal()
        converter_sink_data = Signal(2)

        self.specials += [
            MultiReg(converter_sink_stb, converter.sink.stb, n=2),
            MultiReg(converter_sink_sop, converter.sink.sop, n=2),
            MultiReg(converter_sink_data, converter.sink.data, n=2)
        ]

        crs_dv = Signal()
        crs_dv_d = Signal()
        rx_data = Signal(2)
        self.sync += [
            crs_dv.eq(pads.crs_dv),
            crs_dv_d.eq(crs_dv),
            rx_data.eq(pads.rx_data)
        ]

        self.submodules.fsm = fsm = FSM(reset_state="IDLE")
        fsm.act("IDLE",
            If(crs_dv & (rx_data != 0b00),
                converter_sink_stb.eq(1),
                converter_sink_sop.eq(1),
                converter_sink_data.eq(rx_data),
                NextState("RECEIVE")
            ).Else(
               converter.reset.eq(1)
            )
        )
        fsm.act("RECEIVE",
            converter_sink_stb.eq(1),
            converter_sink_data.eq(rx_data),
            # end of frame when 2 consecutives 0 on crs_dv
            If(~(crs_dv | crs_dv_d),
              converter.sink.eop.eq(1),
              NextState("IDLE")
            )
        )
        self.comb += converter.source.connect(source)


class LiteEthPHYRMIICRG(Module, AutoCSR):
    def __init__(self, clock_pads, pads, with_hw_init_reset):
        self._reset = CSRStorage()

        # # #

        self.clock_domains.cd_eth_rx = ClockDomain()
        self.clock_domains.cd_eth_tx = ClockDomain()
        self.comb += [
            self.cd_eth_rx.clk.eq(ClockSignal("eth")),
            self.cd_eth_tx.clk.eq(ClockSignal("eth"))
        ]

        self.specials += DDROutput(0, 1, clock_pads.ref_clk, ClockSignal("eth_tx"))

        reset = Signal()
        if with_hw_init_reset:
            self.submodules.hw_reset = LiteEthPHYHWReset()
            self.comb += reset.eq(self._reset.storage | self.hw_reset.reset)
        else:
            self.comb += reset.eq(self._reset.storage)

        self.comb += pads.rst_n.eq(~reset)
        self.specials += [
            AsyncResetSynchronizer(self.cd_eth_tx, reset),
            AsyncResetSynchronizer(self.cd_eth_rx, reset),
        ]


class LiteEthPHYRMII(Module, AutoCSR):
    def __init__(self, clock_pads, pads, with_hw_init_reset=True):
        self.dw = 8
        self.submodules.crg = LiteEthPHYRMIICRG(clock_pads, pads, with_hw_init_reset)
        self.submodules.tx = ClockDomainsRenamer("eth_tx")(LiteEthPHYRMIITX(pads))
        self.submodules.rx = ClockDomainsRenamer("eth_rx")(LiteEthPHYRMIIRX(pads))
        self.sink, self.source = self.tx.sink, self.rx.source

        if hasattr(pads, "mdc"):
            self.submodules.mdio = LiteEthPHYMDIO(pads)
