/* SPDX-License-Identifier: BSD-2-Clause-Patent
 *
 * A register model of the SDHCI controller, so the driver's protocol can be exercised on the host.
 *
 * This is not the driver and not a device: it is the smallest controller that answers the commands PollingHost issues, so a mistake in the
 * driver's sequence (a missing reset, a response read at the wrong time, a block read that never waits for the buffer) shows up as a failing
 * test instead of a hang on a phone.
 *
 * Three things about the real controller that this model had to get right, each found by a failing check:
 *   - interrupts are write-one-to-clear, and the driver acknowledges them;
 *   - the data port is not a stored register: a read advances the transfer;
 *   - "buffer read ready" and "transfer complete" are levels that stay up until the driver acknowledges them, not pulses.
 */

#include <cstdint>

#include "SdhciRegs.h"
#include "SdhciTypes.h"

namespace sdhci {

struct ModelCard {
    bool ready = false;
    bool selected = false;
    u16 relativeAddress = 0;
    u32 blockLength = 0;
    u8 data[512] = {};
    u32 dataIndex = 0;
};

class ModelSdhci {
public:
    ModelSdhci()
    {
        put8(kRegHostVersion, 0x03);
        put8(kRegHostVersion + 1, 0x00);
        put32(kRegCapabilities, 0x00000000u);
    }

    void fillPattern(u8 seed)
    {
        for (u32 index = 0; index < 512; ++index) {
            card.data[index] = static_cast<u8>(seed + index);
        }
    }

    u8 read8(u32 offset) { return regs[offset % sizeof(regs)]; }

    u32 read32(u32 offset)
    {
        /* levels first: these stay raised until the driver acknowledges them */
        if (offset == kRegInterruptStatus && transferComplete) {
            put32(kRegInterruptStatus, get32(kRegInterruptStatus) | kIntTransferComplete);
        }
        if (offset == kRegInterruptStatus && pendingData) {
            put32(kRegInterruptStatus, get32(kRegInterruptStatus) | kIntBufferReadReady);
        }
        if (offset == kRegBufferPort && pendingData) {
            /* the data port is not a stored register: a read advances the transfer */
            return readDataPort();
        }
        if (offset == kRegPresentState && pendingData) {
            presentState |= kPresentBufferRead;
            put32(kRegPresentState, presentState);
        }
        return get32(offset);
    }

    void write8(u32 offset, u8 value)
    {
        regs[offset % sizeof(regs)] = value;
        handleWrite(offset, value, 1);
    }

    void write16(u32 offset, u16 value)
    {
        put16(offset, value);
        handleWrite(offset, value, 2);
    }

    void write32(u32 offset, u32 value)
    {
        put32(offset, value);
        handleWrite(offset, value, 4);
    }

    const ModelCard &modelCard() const { return card; }
    u32 commands = 0;
    u32 writeCommands = 0;

private:
    void put8(u32 offset, u8 value) { regs[offset % sizeof(regs)] = value; }
    void put16(u32 offset, u16 value)
    {
        for (u32 byte = 0; byte < 2; ++byte) {
            regs[(offset + byte) % sizeof(regs)] = static_cast<u8>(value >> (8 * byte));
        }
    }
    void put32(u32 offset, u32 value)
    {
        for (u32 byte = 0; byte < 4; ++byte) {
            regs[(offset + byte) % sizeof(regs)] = static_cast<u8>(value >> (8 * byte));
        }
    }
    u32 get32(u32 offset) const
    {
        u32 value = 0;
        for (u32 byte = 0; byte < 4; ++byte) {
            value |= static_cast<u32>(regs[(offset + byte) % sizeof(regs)]) << (8 * byte);
        }
        return value;
    }

    void reset()
    {
        for (u32 index = 0; index < sizeof(regs); ++index) {
            regs[index] = 0;
        }
        put8(kRegHostVersion, 0x03);
        put8(kRegHostVersion + 1, 0x00);
        presentState = 0;
        pendingData = false;
        transferComplete = false;
        card = ModelCard{};
        blockLength = 0;
    }

    void handleWrite(u32 offset, u32 value, u32 width)
    {
        (void)width;
        if (offset == kRegSoftwareReset) {
            if (value & kResetAll) {
                reset();
            }
            put8(kRegSoftwareReset, 0);
            return;
        }
        if (offset == kRegInterruptStatus) {
            /* write-one-to-clear: storing the value would make every later poll see error bits */
            put32(kRegInterruptStatus, get32(kRegInterruptStatus) & ~value);
            if (value & kIntTransferComplete) {
                transferComplete = false;
            }
            return;
        }
        if (offset == kRegPowerControl) {
            presentState = (value & kPowerBusOn) ? kPresentCardInserted : 0;
            put32(kRegPresentState, presentState);
            return;
        }
        if (offset == kRegCommand) {
            issueCommand(static_cast<u16>(get32(kRegCommand) & 0xFFFFu));
            return;
        }
        if (offset == kRegBufferPort) {
            /* the driver writing the data port would be a write path; the model only counts it */
            writeCommands += 1;
        }
    }

    void issueCommand(u16 command)
    {
        /* The driver's encoding -- index in bits 8..13, flags below -- is the same one EDK2's SDHCI host driver builds
           (SdMmcPciHci.c: Cmd = CommandIndex << 8, then BIT1|BIT3|BIT4 for R1/R5/R6/R7 and BIT5 for data present). So the model follows a
           reference implementation, not a guess. */
        const u32 index = (command >> 8) & 0x3F;
        const u32 argument = get32(kRegArgument);
        u32 status = get32(kRegInterruptStatus) | kIntCommandComplete;

        commands += 1;
        if (index == 24u || index == 25u || index == 38u) {
            writeCommands += 1;
        }

        switch (index) {
        case kCmd0GoIdleState:
            card.ready = false;
            card.selected = false;
            card.relativeAddress = 0;
            break;
        case kCmd1SendOpCond:
            card.ready = true;
            /* the driver masks every R1 response with kCardErrors, so answer with a clean card status */
            put32(kRegResponse, 0x00000000u);
            break;
        case kCmd2AllSendCid:
            put32(kRegResponse, 0x03534453u);
            put32(kRegResponse + 4, 0x38313247u);
            break;
        case kCmd3SetRelativeAddr:
            card.relativeAddress = static_cast<u16>(argument >> 16);
            put32(kRegResponse, 0x00000900u);
            break;
        case kCmd7SelectCard:
            card.selected = (argument >> 16) == card.relativeAddress;
            put32(kRegResponse, 0x00000900u);
            break;
        case kCmd9SendCsd:
            put32(kRegResponse, 0x00000000u);
            put32(kRegResponse + 4, 0x00000000u);
            break;
        case kCmd16SetBlockLength:
            card.blockLength = argument;
            put32(kRegResponse, 0x00000900u);
            break;
        case kCmd8SendExtCsd:
        case kCmd17ReadSingleBlock:
            card.dataIndex = 0;
            pendingData = true;
            put32(kRegResponse, 0x00000900u);
            break;
        case kCmd13SendStatus:
            put32(kRegResponse, (static_cast<u32>(card.relativeAddress) << 16) | 0x00000900u);
            break;
        default:
            put32(kRegResponse, 0x00000900u);
            break;
        }
        put32(kRegInterruptStatus, status);
    }

    u32 readDataPort()
    {
        u32 value = 0;
        for (u32 byte = 0; byte < 4; ++byte) {
            value |= static_cast<u32>(card.data[(card.dataIndex + byte) & 511u]) << (8 * byte);
        }
        card.dataIndex = (card.dataIndex + 4) & 511u;
        if (card.dataIndex == 0) {
            pendingData = false;
            transferComplete = true;
            presentState &= ~kPresentBufferRead;
            put32(kRegPresentState, presentState);
        }
        return value;
    }

    u8 regs[0x200] = {};
    u32 presentState = 0;
    bool pendingData = false;
    bool transferComplete = false;
    u32 blockLength = 0;
    ModelCard card = {};
};

}  // namespace sdhci
