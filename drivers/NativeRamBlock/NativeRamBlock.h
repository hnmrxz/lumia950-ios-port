// SPDX-License-Identifier: BSD-2-Clause-Patent
//
// NativeRamBlock: a synthetic block device so `vfs_mountroot` has something to mount.
//
// It is an IOBlockStorageDevice like NativeSdhci, not an IOMedia subclass: the framework turns a storage
// device into an IOMedia and then into the mount the kernel is waiting for, and that is the path that
// already compiles in this tree. The device body is a contiguous buffer whose size comes from the
// ramblock_bytes boot argument (docs/emulation/root-device-design.md).

#ifndef NATIVE_RAM_BLOCK_H
#define NATIVE_RAM_BLOCK_H

#include <IOKit/IOLib.h>
#include <IOKit/IOService.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <IOKit/IOBufferMemoryDescriptor.h>
#include <IOKit/storage/IOBlockStorageDevice.h>

#include "RamBlockCore.h"

class NativeRamBlock : public IOBlockStorageDevice {
	OSDeclareDefaultStructors(NativeRamBlock)

public:
	bool start(IOService *provider) override;
	void stop(IOService *provider) override;
	void free() override;

	// IOBlockStorageDevice
	IOReturn doEjectMedia() override { return kIOReturnUnsupported; }
	IOReturn doFormatMedia(UInt64) override { return kIOReturnUnsupported; }
	UInt32 doGetFormatCapacities(UInt64 *, UInt32) const override { return 0; }
	char *getVendorString() override { return const_cast<char *>("Native"); }
	char *getProductString() override { return const_cast<char *>("Lumia 950 bring-up root media"); }
	char *getRevisionString() override { return const_cast<char *>("0.1"); }
	char *getAdditionalDeviceInfoString() override { return const_cast<char *>("synthetic, read-only"); }
	IOReturn reportBlockSize(UInt64 *value) override;
	IOReturn reportEjectability(bool *value) override;
	IOReturn reportMaxValidBlock(UInt64 *value) override;
	IOReturn reportMediaState(bool *present, bool *changed) override;
	IOReturn reportRemovability(bool *value) override;
	IOReturn reportWriteProtection(bool *value) override;
	IOReturn doSynchronizeCache() override { return ready ? kIOReturnSuccess : kIOReturnNotReady; }
	IOReturn doAsyncReadWrite(IOMemoryDescriptor *buffer, UInt64 block, UInt64 count,
	    IOStorageAttributes *attributes, IOStorageCompletion *completion) override;
	IOReturn getDeviceCharacteristics(OSDictionary **characteristics) override;

private:
	IOBufferMemoryDescriptor *storage = nullptr;
	native_ram_block::Geometry geometry = {};
	bool ready = false;
};

#endif
