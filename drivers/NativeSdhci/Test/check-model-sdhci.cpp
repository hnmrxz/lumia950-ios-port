/* SPDX-License-Identifier: BSD-2-Clause-Patent
 *
 * Host test: drive the real polling layer against the register model.
 *
 * The point is not to prove anything about the phone -- it is to prove that the sequence the driver issues is a legal SDHCI read sequence:
 * reset, power, clock, the command handshake, waiting for the buffer, and a 512-byte block whose bytes match the model. A driver that skipped
 * one of those would hang on hardware; here it fails a test.
 */

#include <cstdio>
#include <cstring>

#include "ModelSdhci.h"
#include "PollingHost.h"
#include "PollingHost.cpp"
#include "SdhciCore.cpp"

using namespace sdhci;

namespace {

sdhci::ModelSdhci g_model(0);

sdhci::u8 modelRead8(void *, sdhci::u32 offset) { return g_model.read8(offset); }
sdhci::u32 modelRead32(void *, sdhci::u32 offset) { return g_model.read32(offset); }
void modelWrite8(void *, sdhci::u32 offset, sdhci::u8 value) { g_model.write8(offset, value); }
void modelWrite16(void *, sdhci::u32 offset, sdhci::u16 value) { g_model.write16(offset, value); }
void modelWrite32(void *, sdhci::u32 offset, sdhci::u32 value) { g_model.write32(offset, value); }
void modelDelay(void *, sdhci::u32) {}

int failures = 0;

void check(bool condition, const char *what)
{
    if (!condition) {
        std::printf("FAIL %s\n", what);
        ++failures;
    } else {
        std::printf("ok   %s\n", what);
    }
}

}  // namespace

int main()
{
    g_model.fillPattern(0x40);

    sdhci::RegisterIo io = {};
    io.context = &g_model;
    io.read8 = modelRead8;
    io.read32 = modelRead32;
    io.write8 = modelWrite8;
    io.write16 = modelWrite16;
    io.write32 = modelWrite32;
    io.delayUs = modelDelay;

    sdhci::PollingHost host;
    check(host.configure(io), "configure accepts a complete register interface");
    check(host.start(), "start resets and powers the controller");

    u32 response[4] = {};
    const bool cmd0 = host.command(0, 0, sdhci::ResponseType::None, response);
    std::printf("  CMD0 error=%s phase=%u interrupt=0x%x\n", hostErrorName(host.result().error),
                static_cast<unsigned>(host.result().phase), host.result().interruptStatus);
    check(cmd0, "CMD0 goes out");
    check(host.command(1, 0x40FF8080u, sdhci::ResponseType::R1, response), "CMD1 goes out");
    check(host.command(2, 0, sdhci::ResponseType::R2, response), "CMD2 goes out");
    check(host.command(3, 1u << 16, sdhci::ResponseType::R1, response), "CMD3 assigns an address");

    u8 block[512] = {};
    const bool read = host.read512(sdhci::kCmd17ReadSingleBlock, 0, block);
    std::printf("  CMD17 error=%s phase=%u interrupt=0x%x bytes=%u\n", hostErrorName(host.result().error),
                static_cast<unsigned>(host.result().phase), host.result().interruptStatus,
                host.result().bytesTransferred);
    check(read, "CMD17 reads a block");
    bool matches = true;
    for (u32 index = 0; index < 512; ++index) {
        if (block[index] != static_cast<u8>(0x40 + index)) {
            matches = false;
            break;
        }
    }
    check(matches, "the block matches the model's pattern");
    check(g_model.writeCommands == 0, "no write or erase command was issued");

    sdhci::PollingHost refusing = host;
    (void)refusing;
    return failures == 0 ? 0 : 1;
}
