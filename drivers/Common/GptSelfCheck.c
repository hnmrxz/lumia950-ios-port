/* SPDX-License-Identifier: BSD-2-Clause-Patent
 *
 * In-kernel self-check for the read-only GPT parser.
 *
 * The parser is in the image; this makes it run, on a synthetic disk assembled in memory, so the evidence is "the parser executed inside the
 * kernel and gave the right answers" rather than "the symbol exists". It builds a valid GPT, parses it, corrupts the header CRC and parses
 * again: the valid table must be accepted with one partition, and the damaged one must be refused.
 *
 * No I/O and no allocation: a few static sectors and a callback that serves them by LBA. The whole thing is smaller than the parser it tests.
 */

#include "GptRead.h"

#define SELF_SECTORS 2048u          /* 1 MiB, so the primary and backup tables fit in readable sectors */
#define SELF_ENTRIES 4u
#define SELF_ENTRY_BYTES 128u
#define SELF_ENTRIES_LBA 2u
#define SELF_BACKUP_ENTRIES_LBA (SELF_SECTORS - 2u)
#define SELF_FIRST_USABLE 34u
#define SELF_LAST_USABLE (SELF_SECTORS - 35u)

static uint8_t sector0[512];
static uint8_t header[512];
static uint8_t backup_header[512];
static uint8_t entries[SELF_ENTRIES * SELF_ENTRY_BYTES];
static unsigned int fault_in_header;

static void put_le32(uint8_t *at, uint32_t value)
{
	at[0] = (uint8_t)value;
	at[1] = (uint8_t)(value >> 8);
	at[2] = (uint8_t)(value >> 16);
	at[3] = (uint8_t)(value >> 24);
}

static void put_le64(uint8_t *at, uint64_t value)
{
	put_le32(at, (uint32_t)value);
	put_le32(at + 4, (uint32_t)(value >> 32));
}

static uint32_t self_crc32(const uint8_t *bytes, uint32_t length)
{
	uint32_t crc = 0xFFFFFFFFu;

	for (uint32_t index = 0; index < length; ++index) {
		crc ^= bytes[index];
		for (int bit = 0; bit < 8; ++bit) {
			crc = (crc >> 1) ^ (0xEDB88320u & (uint32_t)(-(int32_t)(crc & 1u)));
		}
	}
	return crc ^ 0xFFFFFFFFu;
}

static void build_header(uint8_t *target, uint64_t my_lba, uint64_t alternate_lba, uint64_t entries_lba)
{
	for (unsigned int index = 0; index < 512u; ++index) {
		target[index] = 0;
	}
	target[0] = 'E';
	target[1] = 'F';
	target[2] = 'I';
	target[3] = ' ';
	target[4] = 'P';
	target[5] = 'A';
	target[6] = 'R';
	target[7] = 'T';
	put_le32(target + 8, 0x00010000u);
	put_le32(target + 12, 92u);
	put_le64(target + 24, my_lba);
	put_le64(target + 32, alternate_lba);
	put_le64(target + 40, SELF_FIRST_USABLE);
	put_le64(target + 48, SELF_LAST_USABLE);
	for (unsigned int index = 0; index < 16u; ++index) {
		target[56 + index] = (uint8_t)(0x10u + index);
	}
	put_le64(target + 72, entries_lba);
	put_le32(target + 80, SELF_ENTRIES);
	put_le32(target + 84, SELF_ENTRY_BYTES);
	put_le32(target + 88, self_crc32(entries, sizeof(entries)));
	put_le32(target + 16, fault_in_header ? 0xDEADBEEFu : self_crc32(target, 92u));
}

static void build_disk(void)
{
	static const uint8_t esp_type[16] = {0x28, 0x73, 0x2A, 0xC1, 0x1F, 0xF8, 0xD2, 0x11,
	                                     0xBA, 0x4B, 0x00, 0xA0, 0xC9, 0x3E, 0xC9, 0x3B};

	for (unsigned int index = 0; index < 512u; ++index) {
		sector0[index] = 0;
	}
	sector0[0x1BE + 4] = 0xEEu;
	put_le32(sector0 + 0x1BE + 8, 1u);
	put_le32(sector0 + 0x1BE + 12, SELF_SECTORS - 1u);

	for (unsigned int index = 0; index < sizeof(entries); ++index) {
		entries[index] = 0;
	}
	for (unsigned int index = 0; index < 16u; ++index) {
		entries[index] = esp_type[index];
	}
	put_le64(entries + 32, 64u);       /* first LBA, inside the usable range */
	put_le64(entries + 40, 200u);      /* last LBA */
	entries[56] = 'S';
	entries[58] = 'E';
	entries[60] = 'L';
	entries[62] = 'F';
}

static int self_read_sector(void *context, uint64_t lba, void *buffer)
{
	uint8_t *target = (uint8_t *)buffer;
	const uint8_t *source = 0;

	(void)context;
	if (lba == 0u) {
		source = sector0;
	} else if (lba == 1u) {
		source = header;
	} else if (lba == SELF_ENTRIES_LBA || lba == SELF_BACKUP_ENTRIES_LBA) {
		source = entries;
	} else if (lba == SELF_SECTORS - 1u) {
		source = backup_header;
	} else {
		/* a device without media fails here, which is exactly what the parser must report */
		return -1;
	}
	for (unsigned int index = 0; index < 512u; ++index) {
		target[index] = source[index];
	}
	return 0;
}

static int run_parser(gpt_info *info)
{
	return (int)gpt_parse(self_read_sector, 0, info);
}

unsigned int
lumia_gpt_selfcheck(void)
{
	gpt_info info;
	int status;

	build_disk();

	fault_in_header = 0;
	build_header(header, 1u, SELF_SECTORS - 1u, SELF_ENTRIES_LBA);
	build_header(backup_header, SELF_SECTORS - 1u, 1u, SELF_BACKUP_ENTRIES_LBA);
	status = run_parser(&info);
	if (status != (int)kGptOk) {
		return 1u;  /* a valid table was refused */
	}
	if (info.partition_count != 1u || info.partitions[0].type != kGptTypeEfiSystem ||
	    info.partitions[0].first_lba != 64u || info.partitions[0].last_lba != 200u) {
		return 2u;  /* the partition it read back is not the one that was written */
	}

	fault_in_header = 1;
	build_header(header, 1u, SELF_SECTORS - 1u, SELF_ENTRIES_LBA);
	status = run_parser(&info);
	if (status == (int)kGptOk) {
		return 3u;  /* a damaged table was accepted */
	}
	if (status != (int)kGptBadHeaderCrc) {
		return 4u;  /* refused, but not for the reason the damage was in */
	}
	fault_in_header = 0;
	return 0u;
}
