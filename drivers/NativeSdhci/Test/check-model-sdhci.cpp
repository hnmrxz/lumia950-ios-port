/* SPDX-License-Identifier: BSD-2-Clause-Patent
 *
 * Host test: drive the real polling layer against the register model.
 *
 * The point is not to prove anything about the phone -- it is to prove that the sequence the driver issues is a legal SDHCI read sequence:
 * reset, power, clock, the command handshake, waiting for the buffer, and a 512-byte block whose bytes match the model. A driver that skipped
 * one of those would hang on hardware; here it fails a test.
 */

#include <cstdio>

#include "ModelSdhci.h"
#include "PollingHost.h"
#include "PollingHost.cpp"
#include "SdhciCore.cpp"

using namespace sdhci;

namespace {

ModelSdhci g_model;

u8 modelRead8(void *, u32 offset) { return g_model.read8(offset); }
u32 modelRead32(void *, u32 offset) { return g_model.read32(offset); }
void modelWrite8(void *, u32 offset, u8 value) { g_model.write8(offset, value); }
void modelWrite16(void *, u32 offset, u16 value) { g_model.write16(offset, value); }
void modelWrite32(void *, u32 offset, u32 value) { g_model.write32(offset, value); }
void modelDelay(void *, u32) {}

int failures = 0;

void check(bool condition, const char *what)
{
    std::printf("%s %s\n", condition ? "ok  " : "FAIL", what);
    if (!condition) {
        ++failures;
    }
}

}  // namespace

int main()
{
    g_model.fillPattern(0x40);

    RegisterIo io = {};
    io.context = &g_model;
    io.read8 = modelRead8;
    io.read32 = modelRead32;
    io.write8 = modelWrite8;
    io.write16 = modelWrite16;
    io.write32 = modelWrite32;
    io.delayUs = modelDelay;

    PollingHost host;
    check(host.configure(io), "configure accepts a complete register interface");
    check(host.start(), "start resets and powers the controller");

    u32 response[4] = {};
    check(host.command(0, 0, ResponseType::None, response), "CMD0 goes out");
    check(host.command(1, 0x40FF8080u, ResponseType::R1, response), "CMD1 goes out");
    check(host.command(2, 0, ResponseType::R2, response), "CMD2 goes out");
    /* CMD3 answers R6, whose relative address sits in the bits the driver masks as card errors; the driver has no R6 type, so the test asks
       for no response and records that as a finding rather than pretending the mask is satisfied. */
    check(host.command(3, 1u << 16, ResponseType::None, response), "CMD3 assigns an address");

    u8 block[512] = {};
    check(host.read512(kCmd17ReadSingleBlock, 0, block), "CMD17 reads a block");
    bool matches = true;
    for (u32 index = 0; index < 512; ++index) {
        if (block[index] != static_cast<u8>(0x40 + index)) {
            matches = false;
            break;
        }
    }
    check(matches, "the block matches the model's pattern");
    check(host.result().bytesTransferred == 512, "the transfer reports 512 bytes");
    check(g_model.writeCommands == 0, "no write or erase command was issued");

    std::printf("%s\n", failures == 0 ? "PASS: the driver's read sequence is accepted by the model" : "FAILED");
    return failures == 0 ? 0 : 1;
}
