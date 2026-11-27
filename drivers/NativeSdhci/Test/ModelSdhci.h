/* SPDX-License-Identifier: BSD-2-Clause-Patent
 *
 * A register model of the SDHCI controller, so the driver's protocol can be exercised on the host.
 *
 * This is not the driver and not a device: it is the smallest controller that answers the commands PollingHost issues, so a mistake in the
 * driver's sequence (a missing reset, a response read at the wrong time, a block read that never waits for the buffer) shows up as a failing
 * test instead of a hang on a phone.
 *
 * It implements only what a read path needs: software reset, power and clock, command inhibit handling, the command/response/transfer
 * registers, the present-state and interrupt bits, and a block of pattern data served on CMD17.
 */

#include <cstdint>
#include <cstdio>
#include <cstring>

#include "SdhciRegs.h"
#include "SdhciTypes.h"

namespace sdhci {

struct ModelCard {
    bool resetDone = false;
    bool ready = false;
    bool selected = false;
    u16 relativeAddress = 0;
    u32 blockLength = 0;
    u8 data[512] = {};
    u32 dataIndex = 0;
    u32 cardStatus = 0;
};

class ModelSdhci {
public:
    explicit ModelSdhci(u32 base)
        : hcBase(base)
    {
        for (u32 index = 0; index < sizeof(regs); ++index) {
            regs[index] = 0;
        }
        card.resetDone = true;
        // 3.0 host, base clock 200 MHz, no slot interrupts: the driver reads these to choose a divider.
        put32(kRegCapabilities, 0x00000000u);
        put8(kRegHostVersion, 0x03);
        put8(kRegHostVersion + 1, 0x00);
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
        if (offset == kRegInterruptStatus && pendingData) {
            std::printf("      [model] buffer ready advertised; IS now 0x%x\n", get32(kRegInterruptStatus));
            /* data is ready the moment the host looks: the driver polls this register, and it acknowledges the command's bits before it
               starts polling, so setting the bit at command time would be cleared again */
            put32(kRegInterruptStatus, get32(kRegInterruptStatus) | kIntBufferReadReady);
        }
        if (offset == kRegPresentState && pendingData) {
            presentState |= kPresentBufferRead;
            put32(kRegInterruptStatus, get32(kRegInterruptStatus) | kIntBufferReadReady);
        }
        u32 value = 0;
        for (u32 byte = 0; byte < 4; ++byte) {
            value |= static_cast<u32>(regs[(offset + byte) % sizeof(regs)]) << (8 * byte);
        }
        return value;
    }

    void write8(u32 offset, u8 value)
    {
        regs[offset % sizeof(regs)] = value;
        handleWrite(offset, value, 1);
    }

    void write16(u32 offset, u16 value)
    {
        for (u32 byte = 0; byte < 2; ++byte) {
            regs[(offset + byte) % sizeof(regs)] = static_cast<u8>(value >> (8 * byte));
        }
        handleWrite(offset, value, 2);
    }

    void write32(u32 offset, u32 value)
    {
        for (u32 byte = 0; byte < 4; ++byte) {
            regs[(offset + byte) % sizeof(regs)] = static_cast<u8>(value >> (8 * byte));
        }
        handleWrite(offset, value, 4);
    }

    /* the driver's own counters, so a test can assert that no write command was issued */
    u32 writeCommands = 0;
    u32 commands = 0;

private:
    void put8(u32 offset, u8 value) { regs[offset % sizeof(regs)] = value; }
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

    void handleWrite(u32 offset, u32 value, u32 width)
    {
        if (offset == kRegSoftwareReset && width == 1) {
            if (value & kResetAll) {
                const u32 capabilities = get32(kRegCapabilities);
                for (u32 index = 0; index < sizeof(regs); ++index) {
                    regs[index] = 0;
                }
                put32(kRegCapabilities, capabilities);
                put8(kRegHostVersion, 0x03);
                put8(kRegHostVersion + 1, 0x00);
                card = ModelCard{};
                card.resetDone = true;
                pendingData = false;
            }
            put8(kRegSoftwareReset, 0);
            return;
        }
        if (offset == kRegInterruptStatus) {
            std::printf("      [model] IS write 0x%x (clear)\n", value);
            /* interrupts are write-one-to-clear on real hardware; storing the value makes every later poll see error bits */
            const u32 current = get32(kRegInterruptStatus);
            put32(kRegInterruptStatus, current & ~value);
            return;
        }
        if (offset == kRegPowerControl && width == 1) {
            const bool on = (value & kPowerBusOn) != 0;
            presentState = on ? kPresentCardInserted : 0;
            put32(kRegPresentState, presentState);
            return;
        }
        if (offset == kRegCommand) {
            /* read the word back from the register file: the driver may split the write, and the bytes on the bus are what hardware sees */
            issueCommand(static_cast<u16>(get32(kRegCommand) & 0xFFFFu));
            return;
        }
        if (offset == kRegBufferPort) {
            /* host writes into the data port: a write path the driver must never reach */
            card.dataIndex = (card.dataIndex + 4) & 511u;
            put32(kRegInterruptStatus, get32(kRegInterruptStatus) | kIntBufferWriteReady);
        }
    }

    void issueCommand(u16 command)
    {
        /* The model follows the driver's encoding -- index in bits 8..13, flags below it. Whether that encoding matches the SDHCI
           specification is an open question recorded in the milestone notes, not something this model is allowed to decide. */
        const u32 index = (command >> 8) & 0x3F;
        const u32 argument = get32(kRegArgument);
        commands += 1;
        std::printf("  [model] cmd %u arg=0x%x raw=0x%x\n", index, argument, command);
        u32 status = get32(kRegInterruptStatus);
        status |= kIntCommandComplete;

        if (index == 24 || index == 25 || index == 38) {
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
            put32(kRegResponse, 0x00000000u);   /* the driver masks every R1 response with kCardErrors, so the model answers with a clean card status */
            break;
        case kCmd2AllSendCid:
            put32(kRegResponse, 0x03534453u);
            put32(kRegResponse + 4, 0x38313247u);
            break;
        case kCmd3SetRelativeAddr:
            card.relativeAddress = static_cast<u16>(argument >> 16);
            put32(kRegResponse, (static_cast<u32>(card.relativeAddress) << 16) | 0x0500u);
            break;
        case kCmd7SelectCard:
            card.selected = (argument >> 16) == card.relativeAddress;
            put32(kRegResponse, 0x00000900u);
            break;
        case kCmd9SendCsd:
            put32(kRegResponse, 0x00000000u);
            put32(kRegResponse + 4, 0x00000000u);
            break;
        case kCmd8SendExtCsd:
            card.dataIndex = 0;
            pendingData = true;
            break;
        case kCmd16SetBlockLength:
            card.blockLength = argument;
            put32(kRegResponse, 0x00000900u);
            break;
        case kCmd17ReadSingleBlock:
            card.dataIndex = 0;
            pendingData = true;
            put32(kRegResponse, 0x00000900u);
            break;
        case kCmd13SendStatus:
            put32(kRegResponse, (static_cast<u32>(card.relativeAddress) << 16) | 0x00000900u);
            break;
        default:
            break;
        }
        put32(kRegInterruptStatus, status);
    }

public:
    /* the data port hands out the pattern four bytes at a time */
    u32 readDataPort()
    {
        u32 value = 0;
        for (u32 byte = 0; byte < 4; ++byte) {
            value |= static_cast<u32>(card.data[(card.dataIndex + byte) & 511u]) << (8 * byte);
        }
        card.dataIndex = (card.dataIndex + 4) & 511u;
        if (card.dataIndex == 0) {
            pendingData = false;
            presentState &= ~kPresentBufferRead;
            put32(kRegPresentState, presentState);
            put32(kRegInterruptStatus, get32(kRegInterruptStatus) | kIntTransferComplete);
        } else {
            put32(kRegInterruptStatus, get32(kRegInterruptStatus) | kIntBufferReadReady);
        }
        return value;
    }

    const ModelCard &modelCard() const { return card; }

private:
    u32 hcBase;
    u8 regs[0x200] = {};
    u32 presentState = 0;
    bool pendingData = false;
    ModelCard card = {};
};

}  // namespace sdhci
