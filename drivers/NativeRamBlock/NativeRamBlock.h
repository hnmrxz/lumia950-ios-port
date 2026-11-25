// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// NativeRamBlock: the synthetic root media. Geometry lives in RamBlockCore so it can be host tested
// without IOKit; this header is the IOKit half.

#ifndef NATIVE_RAM_BLOCK_H
#define NATIVE_RAM_BLOCK_H

#include <IOKit/storage/IOMedia.h>

#include "RamBlockCore.h"

class NativeRamBlock : public IOMedia {
	OSDeclareDefaultStructors(NativeRamBlock)

public:
	bool start(IOService *provider) override;
	void stop(IOService *provider) override;
	void free() override;

	void read(IOService *client, UInt64 byteOffset, IOMemoryDescriptor *buffer,
	    IOStorageCompletion completion) override;
	void write(IOService *client, UInt64 byteOffset, IOMemoryDescriptor *buffer,
	    IOStorageCompletion completion) override;

private:
	void *buffer = nullptr;
	native_ram_block::Geometry geometry = {};
};

#endif
