/* SPDX-License-Identifier: BSD-2-Clause-Patent
 *
 * Host harness for the read-only GPT parser: read an image, print the same fields the reference reader prints, so the two can be compared.
 * It is not part of the kernel; the kernel-side caller supplies its own sector reader.
 */

#include "../../drivers/Common/GptRead.h"

#include <stdio.h>
#include <stdlib.h>

static FILE *g_image;

static int read_sector(void *context, uint64_t lba, void *buffer)
{
	size_t read;

	(void)context;
	if (fseek(g_image, (long)(lba * GPT_SECTOR_BYTES), SEEK_SET) != 0) {
		return -1;
	}
	read = fread(buffer, 1, GPT_SECTOR_BYTES, g_image);
	return read == GPT_SECTOR_BYTES ? 0 : -1;
}

int main(int argc, char **argv)
{
	gpt_info info;
	gpt_status status;

	if (argc != 2) {
		fprintf(stderr, "usage: %s <image>\n", argv[0]);
		return 2;
	}
	g_image = fopen(argv[1], "rb");
	if (g_image == NULL) {
		fprintf(stderr, "cannot open %s\n", argv[1]);
		return 2;
	}
	status = gpt_parse(read_sector, NULL, &info);
	if (status != kGptOk) {
		fprintf(stderr, "refused: %s\n", gpt_status_text(status));
		fclose(g_image);
		return 1;
	}
	printf("header_crc=0x%08x\n", info.header_crc);
	printf("entries_crc=0x%08x\n", info.entries_crc);
	printf("first_usable_lba=%llu\n", (unsigned long long)info.first_usable_lba);
	printf("last_usable_lba=%llu\n", (unsigned long long)info.last_usable_lba);
	printf("backup_agrees=%d\n", info.backup_agrees);
	for (uint32_t index = 0; index < info.partition_count; ++index) {
		const gpt_partition *partition = &info.partitions[index];
		char name[GPT_NAME_WORDS + 1];
		for (uint32_t word = 0; word < GPT_NAME_WORDS; ++word) {
			unsigned int code = partition->name[word];
			name[word] = (code >= 0x20 && code < 0x7F) ? (char)code : '\0';
			if (name[word] == '\0') {
				break;
			}
		}
		name[GPT_NAME_WORDS] = '\0';
		printf("partition=%u type=%s first=%llu last=%llu name=%s\n", partition->index,
		       gpt_type_text(partition->type), (unsigned long long)partition->first_lba,
		       (unsigned long long)partition->last_lba, name);
	}
	fclose(g_image);
	return 0;
}
