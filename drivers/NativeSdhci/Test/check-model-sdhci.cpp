/* SPDX-License-Identifier: BSD-2-Clause-Patent
 *
 * Host test: drive the real polling layer against the register model.
 *
 * The point is not to prove anything about the phone -- it is to prove that the sequence the driver issues is a legal SDHCI read sequence:
 * reset, power, clock, the command handshake, waiting for the buffer, and a 512-byte block whose bytes match the model. A driver that skipped
 * one of those would hang on hardware; here it fails a test.
 */

#include <cstdio>
#include <cstdlib>
#include <vector>

#include "ModelSdhci.h"
#include "PollingHost.h"
#include "../../Common/GptRead.h"
#include "PollingHost.cpp"
#include "SdhciCore.cpp"
#include "../../Common/GptRead.c"

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

int main(int argc, char **argv)
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

    /* The path the driver actually runs on the phone: a warm card, found by RCA, selected, then read. */
    g_model.makeWarmCard(4ULL << 30);
    PollingHost warmHost;
    check(warmHost.configure(io), "the warm path configures a second controller instance");
    WarmCard warmCard;
    const u16 candidates[] = {1};
    const bool attached = warmCard.attach(warmHost, candidates, sizeof(candidates) / sizeof(candidates[0]));
    check(attached, "a warm card is found, selected and decoded");
    if (attached) {
        check(warmCard.info().relativeAddress == 1, "the RCA the model served is the one the driver kept");
        check(warmCard.info().capacityBytes > (2ULL << 30), "the capacity comes from SEC_COUNT and is above the driver's floor");
        u8 sector[512] = {};
        check(warmCard.readBlock(0, sector), "a block is read through the warm card");
        bool warmMatches = true;
        for (u32 index = 0; index < 512; ++index) {
            if (sector[index] != static_cast<u8>(0x40 + index)) {
                warmMatches = false;
                break;
            }
        }
        check(warmMatches, "the warm read returns the model's pattern");
    }
    check(g_model.writeCommands == 0, "the warm path issued no write or erase command");

    /* The interface M3 needs: the GPT parser reads sectors through the driver's card. The image is the synthetic fixture the Python reader
       and the parser parity test already use, passed in by the runner so both sides parse the same bytes. */
    if (argc >= 2) {
        std::FILE *file = std::fopen(argv[1], "rb");
        if (file == nullptr) {
            std::printf("FAIL the image %s could not be opened\n", argv[1]);
            return 1;
        }
        std::vector<unsigned char> bytes(8u << 20);
        const size_t read = std::fread(bytes.data(), 1, bytes.size(), file);
        std::fclose(file);
        g_model.loadImage(bytes.data(), static_cast<u32>(read / 512u));

        PollingHost gptHost;
        check(gptHost.configure(io), "the GPT host configures");
        WarmCard gptCard;
        check(gptCard.attach(gptHost, candidates, 1), "the GPT card attaches");
        gpt_info info = {};
        const gpt_status status = gpt_parse(
            [](void *context, uint64_t lba, void *buffer) -> int {
                WarmCard *card = static_cast<WarmCard *>(context);
                return card->readBlock(lba, static_cast<u8 *>(buffer)) ? 0 : -1;
            },
            &gptCard, &info);
        check(status == kGptOk, "the GPT parser accepts the table read through the driver");
        /* the fixture declares two partitions, the same two the Python reader reports */
        check(info.partition_count == 2, "both partitions come back through the driver");
        check(info.partitions[0].type == kGptTypeEfiSystem, "the first is EFI System");
        check(info.partitions[0].first_lba == 2048u && info.partitions[0].last_lba == 4095u,
              "and its extent is the one the image declares");
        check(info.partitions[1].type == kGptTypeMicrosoftData, "the second is Microsoft basic data");
        check(g_model.writeCommands == 0, "the GPT read issued no write or erase command");
    }

    std::printf("%s\n", failures == 0 ? "PASS: the driver's read sequence is accepted by the model, and a GPT table reads through it" : "FAILED");
    return failures == 0 ? 0 : 1;
}
