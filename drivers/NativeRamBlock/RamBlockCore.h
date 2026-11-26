/*
 * Geometry and buffer arithmetic for the bring-up root device.
 *
 * This file deliberately has no IOKit dependency: the numbers are decided here, the IOMedia subclass in
 * NativeRamBlock.cpp only asks for them. docs/emulation/root-device-design.md explains why the synthetic
 * media comes before any eMMC read path.
 *
 * Include and type notes: the kernel builds this file freestanding, so it uses <stdint.h> and plain
 * uint64_t, never <cstdint> or std::uint64_t -- the first compile in the kernel job failed on exactly
 * that ('cstdint' file not found).
 */

#ifndef NATIVE_RAM_BLOCK_CORE_H
#define NATIVE_RAM_BLOCK_CORE_H

#include <stdint.h>

namespace native_ram_block {

// A media the kernel can mount needs a geometry, a content hint and a buffer it can read. The block size is
// fixed at the sector size the HFS layer expects; the block count follows from the byte budget.
constexpr uint32_t kBlockSize = 512;
constexpr const char *kContentHint = "Apple_HFS";
constexpr uint64_t kDefaultBytes = 4ull * 1024 * 1024;

struct Geometry {
	uint64_t bytes;
	uint32_t blockSize;
	uint64_t blockCount;

	bool valid() const
	{
		return blockSize == kBlockSize && bytes >= blockSize && blockCount == bytes / blockSize;
	}
};

Geometry geometry_for(uint64_t bytes);

// A read is served only when it lies inside the buffer; the caller gets the byte count it may copy.
bool read_within(const Geometry &geometry, uint64_t byteOffset, uint64_t length,
    uint64_t *served);

// Writes are accepted for the whole buffer: this device exists to be read, but a mount may probe it.
bool write_within(const Geometry &geometry, uint64_t byteOffset, uint64_t length);

} // namespace native_ram_block

#endif
