/* SPDX-License-Identifier: BSD-2-Clause-Patent
 *
 * Read-only GPT parsing. See GptRead.h for what this is for and what it refuses.
 */

#include "GptRead.h"

#include <string.h>

#define GPT_SIGNATURE "EFI PART"
#define GPT_HEADER_MIN 92u
#define GPT_PROTECTIVE_TYPE 0xEEu
#define GPT_ENTRY_MIN 128u

static uint32_t gpt_crc32(const void *data, uint32_t length)
{
	const uint8_t *bytes = (const uint8_t *)data;
	uint32_t crc = 0xFFFFFFFFu;

	for (uint32_t index = 0; index < length; ++index) {
		crc ^= bytes[index];
		for (int bit = 0; bit < 8; ++bit) {
			crc = (crc >> 1) ^ (0xEDB88320u & (uint32_t)(-(int32_t)(crc & 1u)));
		}
	}
	return crc ^ 0xFFFFFFFFu;
}

static uint32_t load_le32(const uint8_t *bytes)
{
	return (uint32_t)bytes[0] | ((uint32_t)bytes[1] << 8) | ((uint32_t)bytes[2] << 16) | ((uint32_t)bytes[3] << 24);
}

static uint64_t load_le64(const uint8_t *bytes)
{
	return (uint64_t)load_le32(bytes) | ((uint64_t)load_le32(bytes + 4) << 32);
}

static int is_zero_guid(const uint8_t *guid)
{
	static const uint8_t zero[16] = {0};
	return memcmp(guid, zero, 16) == 0;
}

static gpt_type classify(const uint8_t *type_guid)
{
	/* Apple APFS: 7C3457EF-0000-11AA-AA11-00306543ECAC, first three fields little-endian. */
	static const uint8_t apfs[16] = {0xEF, 0x57, 0x34, 0x7C, 0x00, 0x00, 0xAA, 0x11,
	                                 0xAA, 0x11, 0x00, 0x30, 0x65, 0x43, 0xEC, 0xAC};
	/* EFI System Partition: C12A7328-F81F-11D2-BA4B-00A0C93EC93B. */
	static const uint8_t esp[16] = {0x28, 0x73, 0x2A, 0xC1, 0x1F, 0xF8, 0xD2, 0x11,
	                                0xBA, 0x4B, 0x00, 0xA0, 0xC9, 0x3E, 0xC9, 0x3B};
	/* Microsoft basic data: EBD0A0A2-B9E5-4433-87C0-68B6B72699C7. */
	static const uint8_t msdata[16] = {0xA2, 0xA0, 0xD0, 0xEB, 0xE5, 0xB9, 0x33, 0x44,
	                                   0x87, 0xC0, 0x68, 0xB6, 0xB7, 0x26, 0x99, 0xC7};
	if (memcmp(type_guid, esp, 16) == 0) {
		return kGptTypeEfiSystem;
	}
	if (memcmp(type_guid, msdata, 16) == 0) {
		return kGptTypeMicrosoftData;
	}
	if (memcmp(type_guid, apfs, 16) == 0) {
		return kGptTypeAppleApfs;
	}
	return kGptTypeUnknown;
}

gpt_status
gpt_parse(gpt_read_sector read_sector, void *context, gpt_info *info)
{
	uint8_t sector[GPT_SECTOR_BYTES];
	uint8_t header[GPT_SECTOR_BYTES];
	uint8_t entries[GPT_SECTOR_BYTES];
	uint32_t header_size;
	uint32_t stored_crc;
	uint32_t entries_crc;
	uint32_t entry_size;
	uint32_t entry_count;
	uint64_t entries_lba;
	uint64_t alternate_lba;
	uint64_t last_end;
	gpt_status status = kGptOk;

	if (read_sector(context, 0, sector) != 0) {
		return kGptReadFailed;
	}
	if (sector[0x1BE + 4] != GPT_PROTECTIVE_TYPE || load_le32(sector + 0x1BE + 8) != 1u) {
		return kGptBadProtectiveMbr;
	}

	if (read_sector(context, 1, header) != 0) {
		return kGptReadFailed;
	}
	if (memcmp(header, GPT_SIGNATURE, 8) != 0) {
		return kGptBadSignature;
	}
	header_size = load_le32(header + 12);
	if (header_size < GPT_HEADER_MIN || header_size > GPT_SECTOR_BYTES) {
		return kGptBadHeader;
	}
	stored_crc = load_le32(header + 16);
	{
		uint8_t copy[GPT_SECTOR_BYTES];
		memcpy(copy, header, header_size);
		memset(copy + 16, 0, 4);
		if (gpt_crc32(copy, header_size) != stored_crc) {
			return kGptBadHeaderCrc;
		}
	}
	alternate_lba = load_le64(header + 32);
	entries_lba = load_le64(header + 72);
	entry_count = load_le32(header + 80);
	entry_size = load_le32(header + 84);
	entries_crc = load_le32(header + 88);
	if (entry_size < GPT_ENTRY_MIN || (entry_size % 8u) != 0u || entry_count == 0u || entry_count > 1024u) {
		return kGptBadEntrySize;
	}
	if ((uint64_t)entry_size * entry_count > GPT_SECTOR_BYTES) {
		/* More than one sector of entries: read them one sector at a time, in order. */
		uint32_t remaining = entry_count * entry_size;
		uint32_t crc = 0xFFFFFFFFu;
		uint64_t lba = entries_lba;
		while (remaining > 0) {
			uint32_t chunk = remaining > GPT_SECTOR_BYTES ? GPT_SECTOR_BYTES : remaining;
			if (read_sector(context, lba, entries) != 0) {
				return kGptReadFailed;
			}
			for (uint32_t index = 0; index < chunk; ++index) {
				crc ^= entries[index];
				for (int bit = 0; bit < 8; ++bit) {
					crc = (crc >> 1) ^ (0xEDB88320u & (uint32_t)(-(int32_t)(crc & 1u)));
				}
			}
			remaining -= chunk;
			lba += 1;
		}
		if ((crc ^ 0xFFFFFFFFu) != entries_crc) {
			return kGptBadEntriesCrc;
		}
	} else {
		if (read_sector(context, entries_lba, entries) != 0) {
			return kGptReadFailed;
		}
		if (gpt_crc32(entries, entry_count * entry_size) != entries_crc) {
			return kGptBadEntriesCrc;
		}
	}

	memset(info, 0, sizeof(*info));
	info->first_usable_lba = load_le64(header + 40);
	info->last_usable_lba = load_le64(header + 48);
	info->header_crc = stored_crc;
	info->entries_crc = entries_crc;
	memcpy(info->disk_guid, header + 56, 16);

	last_end = info->first_usable_lba - 1;
	for (uint32_t index = 0; index < entry_count; ++index) {
		uint64_t entry_offset = (uint64_t)index * entry_size;
		uint64_t sector_lba = entries_lba + entry_offset / GPT_SECTOR_BYTES;
		uint32_t sector_offset = (uint32_t)(entry_offset % GPT_SECTOR_BYTES);
		uint8_t entry[GPT_ENTRY_MIN];
		uint64_t first_lba, end_lba;
		gpt_type type;

		if (read_sector(context, sector_lba, entries) != 0) {
			return kGptReadFailed;
		}
		memcpy(entry, entries + sector_offset, GPT_ENTRY_MIN);
		if (is_zero_guid(entry)) {
			continue;
		}
		type = classify(entry);
		first_lba = load_le64(entry + 32);
		end_lba = load_le64(entry + 40);
		if (first_lba > end_lba || first_lba <= last_end) {
			status = kGptOverlap;
			break;
		}
		last_end = end_lba;
		if (info->partition_count >= GPT_MAX_PARTITIONS) {
			status = kGptTooManyPartitions;
			break;
		}
		{
			gpt_partition *partition = &info->partitions[info->partition_count];
			partition->index = index;
			partition->type = type;
			partition->first_lba = first_lba;
			partition->last_lba = end_lba;
			for (uint32_t word = 0; word < GPT_NAME_WORDS; ++word) {
				partition->name[word] = (uint16_t)(entry[56 + word * 2] | (entry[57 + word * 2] << 8));
			}
		}
		info->partition_count += 1;
	}

	if (status == kGptOk) {
		uint8_t backup[GPT_SECTOR_BYTES];
		if (alternate_lba != 0 && read_sector(context, alternate_lba, backup) == 0 &&
		    memcmp(backup, GPT_SIGNATURE, 8) == 0) {
			uint64_t backup_my_lba = load_le64(backup + 24);
			uint64_t backup_alt = load_le64(backup + 32);
			info->backup_agrees = (backup_my_lba == alternate_lba && backup_alt == 1u &&
			                       memcmp(backup + 56, info->disk_guid, 16) == 0);
		}
	}
	return status;
}

const char *
gpt_status_text(gpt_status status)
{
	switch (status) {
	case kGptOk: return "ok";
	case kGptBadProtectiveMbr: return "bad protective MBR";
	case kGptBadSignature: return "bad signature";
	case kGptBadHeader: return "bad header";
	case kGptBadHeaderCrc: return "bad header CRC";
	case kGptBadEntriesCrc: return "bad entry-array CRC";
	case kGptBadEntrySize: return "bad entry size or count";
	case kGptOverlap: return "partitions overlap";
	case kGptReadFailed: return "read failed";
	case kGptBackupDisagrees: return "backup disagrees";
	case kGptTooManyPartitions: return "too many partitions";
	default: return "unknown";
	}
}

const char *
gpt_type_text(gpt_type type)
{
	switch (type) {
	case kGptTypeEfiSystem: return "EFI System Partition";
	case kGptTypeMicrosoftData: return "Microsoft basic data";
	case kGptTypeAppleApfs: return "Apple APFS";
	default: return "unknown";
	}
}
