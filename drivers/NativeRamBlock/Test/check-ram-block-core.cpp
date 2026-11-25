// Host test for the bring-up root device's geometry arithmetic. Built by scripts/test-ramblock.sh with a
// plain C++ compiler and sanitizers: nothing here may depend on IOKit.

#include "RamBlockCore.h"

#include <cstdio>
#include <cstdlib>

using namespace native_ram_block;

static int failures = 0;

static void
check(bool condition, const char *what)
{
	if (!condition) {
		std::fprintf(stderr, "FAIL %s\n", what);
		failures++;
	}
}

int
main()
{
	// A budget below one block is rounded up to exactly one block, never zero.
	Geometry tiny = geometry_for(1);
	check(tiny.valid(), "a tiny budget still yields a valid geometry");
	check(tiny.blockCount == 1, "a tiny budget yields one block");

	// A budget that is not a whole number of blocks is truncated, never rounded up into the buffer.
	Geometry ragged = geometry_for(kBlockSize * 10 + 7);
	check(ragged.valid(), "a ragged budget yields a valid geometry");
	check(ragged.blockCount == 10, "a ragged budget truncates to whole blocks");
	check(ragged.bytes == kBlockSize * 10, "the byte count follows the block count");

	// The default budget is what the driver asks for when the boot argument is absent.
	Geometry standard = geometry_for(kDefaultBytes);
	check(standard.valid(), "the default budget is valid");
	check(standard.blockCount * standard.blockSize == standard.bytes, "geometry is self-consistent");

	// Reads are clamped to the end of the buffer, and a read past the end is refused.
	std::uint64_t served = 0;
	check(!read_within(standard, standard.bytes, kBlockSize, &served), "a read past the end is refused");
	check(read_within(standard, standard.bytes - kBlockSize, kBlockSize * 4, &served),
	    "a read that overruns the end is still offered");
	check(served == kBlockSize, "an overrunning read is clamped to what remains");
	check(!read_within(standard, 0, 0, nullptr), "a null served pointer is refused");

	// Writes are all-or-nothing: a partial write is refused rather than silently shortened.
	check(write_within(standard, 0, standard.bytes), "a write over the whole buffer is allowed");
	check(!write_within(standard, 0, standard.bytes + 1), "a write past the buffer is refused");
	check(!write_within(standard, standard.bytes, kBlockSize), "a write starting past the end is refused");

	if (failures != 0) {
		std::fprintf(stderr, "%d checks failed\n", failures);
		return EXIT_FAILURE;
	}
	std::printf("ram block core: all checks passed\n");
	return EXIT_SUCCESS;
}
