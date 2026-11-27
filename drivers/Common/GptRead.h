/* SPDX-License-Identifier: BSD-2-Clause-Patent
 *
 * Read-only GPT parsing, for the milestone-3 work.
 *
 * The acceptance for M3 is written against an independent reader, so this parser is deliberately the same shape: it refuses anything it
 * cannot verify (protective MBR, header CRC, entry-array CRC, primary/backup agreement, overlap) and it never writes to the medium -- it only
 * asks a caller-supplied callback for sectors.
 *
 * It is plain C with no OS or IOKit dependency, so the host test can compile it with the same sources and compare its answers with
 * scripts/gpt-read.py on the same synthetic image. That comparison is the point: the kernel parser and the reference reader have to agree
 * before either one is allowed to describe a real disk.
 */

#ifndef NATIVE_GPT_READ_H
#define NATIVE_GPT_READ_H

#include <stdint.h>

#define GPT_SECTOR_BYTES 512u
#define GPT_MAX_PARTITIONS 32u
#define GPT_NAME_WORDS 36u

typedef enum {
	kGptOk = 0,
	kGptBadProtectiveMbr = 1,
	kGptBadSignature = 2,
	kGptBadHeader = 3,
	kGptBadHeaderCrc = 4,
	kGptBadEntriesCrc = 5,
	kGptBadEntrySize = 6,
	kGptOverlap = 7,
	kGptReadFailed = 8,
	kGptBackupDisagrees = 9,
	kGptTooManyPartitions = 10
} gpt_status;

typedef enum {
	kGptTypeUnknown = 0,
	kGptTypeEfiSystem = 1,
	kGptTypeMicrosoftData = 2,
	kGptTypeAppleApfs = 3
} gpt_type;

typedef struct {
	uint32_t index;
	gpt_type type;
	uint64_t first_lba;
	uint64_t last_lba;
	uint16_t name[GPT_NAME_WORDS];
} gpt_partition;

typedef struct {
	uint64_t disk_guid[2];
	uint64_t first_usable_lba;
	uint64_t last_usable_lba;
	uint32_t header_crc;
	uint32_t entries_crc;
	uint32_t partition_count;
	gpt_partition partitions[GPT_MAX_PARTITIONS];
	int backup_agrees;
} gpt_info;

/* Returns 0 on success, negative on a read failure. */
typedef int (*gpt_read_sector)(void *context, uint64_t lba, void *buffer);

gpt_status gpt_parse(gpt_read_sector read_sector, void *context, gpt_info *info);
const char *gpt_status_text(gpt_status status);
const char *gpt_type_text(gpt_type type);

#endif /* NATIVE_GPT_READ_H */
