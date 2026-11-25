#include "RamBlockCore.h"

namespace native_ram_block {

Geometry
geometry_for(uint64_t bytes)
{
	Geometry geometry = {};

	if (bytes < kBlockSize) {
		bytes = kBlockSize;
	}
	// A whole number of blocks, so a reader can never be handed a partial sector.
	bytes -= bytes % kBlockSize;
	geometry.bytes = bytes;
	geometry.blockSize = kBlockSize;
	geometry.blockCount = bytes / kBlockSize;
	return geometry;
}

bool
read_within(const Geometry &geometry, uint64_t byteOffset, uint64_t length,
    uint64_t *served)
{
	if (served == nullptr) {
		return false;
	}
	*served = 0;
	if (!geometry.valid() || byteOffset >= geometry.bytes) {
		return false;
	}
	const uint64_t remaining = geometry.bytes - byteOffset;
	*served = length < remaining ? length : remaining;
	return *served != 0;
}

bool
write_within(const Geometry &geometry, uint64_t byteOffset, uint64_t length)
{
	if (!geometry.valid() || byteOffset >= geometry.bytes) {
		return false;
	}
	return length <= geometry.bytes - byteOffset;
}

} // namespace native_ram_block
